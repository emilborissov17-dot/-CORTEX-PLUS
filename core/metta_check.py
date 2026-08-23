#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/metta_check.py — СИМВОЛНОТО ВТОРО МНЕНИЕ НА ВСЯКА СТЪПКА (15 август 2026)

Емил, 15 авг: „имаме ли МеТТа и Хиперон връзка на всяка стъпка (като допълнително
мнение и точка за съпоставка)?"

Отговорът беше НЕ. MeTTa стоеше на едно-единствено място (core/cycle_graph.py,
за правото на пропускане). Този модул го прави присъстващ навсякъде — но НЕ като
втори мозък, а като нещо друго и по-полезно: НЕЗАВИСИМ СВИДЕТЕЛ.

РАЗЛИКАТА, която прави това смислено:
  • МОЗЪКЪТ (локален LLM) казва какво МИСЛИ за стъпката — преценка, смисъл, догадка.
  • MeTTa казва какво СЛЕДВА ОТ ФАКТИТЕ — детерминистично, без мнение: този файл
    съществува ли, пресен ли е, кой го чака надолу, удържа ли предишната стъпка
    обещанието си.
  • Когато двамата се РАЗМИНАТ, това се записва. Разминаването е сигналът.

Мозък, който казва „предишната мина добре", докато графът вижда, че обещаният ѝ
файл не е пипнат, е точно случаят, който досега минаваше невидим. Сега двете
твърдения стоят едно до друго в memory/divergence_log.jsonl и утре се съдят по
това кой е бил прав. Това е „верификация над твърдение", приложена към самия мозък.

Цената е нула LLM повиквания: атомите се строят веднъж на цикъл и се преизползват.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
LOG = BASE / "memory" / "divergence_log.jsonl"
NIGHT = BASE / "memory" / "night_events.jsonl"

_CONSUMERS: dict | None = None     # step -> [стъпки надолу, които ядат негов продукт]
_ORDER: dict = {}
_PROD: dict = {}
_REQ: dict = {}
_ENGINE: str | None = None
_NOTED = False                     # мълчанието на MeTTa се обявява веднъж на цикъл
_LAST_BEAT: float | None = None    # начало на прозореца на ТЕКУЩАТА стъпка


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── КЪДЕ ЖИВЕЕ MeTTa ────────────────────────────────────────────────────────
# hyperon е инсталиран САМО в venv312_metta; цикълът се пуска с venv. Ако този
# модул просто беше `from hyperon import MeTTa`, целият слой щеше да е МЪРТЪВ на
# всяка стъпка в реалния цикъл — и, най-лошото, мълчаливо мъртъв: нула записани
# разминавания изглежда точно като „няма разминавания". Затова: когато hyperon го
# няма в текущия интерпретатор, MeTTa се пуска ВЕДНЪЖ на цикъл в своя venv като
# отделен процес, а изводът му се пренася като JSON. Един процес на цикъл, не 53.
def _metta_python() -> Path | None:
    for rel in ("venv312_metta/Scripts/python.exe", "venv312_metta/bin/python"):
        p = BASE / rel
        if p.exists():
            return p
    return None


def _consumers_via_hyperon(since_ts: float) -> tuple:
    """Изчислява consumers чрез MeTTa В ТОЗИ процес. Иска hyperon."""
    from hyperon import MeTTa
    from core.cycle_graph import _atoms
    program, prod, req, order, _fresh = _atoms(since_ts)
    m = MeTTa()
    m.run(program + '''
(= (consumers $s)
   (match &self (produces $s $f)
      (match &self (requires $t $f) ($t $f))))
(= (needs $s)
   (match &self (requires $s $f) $f))
''')
    cons = {}
    for step in order:
        found = []
        for grp in m.run(f"!(consumers {step})"):
            for atom in grp:
                try:
                    t, _f = str(atom).strip("()").split(" ", 1)
                except ValueError:
                    continue
                if order.get(t, 0.0) > order.get(step, 0.0):
                    found.append(t)
        cons[step] = sorted(set(found))
    return cons, prod, req, order


def _consumers_via_subprocess(since_ts: float) -> tuple:
    """Пуска същото изчисление в venv312_metta и връща изводa му."""
    py = _metta_python()
    if not py:
        raise RuntimeError("venv312_metta липсва — няма къде да живее MeTTa")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(BASE))
    r = subprocess.run([str(py), "-m", "core.metta_check", "--export", str(since_ts)],
                       cwd=str(BASE), env=env, capture_output=True, timeout=180)
    txt = r.stdout.decode("utf-8", "replace")
    i = txt.find("{")
    if r.returncode != 0 or i < 0:
        raise RuntimeError(f"exit={r.returncode} {r.stderr.decode('utf-8','replace')[-200:]}")
    d = json.loads(txt[i:])
    return (d["consumers"],
            {k: set(v) for k, v in d["prod"].items()},
            d["req"], d["order"])


def _note_absence(why: str) -> None:
    """MeTTa не е на линия. Това се ЧУВА, а не се преглъща: слой, който мълчи,
    иначе изглежда като слой, който не намира разминавания."""
    global _NOTED
    if _NOTED:
        return
    _NOTED = True
    for path in (NIGHT, LOG):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now(), "subject": "MeTTa НЕ Е НА ЛИНИЯ",
                                     "detail": why, "engine": None,
                                     "consequence": "второто мнение отсъства този цикъл — "
                                                    "нула разминавания НЕ значи съгласие"},
                                    ensure_ascii=False) + "\n")
        except Exception:
            pass


def _build(since_ts: float) -> bool:
    """Строи веднъж на процес. True, ако MeTTa е проговорила."""
    global _CONSUMERS, _ORDER, _PROD, _REQ, _ENGINE
    if _CONSUMERS is not None:
        return _ENGINE is not None
    tried = []
    for name, fn in (("hyperon/MeTTa (in-process)", _consumers_via_hyperon),
                     ("hyperon/MeTTa (venv312_metta)", _consumers_via_subprocess)):
        try:
            cons, prod, req, order = fn(since_ts)
            _CONSUMERS, _PROD, _REQ, _ORDER, _ENGINE = cons, prod, req, order, name
            return True
        except Exception as e:
            tried.append(f"{name}: {type(e).__name__}: {e}")
    # Дори без MeTTa таблицата и скенерът работят — но това НЕ е второ мнение и
    # тук се казва точно така.
    try:
        from core.cycle_graph import _atoms
        _program, prod, req, order, _fresh = _atoms(since_ts)
        _PROD, _REQ, _ORDER = prod, req, order
    except Exception as e:
        tried.append(f"atoms: {type(e).__name__}: {e}")
    _CONSUMERS, _ENGINE = {}, None
    _note_absence(" | ".join(tried)[:400])
    return False


def invalidate(why: str = "") -> None:
    """Изхвърля построения граф. Kimi, 15 авг: „структурата е кеширана, а стъпки
    18-19 пишат НОВ КОД — значи нови requires; графът остарява точно там, където
    системата се променя." Приех го. Вика се след execute_patches/self_modifier."""
    global _CONSUMERS, _ENGINE, _ORDER, _PROD, _REQ
    _CONSUMERS, _ENGINE, _ORDER, _PROD, _REQ = None, None, {}, {}, {}
    if why:
        try:
            NIGHT.parent.mkdir(parents=True, exist_ok=True)
            with open(NIGHT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now(), "subject": "графът се престроява",
                                     "detail": why}, ensure_ascii=False) + "\n")
        except Exception:
            pass


def witness_present(since_ts: float | None = None) -> bool:
    """Има ли свидетел СЕГА. Kimi: „обявяваш отсъствие, но продължаваш — това е
    монолог, не диалог." Приех: отсъствието вече има цена. Необратимите стъпки
    (github_publish, self_modifier, execute_patches) питат тук и НЕ тръгват без
    свидетел. Цикълът продължава да мисли — просто не пипа света и не пипа себе си,
    докато няма кой да го провери."""
    if since_ts is None:
        since_ts = _cycle_start()
    return _build(since_ts)


# ── ТРЕТИЯТ ИЗТОЧНИК: НАБЛЮДЕНИЕТО (Kimi, 15 авг) ──────────────────────────
# „Прикрит втори мозък — _atoms е същата логика, същия автор; независимост изисква
# различен алгоритъм, не просто друга среда."
# Половината от възражението приех: свидетел, чиито предпоставки съм писал аз, не
# лови МОИТЕ грешки. Затова тук влиза факт, който никой не е декларирал — какво
# РЕАЛНО е пипнато на диска в прозореца на стъпката. Той съди таблицата, не мозъка:
# стъпка, която пише недекларирано (таблицата ми е сляпа) или декларира и не пипа
# (таблицата ми лъже).
_WATCH = ("memory", "output", "daily", "plans", "data")
# "self_archive" GUARDS A DIRECTORY THAT DOES NOT EXIST TODAY (23 Aug 2026).
# snapshots/self_archive/ held 45 GB and was deleted by hand once the
# ballooning bug was confirmed gone. The entry stays: it costs one string
# compare, and the documented remediation for that bug is to recreate the
# directory. Removing it means the next person who does gets an rglob over
# 45 GB and has to rediscover why that is slow.
_SKIP = ("self_archive", "__pycache__", ".git", "ucdp")
_MAX_FILES = 6000
# Собственото счетоводство на слоя НЕ се брои за продукт на стъпката — иначе
# свидетелят докладва собствения си подпис като недекларирано писане и всяка
# стъпка изглежда виновна. Изходният код също: .py файл в memory/ е модул, не
# продукт на цикъла.
_IGNORE = ("memory/heartbeat.json", "memory/divergence_log.jsonl",
           "memory/night_events.jsonl", "memory/brain_journal.jsonl",
           "memory/cycle_origin.json", "memory/last_cycle_id.txt",
           "memory/last_attempt.txt", "memory/cycle.lock")


def _countable(rel: str) -> bool:
    return rel not in _IGNORE and not rel.endswith((".py", ".pyc", ".tmp", ".log"))


# Кодът е СЪЩО наблюдаем факт. Изключването на .py по-горе е правилно за продукти
# (модул в memory/ не е продукт на цикъла), но остави сляпо петно точно там, където
# наблюдението е най-нужно: системата пише сама себе си. Затова .py файловете се
# гледат ОТДЕЛНО — и това, че са пипнати ИЗВЪН self_modifier/execute_patches, е
# аларма, не бележка.
_CODE_DIRS = ("core", "agents", "memory", "safety", "experiments", "scripts")
_CODE_ALLOWED_IN = ("self_modifier", "execute_patches")


def observe_code(t0: float, t1: float) -> list:
    """Кои .py файла са пипнати в този прозорец."""
    out = []
    for d in _CODE_DIRS:
        root = BASE / d
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [x for x in dirnames if x not in _SKIP]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = Path(dirpath) / fn
                try:
                    if t0 <= p.stat().st_mtime <= t1:
                        out.append(p.relative_to(BASE).as_posix())
                except Exception:
                    continue
    return sorted(out)[:12]


def observe(step: str, t0: float, t1: float) -> dict:
    """Кои файлове реално са пипнати между t0 и t1, срещу декларираното."""
    touched, n = [], 0
    for d in _WATCH:
        root = BASE / d
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [x for x in dirnames if x not in _SKIP]
            for fn in filenames:
                n += 1
                if n > _MAX_FILES:
                    break
                p = Path(dirpath) / fn
                try:
                    m = p.stat().st_mtime
                except Exception:
                    continue
                if t0 <= m <= t1:
                    try:
                        rel = p.relative_to(BASE).as_posix()
                    except Exception:
                        continue
                    if _countable(rel):
                        touched.append(rel)
            if n > _MAX_FILES:
                break
    declared = {f for f in _PROD.get(step, set())}
    tset = set(touched)
    # декларираното се брои за пипнато и когато е папка, в която нещо се е променило
    kept = {d for d in declared
            if d in tset or any(t.startswith(d.rstrip("/") + "/") for t in tset)}
    out = {"touched": len(touched), "capped": n > _MAX_FILES,
           "wrote_undeclared": sorted(tset - {t for t in tset
                                              if any(t == d or t.startswith(d.rstrip("/") + "/")
                                                     for d in declared)})[:12],
           "declared_untouched": sorted(declared - kept)[:12]}
    return out


def _cycle_start() -> float:
    try:
        hb = json.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
        return datetime.fromisoformat(hb["cycle_id"]).timestamp()
    except Exception:
        return datetime.now(timezone.utc).timestamp() - 86400


def verdict(step: str, since_ts: float | None = None) -> dict:
    """Какво казват ФАКТИТЕ за тази стъпка — без мнение, без LLM.

    Връща:
      needs_missing — входове, които стъпката чете, но ги няма/стари са
      feeds         — кой надолу чака нейния продукт
      prev_promise  — удържала ли е предишната стъпка обявения си файл
    """
    out = {"step": step, "engine": None}
    if since_ts is None:
        try:
            hb = json.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
            since_ts = datetime.fromisoformat(hb["cycle_id"]).timestamp()
        except Exception:
            since_ts = datetime.now(timezone.utc).timestamp() - 86400
    spoke = _build(since_ts)
    out["engine"] = _ENGINE
    if not spoke:
        out["silent"] = "MeTTa не е на линия — това НЕ е съгласие, а липса на свидетел"

    try:
        from core.cycle_graph import _freshness
        needs = _REQ.get(step, [])
        states = _freshness(set(needs), since_ts)
        out["needs_missing"] = [f"{f}({states.get(f)})" for f in needs
                                if states.get(f) != "fresh"]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["needs_missing"] = []
    out["feeds"] = list((_CONSUMERS or {}).get(step, []))
    return out


def compare(step: str, prev_step: str | None, brain_says: dict | None,
            since_ts: float | None = None) -> dict:
    """Слага мнението на мозъка до извода от фактите и записва РАЗМИНАВАНЕТО.

    Мозъкът твърди `prev_ok` за предишната стъпка. Таблицата знае какъв файл е
    обещала тя. Ако мозъкът казва „добре", а файлът не е пипнат — това е точно
    невидимият досега случай, и тук получава ред в дневника."""
    global _LAST_BEAT
    now_ts = datetime.now(timezone.utc).timestamp()
    window_t0, _LAST_BEAT = _LAST_BEAT, now_ts

    v = verdict(step, since_ts)
    rec = {"ts": _now(), "step": step, "facts": v}
    if prev_step:
        # ТРЕТИЯТ ИЗТОЧНИК: какво реално е пипнато, докато предишната стъпка е текла.
        if window_t0:
            try:
                obs = observe(prev_step, window_t0, now_ts)
                rec["observed"] = obs
                if obs["wrote_undeclared"]:
                    rec["table_blind"] = (f"{prev_step} е пипнала недекларирани файлове: "
                                          f"{', '.join(obs['wrote_undeclared'][:4])}")
                if obs["declared_untouched"]:
                    rec["table_lies"] = (f"{prev_step} декларира, но не е пипнала: "
                                         f"{', '.join(obs['declared_untouched'][:4])}")
                code = observe_code(window_t0, now_ts)
                if code:
                    rec["code_touched"] = code
                    if prev_step not in _CODE_ALLOWED_IN:
                        rec["code_changed_outside_selfmod"] = (
                            f"{prev_step} е пипнала СОБСТВЕНИЯ код извън стъпките за "
                            f"самопромяна: {', '.join(code[:4])}")
            except Exception:
                pass
        try:
            from core import cycle_map as cm
            if since_ts is None:
                since_ts = _cycle_start()
            kept, detail = cm.kept_promise(prev_step, since_ts)
            rec["prev_step"] = prev_step
            rec["prev_promise"] = kept
            rec["prev_detail"] = detail[:120]
            if brain_says is not None:
                said_ok = str(brain_says.get("prev_ok")).lower() in ("true", "1", "yes")
                rec["brain_prev_ok"] = said_ok
                rec["brain_note"] = str(brain_says.get("prev_note", ""))[:200]
                if said_ok and kept == "НЕ ПИПНА":
                    rec["divergence"] = (f"мозъкът каза, че {prev_step} е минала добре, "
                                         f"а обещаният ѝ файл не е пипнат")
                elif (not said_ok) and kept == "ОБНОВИ":
                    rec["divergence"] = (f"мозъкът се усъмни в {prev_step}, а тя "
                                         f"е обновила обещаното")
        except Exception:
            pass

    if (rec.get("divergence") or rec.get("table_blind") or rec.get("table_lies")
            or rec.get("code_changed_outside_selfmod") or v.get("needs_missing")):
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            if LOG.exists() and LOG.stat().st_size > 5_000_000:
                LOG.replace(LOG.with_suffix(".jsonl.1"))
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return rec


def _export(since_ts: float) -> None:
    """Режимът, в който този модул се пуска ВЪТРЕ в venv312_metta: смята чрез
    MeTTa и подава извода на процеса, който няма hyperon."""
    cons, prod, req, order = _consumers_via_hyperon(since_ts)
    print(json.dumps({"consumers": cons, "prod": {k: sorted(v) for k, v in prod.items()},
                      "req": req, "order": order}, ensure_ascii=False))


if __name__ == "__main__":
    if "--export" in sys.argv:
        _export(float(sys.argv[sys.argv.index("--export") + 1]))
    else:
        s = next((a for a in sys.argv[1:] if not a.startswith("--")), "deduction")
        print(json.dumps(verdict(s), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_report.py — ОТЧЕТЪТ НА ЦИКЪЛА, НАПИСАН ОТ САМАТА СИСТЕМА (15 авг 2026)

Емил, 15 август: "ВАЖНО Е ДА ИМА РАЗБИРАЕМА ОТЧЕТНОСТ И ЗА МЕН ..... КАКВО СЕ
СЛУЧВА НА ВСЯКА СТЪПКА ОТ ЦИКЪЛА И КАКВО Е РЕШИЛА СИСТЕМАТА .... НО НАПИСАНО ОТ
САМАТА СИСТЕМА".

Затова тук НЯМА мои формулировки за това какво е станало. Отчетът се сглобява от:

  • думите на МОЗЪКА за всяка стъпка (memory/brain_step_log.jsonl — какво е
    заварил от предишната и какво е очаквал от следващата);
  • ИСТИНСКИЯ изход на всяка стъпка от лога на цикъла (редовете, които тя сама е
    напечатала);
  • МЕХАНИЧНА проверка удържала ли е обещанието си (core/cycle_map.kept_promise —
    обновил ли се е файлът, който стъпката е декларирала, че произвежда);
  • откриващ и закриващ абзац, написани от мозъка (не от мен).

Стъпка, която пише "-> OK" и не пипва нито един от обявените си файлове, излиза
в отчета като НЕ ПИПНА. Точно това не се виждаше досега.

  venv\\Scripts\\python.exe -m core.cycle_report          # отчет за последния цикъл
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT_DIR = BASE / "output" / "reports"
STEP_LOG = BASE / "memory" / "brain_step_log.jsonl"
PLAN = BASE / "memory" / "brain_cycle_plan.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_log() -> Path | None:
    logs = sorted((BASE / "memory" / "cycle_logs").glob("cycle_*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _steps_from_log(log_path: Path) -> list:
    """Истинският изход на всяка стъпка — редовете между два [STEP] маркера.
    Това са ДУМИТЕ НА САМАТА СТЪПКА, не мой преразказ."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    out, cur = [], None
    for l in lines:
        s = l.strip()
        if s.startswith("[STEP] "):
            if cur:
                out.append(cur)
            cur = {"step": s[7:].strip(), "lines": []}
        elif cur is not None and s:
            cur["lines"].append(s[:220])
    if cur:
        out.append(cur)
    if out:
        return out
    # Логове отпреди 15 авг 2026 нямат [STEP] маркери (пулсът започна да ги пише
    # чак тогава). За тях се групира по реда "[FAST_CYCLE] <етикет> -> ...", за да
    # има отчет и за миналото, а не празна таблица.
    grouped: dict = {}
    for l in lines:
        m = re.match(r"\[FAST_CYCLE\]\s+([A-Za-z_0-9]+)\s*->", l.strip())
        if m:
            grouped.setdefault(m.group(1), []).append(l.strip()[:220])
    return [{"step": k, "lines": v} for k, v in grouped.items()]


def _brain_words(cycle_start: float) -> dict:
    """Какво е казал мозъкът на всяка стъпка ПРЕЗ ТОЗИ цикъл."""
    words = {}
    try:
        for line in STEP_LOG.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
                ts = datetime.fromisoformat(d["ts"]).timestamp()
            except Exception:
                continue
            if ts >= cycle_start:
                words[d.get("step")] = d
    except Exception:
        pass
    return words


_SIGNAL = re.compile(r"(FAILED|ERROR|Traceback|SKIP|DEAD|WARN|->)", re.I)


def build(cycle_start: float | None = None) -> dict:
    log_path = _latest_log()
    if not log_path:
        return {"error": "няма лог на цикъл"}
    if cycle_start is None:
        # началото на цикъла = времето на файла минус неговата продължителност;
        # най-надеждно: първият ред на лога, иначе mtime на самия файл.
        try:
            head = log_path.read_text(encoding="utf-8", errors="ignore")[:400]
            m = re.search(r"started at ([0-9T:\-\.]+)", head)
            cycle_start = datetime.fromisoformat(m.group(1)).timestamp() if m \
                else log_path.stat().st_mtime - 3600
        except Exception:
            cycle_start = log_path.stat().st_mtime - 3600

    from core import cycle_map as cm
    steps = _steps_from_log(log_path)
    words = _brain_words(cycle_start)

    rows = []
    for s in steps:
        name = s["step"]
        verdict, detail = cm.kept_promise(name, cycle_start)
        bw = words.get(name, {})
        rows.append({
            "step": name,
            "purpose": cm.purpose(name) or "(не е в таблицата — нова или преименувана стъпка)",
            "said": [l for l in s["lines"] if _SIGNAL.search(l)][:6] or s["lines"][:3],
            "promise": verdict, "promise_detail": detail,
            "brain_saw": bw.get("prev_note", ""),
            "brain_expected": bw.get("expect", ""),
            "brain_stance": bw.get("stance", ""),
        })

    plan = {}
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
    except Exception:
        pass

    broken = [r for r in rows if r["promise"] == "НЕ ПИПНА"]
    failed = [r for r in rows if any("FAILED" in l or "Traceback" in l for l in r["said"])]

    # ── ДУМАТА Е НА СИСТЕМАТА: откриване и закриване пише мозъкът ────────────
    opening = closing = None
    try:
        from core import brain
        digest = "\n".join(
            f"{r['step']}: обещание={r['promise']}; каза={' | '.join(r['said'])[:160]}"
            for r in rows)
        d = brain.think(
            role="отчитащ се пред човека",
            question=("Това е твоят цикъл — какво направи всяка стъпка и удържа ли тя "
                      "обещания си файл. Обясни на човека С ТВОИ ДУМИ какво се случи "
                      "днес и какво реши ти. Без ласкателство: ако нещо е било кухо, "
                      "кажи го. Пиши на български, кратко и разбираемо."),
            evidence=("ТВОЯТ ПЛАН:\n" + json.dumps(plan, ensure_ascii=False)[:800] +
                      "\n\nСТЪПКИТЕ:\n" + digest[-4000:]),
            schema={"opening": "3-4 изречения: какво стана днес, с твои думи",
                    "decisions": "какво реши ТИ днес (списък, кратко)",
                    "worry": "кое те притеснява най-много в този цикъл",
                    "closing": "едно изречение: беше ли този цикъл успешен и защо"},
            kind="cycle_report")
        if d:
            opening, closing = d, d
    except Exception:
        pass

    return {"ts": _now(), "log": str(log_path.relative_to(BASE)),
            "cycle_start": cycle_start, "plan": plan, "rows": rows,
            "broken": [r["step"] for r in broken], "failed": [r["step"] for r in failed],
            "brain": opening}


def to_markdown(rep: dict) -> str:
    if rep.get("error"):
        return f"# Отчет — {rep['error']}"
    b = rep.get("brain") or {}
    day = str(rep["ts"])[:10]
    out = [f"# ОТЧЕТ ЗА ЦИКЪЛА — {day}", ""]

    if b:
        out += ["## Думата на системата", "",
                str(b.get("opening", "")).strip(), "",
                "**Какво реших днес:** " + str(b.get("decisions", "")).strip(), "",
                "**Какво ме притеснява:** " + str(b.get("worry", "")).strip(), "",
                f"> {str(b.get('closing','')).strip()}", ""]
    else:
        out += ["## Думата на системата", "",
                "_(мозъкът мълчеше при съставянето на този отчет — "
                "долното е само механичната истина)_", ""]

    # Емил, 15 авг: „да не ме будят — искам само докладите за изминал ден."
    # Значи всичко, което системата е преживяла сама през нощта, трябва да го
    # има ТУК. Иначе тишината нощем става тишина и сутрин.
    try:
        ev = [json.loads(l) for l in
              (BASE / "memory" / "night_events.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip()]
        ev = [e for e in ev if e.get("ts", "") >= str(rep.get("ts", ""))[:10]]
        if ev:
            out += ["## Какво стана през нощта, докато спеше", "",
                    f"{len(ev)} събития, с които системата се справи сама "
                    f"(или не се справи) без да те буди:", ""]
            for e in ev[-10:]:
                out.append(f"- **{str(e.get('ts'))[11:16]}** — {e.get('subject')}: "
                           f"{str(e.get('detail','')).replace(chr(10), ' ')[:220]}")
            out.append("")
    except Exception:
        pass

    # РАЗМИНАВАНИЯТА мозък-срещу-факти (Емил, 15 авг: MeTTa като точка за
    # съпоставка на всяка стъпка). Ако мозъкът е казал едно, а фактите друго —
    # човекът трябва да го види, а не да се разчита, че някой ще отвори лог.
    try:
        _dv = [json.loads(l) for l in
               (BASE / "memory" / "divergence_log.jsonl").read_text(encoding="utf-8").splitlines()
               if l.strip()]
        _dv = [d for d in _dv if d.get("divergence")
               and d.get("ts", "") >= str(rep.get("ts", ""))[:10]]
        if _dv:
            out += ["## Където мозъкът и фактите не се разбраха", "",
                    f"{len(_dv)} разминавания този цикъл (MeTTa срещу преценката на мозъка):", ""]
            for d in _dv[:8]:
                out.append(f"- `{d.get('step')}` — {d.get('divergence')}")
            out.append("")

        # ТАБЛИЦАТА СРЕЩУ НАБЛЮДЕНИЕТО (Kimi, 15 авг: „свидетел, чиито предпоставки
        # си писал ти, не лови твоите грешки"). Тук се съди НЕ мозъкът, а моята
        # декларация: стъпка, която пише недекларирано, или декларира и не пипа.
        _tb = [json.loads(l) for l in
               (BASE / "memory" / "divergence_log.jsonl").read_text(encoding="utf-8").splitlines()
               if l.strip()]
        _tb = [d for d in _tb if (d.get("table_blind") or d.get("table_lies"))
               and d.get("ts", "") >= str(rep.get("ts", ""))[:10]]
        if _tb:
            out += ["## Където таблицата се разминава с диска", "",
                    "Това не съди мозъка, а собственото ми описание на цикъла — "
                    "сравнено с това, което наистина е пипнато:", ""]
            for d in _tb[:8]:
                for key in ("table_blind", "table_lies"):
                    if d.get(key):
                        out.append(f"- {d[key]}")
            out.append("")
    except Exception:
        pass

    # ПРАЗНИТЕ СЕКЦИИ (15 авг 2026). Източник, който не дава нищо, не е източник —
    # но дотук се броеше за такъв, защото празнотата не влизаше в никой брояч.
    try:
        _gi = json.loads((BASE / "snapshots" / "master" /
                          "global_indicators_latest.json").read_text(encoding="utf-8"))
        _sil = (_gi.get("_health") or {}).get("silent_sections") or []
        if _sil:
            out += ["## Източници, които мълчаха", "",
                    f"{len(_sil)} секции не дадоха НИТО ЕДНА стойност. Те се броят "
                    f"сред източниците, но не носят данни:", ""]
            for s in _sil:
                out.append(f"- `{s.get('section')}` — {s.get('source')}")
            out.append("")
    except Exception:
        pass

    # ОТХВЪРЛЕНИТЕ ЧИСЛА (консенсус с Kimi, 15 авг 2026). Отхвърленото не е липсващо
    # и разликата трябва да се вижда от човека, а не да се лови от логовете.
    #
    # ПОПРАВЕНА ПРЕПРАТКА (17 авг 2026). Този текст пращаше човека към
    # `attestation/quarantine_attestations.jsonl`. Този файл НЕ СЪЩЕСТВУВА и никога
    # не е съществувал — той е FALLBACK в core/source_trust.bury(), който се пише
    # само когато сензориумът е недостъпен. По подразбиране отхвърленото число отива
    # в сензорната СЯНКА (penumbra, Merkle-верига) и crypt_ref сочи натам.
    # Отчет, който праща човека към несъществуващ файл, е по-лош от отчет без
    # препратка: първият изглежда проверим.
    try:
        _gi = json.loads((BASE / "snapshots" / "master" /
                          "global_indicators_latest.json").read_text(encoding="utf-8"))
        _rej = _gi.get("_rejected") or []
        if _rej:
            out += ["## Числа, които системата ОТХВЪРЛИ", "",
                    f"{len(_rej)} стойности не влязоха в оценката. Те не липсват — "
                    f"отхвърлени са. Всяко е погребано от `core/source_trust.bury()` "
                    f"в сензорната сянка (penumbra) и `crypt_ref` по-долу сочи към "
                    f"него. Ако сензориумът е бил недостъпен, записът е паднал във "
                    f"`attestation/quarantine_attestations.jsonl` и веригата за това "
                    f"число ЛИПСВА — тогава файлът съществува, иначе не:", ""]
            for r in _rej[:10]:
                out.append(f"- `{r.get('section')}.{r.get('metric')}` — "
                           f"{r.get('reason')} (crypt_ref `{r.get('crypt_ref')}`)")
            out.append("")
    except Exception:
        pass

    # ПОКРИТИЕТО НА КОМПОЗИТА (консенсус с Kimi, 15 авг 2026). Дотук отчетът
    # показваше едно число. Число при 32% незнание не е оценка — затова тук стои
    # заедно с това КОЛКО от целта изобщо е измерена.
    try:
        _g = json.loads((BASE / "memory" / "goal_score_history.json")
                        .read_text(encoding="utf-8"))
        _last = _g[-1] if isinstance(_g, list) and _g else _g
        _cov = (_last or {}).get("coverage")
        if _cov is not None:
            _valid = (_last or {}).get("composite_valid")
            _un = (_last or {}).get("unmeasured_axes") or []
            out += ["## Колко от целта изобщо е измерена", "",
                    f"- покритие: **{_cov:.0%}** от теглото стои зад реално число",
                    f"- композитът {'ВАЛИДЕН' if _valid else 'НЕ Е ВАЛИДЕН — не го чети като оценка'}"]
            if _un:
                out.append(f"- без нито едно число: {', '.join(_un[:8])}"
                           + (f" (+{len(_un) - 8})" if len(_un) > 8 else ""))
            out.append("")
    except Exception:
        pass

    # ── ДЪЛГЪТ НА ЧОВЕКА (Емил, 21 авг 2026) ───────────────────────────────
    # Системата брои какво ДЪЛЖИ — неизмерени оси, мълчащи източници, стъпки
    # без следа. Никой не броеше какво Й СЕ ДЪЛЖИ. Обещанието е отговор до 24
    # часа; ето колко предложения го чакат и от колко време.
    try:
        from core.proposal_sla import for_cycle_report as _sla
        _s = _sla()
        if _s.get("open"):
            out += ["## Дългът на човека", "", f"- {_s['line']}", ""]
            if _s.get("oldest_five"):
                out.append("Най-дълго чакащите:")
                for r in _s["oldest_five"]:
                    out.append(f"- {r['days']} дни · `{r['id']}` — {r['title'][:80]}")
                out.append("")
            out.append(f"- по вид: " + ", ".join(
                f"{k} ×{v}" for k, v in (_s.get("by_kind") or {}).items()))
            out.append("")
    except Exception:
        pass

    # ── КОНТИНЕНТИТЕ (21 авг 2026) ─────────────────────────────────────────
    # wellbeing_globe смята този слой от 2 юли и никой доклад не го е показвал:
    # цялата планета се отчиташе с едно число, докато разбивка на седем реда от
    # същите данни стоеше непрочетена на диска. Терминът към човека е КОНТИНЕНТ
    # навсякъде; кодът на Световната банка си остава само join ключ.
    try:
        from core.continents import render_markdown as _cont_md
        _cont = _cont_md()
        if _cont:
            out += _cont
    except Exception:
        pass

    # ── ОСИТЕ ОТВЪД ЦЕЛТА СИ, С АТРИБУЦИЯ ──────────────────────────────────
    # R4 казва, че оста е от грешната страна на собствената си цел. Глобално
    # число, лошо навсякъде, и глобално число, лошо на едно място, искат
    # различен отговор — а самата ос не ги различава.
    try:
        from core.continents import attribution as _attr
        _mt = json.loads((BASE / "memory" / "metta_assessment_latest.json")
                         .read_text(encoding="utf-8"))
        _r4 = [d for d in (_mt.get("disagreements") or [])
               if d.get("rule") == "R4_OFF_TARGET"]
        if _r4:
            out += ["## Оси отвъд собствената си цел", "",
                    f"{len(_r4)} оси стоят от грешната страна на целта си:", ""]
            _lead = _attr("")
            for d in _r4[:10]:
                line = f"- **{d.get('axis')}** — {d.get('says')}"
                if _lead:
                    line += f" · {_lead}"
                out.append(line)
            out.append("")
    except Exception:
        pass

    # постоянството и съзвездието — прочит, който не гони промяната (15 авг)
    try:
        cn = json.loads((BASE / "memory" / "constancy_latest.json").read_text(encoding="utf-8"))
        cc = cn.get("counts", {})
        out += ["## Показателите: какво стои и какво мърда", "",
                f"От {cc.get('total')} проследени показателя **{cc.get('still')} стоят неподвижни**, "
                f"а {cc.get('alarm')} са отбелязани от системата като тревожни.", ""]
        still_ok = [r for r in cn.get("rows", [])
                    if str((r.get("verdict") or {}).get("healthy")).lower() == "true"
                    and r.get("observed") != "ПОДВИЖНА"]
        if still_ok:
            out += ["Неподвижни и **здрави** — постоянството им е добрата новина:", ""]
            for r in still_ok[:6]:
                v = r["verdict"]
                out.append(f"- `{r['axis']}.{r['metric']}` = {r['last']} — "
                           f"{v.get('expected_regime')}: {str(v.get('reading',''))[:140]}")
            out.append("")
        alarms = [r for r in cn.get("rows", [])
                  if str((r.get("verdict") or {}).get("alarm")).lower() == "true"]
        if alarms:
            out += ["Тревожни:", ""]
            for r in alarms[:6]:
                v = r["verdict"]
                out.append(f"- `{r['axis']}.{r['metric']}` ({r['observed']}, последно {r['last']}) — "
                           f"{str(v.get('reading',''))[:160]}")
            out.append("")
    except Exception:
        pass
    try:
        st = json.loads((BASE / "memory" / "constellation_latest.json").read_text(encoding="utf-8"))
        out += ["## Показателите, четени заедно", "",
                f"**Най-показателното:** {st.get('most_telling')}", ""]
        rels = st.get("relations")
        if isinstance(rels, list):
            out += [f"- {x}" for x in rels[:6]] + [""]
        elif rels:
            out += [str(rels), ""]
        if st.get("what_would_change_my_mind"):
            out += [f"_Какво би оборило този прочит: {st['what_would_change_my_mind']}_", ""]
    except Exception:
        pass

    p = rep.get("plan") or {}
    if p:
        out += ["## Планът, който сама си зададе сутринта", "",
                f"- **Фокус:** {p.get('focus')}",
                f"- **Защо:** {p.get('why')}",
                f"- **Следи:** {p.get('watch')}",
                f"- **Подозрение към себе си:** {p.get('suspicion')}",
                f"- **Свой тест за успех:** {p.get('success_test')}", ""]

    if rep["broken"]:
        out += ["## ⚠ Стъпки, които казаха ОК, но не пипнаха обещаното", "",
                ", ".join(f"`{s}`" for s in rep["broken"]), ""]
    if rep["failed"]:
        out += ["## ⚠ Стъпки с явна грешка", "",
                ", ".join(f"`{s}`" for s in rep["failed"]), ""]

    out += ["## Стъпка по стъпка", "",
            "| Стъпка | За какво служи | Какво каза самата тя | Удържа ли обещанието | Какво видя мозъкът |",
            "|---|---|---|---|---|"]
    for r in rep["rows"]:
        said = "<br>".join(x.replace("|", "/") for x in r["said"][:3]) or "—"
        seen = (r["brain_saw"] or "—").replace("|", "/")[:120]
        out.append(f"| `{r['step']}` | {r['purpose'][:90]} | {said[:220]} | "
                   f"**{r['promise']}** — {r['promise_detail'][:70]} | {seen} |")
    out += ["", f"_Отчетът е сглобен от {rep['log']} и от собствените записи на "
                f"мозъка. Колоната „удържа ли обещанието\" е механична проверка на "
                f"файловете, обявени в `core/cycle_map.py` — не е мнение._"]
    return "\n".join(out)


def telegram_text(rep: dict) -> str:
    b = rep.get("brain") or {}
    day = str(rep.get("ts", ""))[:10]
    lines = [f"ОТЧЕТ {day}"]
    if b:
        lines += [str(b.get("opening", ""))[:400], "",
                  "Реших: " + str(b.get("decisions", ""))[:200],
                  "Тревожи ме: " + str(b.get("worry", ""))[:200]]
    if rep.get("broken"):
        lines.append("Кухи стъпки: " + ", ".join(rep["broken"][:6]))
    if rep.get("failed"):
        lines.append("Паднали: " + ", ".join(rep["failed"][:6]))
    return "\n".join(lines)[:1500]


def run() -> str | None:
    """Сглобява, записва и връща пътя до отчета."""
    rep = build()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = str(rep.get("ts", _now()))[:10]
    md = OUT_DIR / f"CYCLE_REPORT_{day}.md"
    md.write_text(to_markdown(rep), encoding="utf-8")
    (OUT_DIR / f"cycle_report_{day}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(md.relative_to(BASE))


if __name__ == "__main__":
    print(run())

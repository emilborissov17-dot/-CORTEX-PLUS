#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_graph.py — ГРАФЪТ НА ЗАВИСИМОСТИТЕ В MeTTa (15 август 2026)

Роден от възражение на Kimi (независим опонент, същия ден), който събори
критерия ми за пропускане на стъпки:

  „Критерият е сгрешен по същество, защото разделя по имплементационна обвивка
   (wrapper vs inline), а не по семантична критичност... Това не е 'гръбнак',
   а коремна кухина със спинален имплант."
  „Нужен е граф на зависимости... или системата е автономна и носи отговорност,
   или не е — но този хибрид е най-лошият от двата свята."

И от въпрос на Емил: „това не е ли идеална роля за MeTTa на Хиперон?" — да, и
това е първото място в проекта, където символният слой не е украса.

РАЗДЕЛЕНИЕТО НА ТРУДА (закон на мозъка, т.1 и т.4):
  • МОЗЪКЪТ решава ИСКА ЛИ да пропусне стъпка — това е преценка и е негова.
  • MeTTa изчислява МОЖЕ ЛИ — това не е мнение, а извод от факти.
  • Действие има само при „да" от двамата.
Така границата вече не е моят ръчен списък от 7 стъпки, а следствие от графа.

ФАКТИТЕ НЕ СА ИЗМИСЛЕНИ. `produces` идва от core/cycle_map.py; `requires` се
ИЗВЕЖДА МЕХАНИЧНО от кода: за всяка стъпка се намират модулите, които тя внася
в fast_cycle_runner.py, и в тях се търсят литерални пътища до файлове. Каквото
не е изведено, стои като НЕИЗВЕСТНО — и неизвестното НЕ е пропускаемо. Точно
обратното на старото правило, където необявеното минаваше за безопасно.

  venv312_metta\\Scripts\\python.exe -m core.cycle_graph --selftest
  venv312_metta\\Scripts\\python.exe -m core.cycle_graph can_skip web_intelligence
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
RUNNER = BASE / "fast_cycle_runner.py"
OUT = BASE / "memory" / "cycle_graph_latest.json"

# литерален път до файл в кода: "memory/x.json", 'config/y.json', ...
_PATH_RE = re.compile(r'["\']((?:memory|snapshots|config|output|data|news)/[\w./-]+'
                      r'\.(?:json|jsonl|txt|md|csv))["\']')
# BASE / "memory" / "x.json"
_BASE_RE = re.compile(r'BASE\s*/\s*["\'](\w+)["\']\s*/\s*["\']([\w.-]+)["\']')
_IMPORT_RE = re.compile(r'^\s*(?:from|import)\s+([\w.]+)', re.M)


def _module_file(dotted: str) -> Path | None:
    p = BASE / (dotted.replace(".", "/") + ".py")
    if p.exists():
        return p
    p2 = BASE / dotted.replace(".", "/") / "__init__.py"
    return p2 if p2.exists() else None


def _paths_in(text: str) -> set:
    return set(_PATH_RE.findall(text)) | {f"{a}/{b}" for a, b in _BASE_RE.findall(text)}


def scan_requires() -> dict:
    """{стъпка: {файлове, които нейният код ЧЕТЕ}} — изведено, не декларирано.

    Взима региона на всяка стъпка в fast_cycle_runner (между два beat()), събира
    внесените модули и претърсва техните файлове за литерални пътища. Плитко е
    (един слой внасяне), затова покритието се отчита ЧЕСТНО, а не се допълва с
    предположения."""
    try:
        src = RUNNER.read_text(encoding="utf-8")
    except Exception:
        return {}
    beats = [(m.start(), m.group(1)) for m in re.finditer(r'beat\("([^"]+)"', src)]
    out: dict = {}
    for i, (pos, name) in enumerate(beats):
        end = beats[i + 1][0] if i + 1 < len(beats) else len(src)
        region = src[pos:end]
        files = _paths_in(region)
        for dotted in set(_IMPORT_RE.findall(region)):
            f = _module_file(dotted)
            if f:
                try:
                    files |= _paths_in(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
        out.setdefault(name, set()).update(files)
    return {k: sorted(v) for k, v in out.items()}


def _hollow(p: Path) -> bool:
    """Празна черупка: файлът съществува, но не носи нищо.

    Възражение на Kimi (15 авг): „Графът ще излъже, когато продуктът съществува
    и не е остарял, но е семантично неверен — празен, грешен формат, или от мъртъв
    източник с HTTP 200. MeTTa вижда артефакт, не вижда истината." Затова тук
    съществуването НЕ е достатъчно: празен JSON, празен списък и файл под 3 байта
    се броят за липсващи. Това не е пълна семантична валидация — то е първият ѝ
    праг, и го казвам така, а не по-скъпо."""
    try:
        if p.is_dir():
            return not any(c.is_file() for c in p.rglob("*"))
        if p.stat().st_size < 3:
            return True
        if p.suffix in (".json",):
            d = json.loads(p.read_text(encoding="utf-8"))
            return d in ({}, [], "", None) or (isinstance(d, dict) and not any(
                v not in ({}, [], None, "") for v in d.values()))
        if p.suffix == ".jsonl":
            return not p.read_text(encoding="utf-8").strip()
    except Exception:
        return True          # нечетимо = негодно за консумация
    return False


def _freshness(files: set, since_ts: float) -> dict:
    """Състояние на всеки продукт: fresh / stale / missing / hollow.
    Само `fresh` върши работа надолу; всичко останало спира пропускането."""
    st = {}
    for rel in files:
        p = BASE / rel
        try:
            m = (max((c.stat().st_mtime for c in p.rglob("*") if c.is_file()), default=0)
                 if p.is_dir() else p.stat().st_mtime)
        except Exception:
            st[rel] = "missing"
            continue
        if _hollow(p):
            st[rel] = "hollow"
        else:
            st[rel] = "fresh" if m >= since_ts else "stale"
    return st


def _atoms(since_ts: float) -> tuple:
    from core import cycle_map as cm
    req = scan_requires()
    prod = {}
    order = {}
    for name, idx, _p, produces, _bb in cm.STEPS:
        prod.setdefault(name, set()).update(produces)
        try:
            order[name] = float(idx)
        except Exception:
            order[name] = 0.0

    all_files = set()
    for s in prod.values():
        all_files |= set(s)
    for s in req.values():
        all_files |= set(s)
    fresh = _freshness(all_files, since_ts)

    lines = []
    for s, fs in prod.items():
        for f in fs:
            lines.append(f'(produces {s} "{f}")')
    for s, fs in req.items():
        own = prod.get(s, set())
        for f in fs:
            if f not in own:                     # четене на собствения си изход не е зависимост
                lines.append(f'(requires {s} "{f}")')
    for s, o in order.items():
        lines.append(f'(order {s} {o})')
    for f, state in fresh.items():
        lines.append(f'({state} "{f}")')
    return "\n".join(lines), prod, req, order, fresh


def can_skip(step: str, since_ts: float | None = None) -> dict:
    """Може ли тази стъпка да бъде пропусната, без някой надолу да остане гладен.

    Връща verdict: РАЗРЕШЕНО / ЗАБРАНЕНО / НЕИЗВЕСТНО (= забранено).
    НЕИЗВЕСТНО е нарочно консервативно: липсата на знание за зависимост НЕ Е
    доказателство за независимост."""
    if since_ts is None:
        since_ts = datetime.now(timezone.utc).timestamp() - 86400
    program, prod, req, order, fresh = _atoms(since_ts)

    try:
        from hyperon import MeTTa
    except Exception as e:
        return {"step": step, "verdict": "НЕИЗВЕСТНО", "engine": None,
                "why": f"MeTTa не се зарежда ({type(e).__name__}) — без граф няма разрешение",
                "blockers": []}

    m = MeTTa()
    m.run(program + '''
(= (consumers $s)
   (match &self (produces $s $f)
      (match &self (requires $t $f) ($t $f))))
''')
    raw = m.run(f'!(consumers {step})')
    blockers = []
    for grp in raw:
        for atom in grp:
            try:
                t, f = str(atom).strip("()").split(" ", 1)
            except ValueError:
                continue
            f = f.strip('"')
            if order.get(t, 0.0) <= order.get(step, 0.0):
                continue                     # нагоре по реда не е гладен от нас
            if fresh.get(f) == "fresh":
                continue                     # продуктът вече е пресен от друг
            blockers.append({"consumer": t, "file": f, "state": fresh.get(f, "missing")})

    known = step in req or step in prod
    verdict = ("ЗАБРАНЕНО" if blockers else
               "РАЗРЕШЕНО" if known else "НЕИЗВЕСТНО")
    why = ("надолу по реда има стъпка, която чете неин продукт, а той липсва или е стар"
           if blockers else
           "никой надолу не чака неин продукт" if verdict == "РАЗРЕШЕНО" else
           "за тази стъпка няма изведени нито входове, нито изходи — "
           "незнанието не е разрешение")
    return {"step": step, "verdict": verdict, "engine": "hyperon/MeTTa",
            "why": why, "blockers": blockers,
            "declared_products": sorted(prod.get(step, [])),
            "derived_requires": req.get(step, [])}


def coverage() -> dict:
    from core import cycle_map as cm
    req = scan_requires()
    steps = [s[0] for s in cm.STEPS]
    prod = {s[0] for s in cm.STEPS if s[3]}
    with_req = {s for s in steps if req.get(s)}
    return {"steps_in_table": len(set(steps)),
            "with_declared_products": len(prod),
            "with_derived_requires": len(with_req & set(steps)),
            "blind": sorted(set(steps) - prod - with_req)}


def selftest() -> dict:
    rep = {"ts": datetime.now(timezone.utc).isoformat()}
    try:
        from hyperon import MeTTa
        rep["hyperon"] = {"ok": True, "smoke": str(MeTTa().run("!(+ 1 2)"))}
    except Exception as e:
        rep["hyperon"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    rep["coverage"] = coverage()
    since = datetime.now(timezone.utc).timestamp() - 86400
    rep["samples"] = {s: can_skip(s, since) for s in
                      ("web_intelligence", "goal_score_calculator", "deduction",
                       "merklememory_commit", "cycle_report")}
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rep


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print("hyperon:", r["hyperon"]["ok"], r["hyperon"].get("error", ""))
        c = r["coverage"]
        print(f"покритие: {c['with_declared_products']} с обявени изходи, "
              f"{c['with_derived_requires']} с изведени входове, "
              f"от {c['steps_in_table']} стъпки")
        print(f"слепи ({len(c['blind'])}): {', '.join(c['blind'][:12])}")
        for s, d in r["samples"].items():
            print(f"- {s}: {d['verdict']} — {d['why']}")
            for b in d["blockers"][:3]:
                print(f"    спира го: {b['consumer']} чака {b['file']} ({b['state']})")
    elif len(sys.argv) > 2 and sys.argv[1] == "can_skip":
        print(json.dumps(can_skip(sys.argv[2]), ensure_ascii=False, indent=2))
    else:
        print(__doc__)

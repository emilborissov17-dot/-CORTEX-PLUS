#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/step_audit.py — ВСЯКА СТЪПКА, ЕДНА ПО ЕДНА, МЕХАНИЧНО. (12 Sep 2026)

ЗАЩО СЪЩЕСТВУВА. До днес дефектите в цикъла се намираха по случайност: някой
пита нещо, отваряш един файл, и там стои буквата "c" като научен закон. Четири
такива за един ден:

  1. ОТРОВЕН ОТ ТЕСТ  — тест пише в живото състояние (memory/canon_invariants.json
     съдържаше урок "c" от фикстура с cycle_id "c1", и той влизаше във всяка подсказка).
  2. ВРАТА, КОЯТО НЕ МОЖЕ ДА СЕ ОТВОРИ — brain.promote_repeated_lesson иска дословно
     еднакъв текст от 8B модел в 3 поредни нощи. Завързано, но мъртво.
  3. ЧЕТЕ ГРЕШНИЯ СЛОЙ — core/consolidation.py чете само архивните signals.json
     (годишни, 46 от 48 постоянни), докато memory/daily_tier.jsonl държи 2346
     датирани наблюдения, които се движат.
  4. ПЕЧАТА И УМИРА — изход, който никой не чете.

Всеки от четирите има МЕХАНИЧЕН отпечатък. Този модул го търси за всичките 74
стъпки, вместо да чака някой да се спъне в него.

КАКВО ПРАВИ, ТОЧНО.
  1. Чете fast_cycle_runner.py и вади всяко beat("име", "индекс") — това е списъкът
     със стъпки, взет от самия бегач, а не преписан на ръка (преписан списък остарява
     тихо; изваден — не).
  2. За всяка стъпка намира модула, който върши работата. Повечето блокове са
     тънки обвивки от 3-30 реда; истинската работа е в модула.
  3. За всеки модул вади с AST декларираните изходни пътища (константи на ниво
     модул със стойност .json/.jsonl/.txt/.md/.npz).
  4. За всеки изход проверява: съществува ли; на колко часа е; и ЧЕТЕ ЛИ ГО НЯКОЙ —
     търси името му във всички .py/.ps1/.bat на хранилището, отделно в тестовете.

КАКВО НЕ ПРАВИ. Не съди дали стъпката е ПРАВА. „Врата, която не може да се отвори"
(дефект 2) не се хваща с граматика — праг върху свободен текст изглежда като всеки
друг праг. Затова изходът е КАНДИДАТИ за човешки преглед, подредени по тежест, а не
присъда. Колоните „цел / фаза / точка от 14-те / присъда" се попълват в
docs/STEP_LEDGER.md и се четат обратно тук, за да се вижда какво е прегледано и кога.

ФЛАГОВЕ.
  ORPHAN          изход, който никой освен собственика си не чете  -> „печата и умира"
  TEST_ONLY       изход, който само тестове четат                  -> живее заради тестовете
  WRITES_LIVE_STATE_FROM_TEST  тест пише в път извън tmp           -> случаят с канона
  STALE           изходът не е пипан от N дни, а стъпката върви всяка нощ
  MISSING         декларираният изход изобщо не съществува
  NO_MODULE       блокът върши всичко на място (по-трудно за тестване)
  UNREVIEWED      няма ред в docs/STEP_LEDGER.md

Usage:
  venv\\Scripts\\python.exe tools\\step_audit.py                 # таблица + JSON
  venv\\Scripts\\python.exe tools\\step_audit.py --flag ORPHAN   # само едно семейство
  venv\\Scripts\\python.exe tools\\step_audit.py --selftest
Пише claude/reports/step_audit_latest.json (и не пише нищо друго — одитът не поправя).
"""
from __future__ import annotations

import ast
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "fast_cycle_runner.py"
LEDGER = REPO / "docs" / "STEP_LEDGER.md"
OUT = REPO / "claude" / "reports" / "step_audit_latest.json"

DATA_EXT = (".json", ".jsonl", ".txt", ".md", ".npz", ".db")
STALE_HOURS = 48
SCAN_SUFFIX = (".py", ".ps1", ".bat")
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", "snapshots",
             "cortex_memory", "logs", "models"}
PKGS = ("core", "experiments", "agents", "tools", "memory")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 1. стъпките, извадени от бегача ──────────────────────────────────────────

def steps(runner: Path | None = None) -> list[dict]:
    """beat("name", "index") в реда, в който бегачът ги изпълнява."""
    src = (runner or RUNNER).read_text(encoding="utf-8", errors="ignore")
    lines = src.splitlines()
    rx = re.compile(r'^\s*beat\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
    marks = [(i, m.group(1), m.group(2))
             for i, l in enumerate(lines) if (m := rx.match(l))]
    out = []
    for j, (i, name, idx) in enumerate(marks):
        end = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
        out.append({"index": idx, "name": name, "line": i + 1,
                    "block_lines": end - i, "code": "\n".join(lines[i:end])})
    return out


# ── 2. кой модул върши работата ──────────────────────────────────────────────

_FROM = re.compile(r"from\s+(" + "|".join(PKGS) + r")(?:\.(\w+))?\s+import\s+([^\n#]+)")
_DOT = re.compile(r"\b(" + "|".join(PKGS) + r")\.(\w+)\b")


def modules_of(code: str) -> list[str]:
    """Модулите на хранилището, които блокът вика. Празно => работата е на място."""
    found: set[str] = set()
    for pkg, sub, names in _FROM.findall(code):
        if sub:
            found.add(f"{pkg}/{sub}.py")
        else:
            for n in re.split(r"[,\s]+", names):
                n = n.split(" as ")[0].strip().strip("()")
                if n and n.isidentifier():
                    found.add(f"{pkg}/{n}.py")
    for pkg, sub in _DOT.findall(code):
        found.add(f"{pkg}/{sub}.py")
    return sorted(p for p in found if (REPO / p).is_file())


# ── 3. какво декларира модулът, че пише ──────────────────────────────────────

_DECLARED: dict[str, list[str]] = {}


def declared_outputs(rel: str) -> list[str]:
    """Константи на ниво модул, чиято стойност съдържа път към данни.

    През AST, не с регулярен израз върху текста: докстринговете в това хранилище
    редовно СПОМЕНАВАТ пътища, които модулът не пипа ("както прави
    memory/daily_tier.jsonl"), а спомената пътека не е изход.
    """
    if rel in _DECLARED:
        return _DECLARED[rel]
    p = REPO / rel
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    def _in_order(node) -> list[str]:
        """Низовете в реда, в който стоят в израза.

        НЕ с ast.walk: той обхожда в ШИРИНА, така че REPO / "memory" / "x.json"
        връща ["x.json", "memory"] и последният елемент е директорията. Този бъг
        беше в първата версия на този файл и правеше declared_outputs() празен за
        всеки модул — тоест одитът щеше да рапортува „никой нищо не пише".
        """
        got = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            got.append(node.value)
        for child in ast.iter_child_nodes(node):
            got.extend(_in_order(child))
        return got

    out: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        parts = _in_order(node.value)
        # URL НЕ Е ИЗХОД. Първата версия обяви
        # https://sealevel.colorado.edu/...gmsl_2025rel1_seasons_rmvd.txt
        # за деклариран изход, който „липсва", и с това надуе MISSING до 24.
        # Адрес, който модулът ЧЕТЕ по мрежата, не е файл, който той пише.
        if any("://" in x for x in parts):
            continue
        tail = next((p for p in reversed(parts) if p.endswith(DATA_EXT)), None)
        if not tail:
            continue
        i = len(parts) - 1 - parts[::-1].index(tail)
        out.add(f"{parts[i - 1]}/{tail}" if i > 0 and "/" not in tail and
                "." not in parts[i - 1] else tail)
    _DECLARED[rel] = sorted(out)
    return _DECLARED[rel]


# ── 4. чете ли го някой ──────────────────────────────────────────────────────

def _repo_files() -> list[Path]:
    """Файловете за сканиране — с ОТРЯЗВАНЕ на обхождането, не с филтър след него.

    ТОВА БЕШЕ ДЕФЕКТЪТ, който направи одита неизползваем. Първата версия беше
    REPO.rglob("*") и после `if any(part in SKIP_DIRS ...)`. Но rglob ВЛИЗА във
    всяка директория, преди филтърът да я отхвърли — включително
    snapshots/self_archive, която по описанието в test/conftest.py е десетки
    гигабайта и стотици хиляди файла. На машината на Емил инструментът вървя
    631 s, после 150 s+ и още течеше; в моята пясъчна кутия — 0.5 s, защото там
    snapshots/ на практика я няма.

    Измерих поправката в среда, която няма проблема. Това е петият път днес, в
    който число от кутията ми не се пренася. os.walk с dirnames[:] премахва
    поддървото ПРЕДИ да се влезе в него, така че цената вече не зависи от това
    колко голям е архивът.
    """
    import os
    files = []
    for root, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base = Path(root)
        for name in filenames:
            if name.endswith(SCAN_SUFFIX):
                files.append(base / name)
    return files


_TEXT: dict[str, str] = {}


def repo_text(files: list[Path]) -> dict:
    """{относителен път: съдържание}, прочетено ВЕДНЪЖ за целия пробег.

    readers() отваряше наново всеки файл за ВСЯКО име на изход, и после пак за
    всеки модул в unscheduled_producers(). Стотици файлове по десетки изхода.
    """
    if not _TEXT:
        for f in files:
            try:
                _TEXT[str(f.relative_to(REPO)).replace("\\", "/")] = \
                    f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return _TEXT


def readers(basename: str, owner: str, files: list[Path]) -> dict:
    """Кой споменава този файл, освен модула, който го декларира.

    Търси се ИМЕТО НА ФАЙЛА, не целият път: един модул пише
    memory/x.json чрез константа, друг го чете като REPO/"memory"/"x.json",
    трети — през помощна функция. Името е общото между трите.
    """
    live, tests = [], []
    for rel, text in repo_text(files).items():
        if rel == owner or basename not in text:
            continue
        (tests if rel.startswith(("test/", "tests/")) or "conftest" in rel
         else live).append(rel)
    return {"live": sorted(live)[:6], "tests": sorted(tests)[:6],
            "n_live": len(live), "n_tests": len(tests)}


_TMP = re.compile(r"tmp_path|tmpdir|tmp_path_factory|mkdtemp|TemporaryDirectory")
_WRITE = re.compile(r'(write_text|write_bytes|open\s*\([^)]*["\'][wa])')
_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$")
_SETATTR = re.compile(r'setattr\(\s*([A-Za-z_][\w.]*)\s*,\s*["\'](\w+)["\']\s*,\s*(.+)$')
_TARGET = re.compile(r"^\(*\s*([A-Za-z_][\w.]*)")


def _safe_names(src: str) -> set[str]:
    """Имената в ЕДИН тестов файл, които сочат към временна директория.

    Три начина един тест да е чист, и трите трябва да се четат като чисти, иначе
    детекторът вика при всеки правилно написан тест и никой няма да го гледа:
      p = tmp_path / "x"                      -> p
      monkeypatch.setattr(mod, "FILE", tmp..) -> mod.FILE
      def t(tmp_path):                        -> tmp_path
    Разпространява се: q = p / "y" също е чисто, затова обхождаме до стабилност.
    """
    safe = {"tmp_path", "tmpdir", "tmp_path_factory"}
    lines = src.splitlines()
    for _ in range(4):                      # малко обхождания стигат; спира при стабилност
        before = len(safe)
        for line in lines:
            m = _SETATTR.search(line)
            if m and (_TMP.search(m.group(3)) or
                      any(re.search(rf"\b{re.escape(s)}\b", m.group(3)) for s in safe)):
                safe.add(f"{m.group(1)}.{m.group(2)}")
                safe.add(m.group(2))
            a = _ASSIGN.match(line)
            if a and (_TMP.search(a.group(2)) or
                      any(re.search(rf"\b{re.escape(s)}\b", a.group(2)) for s in safe)):
                safe.add(a.group(1))
        if len(safe) == before:
            break
    return safe


def test_writes_live_state(files: list[Path]) -> list[dict]:
    """Дефектът, който отрови канона: тест, който пише в пътя на хранилището.

    memory/canon_invariants.json държеше урок "c" с доказателство "(c1..c1)" —
    фикстура, влязла в живия канон, и оттам във всяка подсказка на мозъка.

    ПРЕЗ AST, НЕ ПРЕЗ ТЕКСТА. Първата версия търсеше "write_text" с регулярен израз
    и върна 212 попадения, от които почти всички бяха ПРОЗА: ред от коментар в
    conftest.py, който ОПИСВА проблема ("went through write_text, an append via
    open(), os.replace..."), и редът, с който самият пазач се реализира. Тоест
    моят инструмент наруши правилото на това хранилище — структурната проверка
    чете код, никога проза — докато проверяваше точно това правило. Числото 212
    беше по-лошо от липсващо: изглеждаше като измерване.

    Сега се търси ИЗВИКВАНЕ: .write_text(...) / .write_bytes(...) / open(..., "w")
    като ast.Call, и се пита върху КОГО е извикано. Коментар не е Call.

    Чисто е: tmp_path и всичко изведено от него, включително monkeypatch.setattr на
    константа на модул към временен път.
    """
    hits = []
    for f in files:
        rel = str(f.relative_to(REPO)).replace("\\", "/")
        if not (rel.startswith(("test/", "tests/")) or "conftest" in rel):
            continue
        try:
            tree = ast.parse(repo_text(files).get(rel, ""))
        except (OSError, SyntaxError):
            continue
        safe = _safe_names_ast(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = _write_target(node)
            if target is None:
                continue
            root = target.split(".")[0]
            if target in safe or root in safe:
                continue
            hits.append({"file": rel, "line": node.lineno, "target": target,
                         "code": f"{target}.write(...)"})
    return hits


def _root_name(node) -> str | None:
    """Най-левият идентификатор на израз: (m / "x").write_text -> m ; pt.FILE -> pt.FILE"""
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            inner = _root_name(node.value)
            return f"{inner}.{node.attr}" if inner else None
        if isinstance(node, ast.BinOp):
            node = node.left
            continue
        if isinstance(node, ast.Call):
            node = node.func
            continue
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        return None


def _write_target(call: ast.Call) -> str | None:
    """Кого пише това извикване, ако пише. None = не е запис."""
    fn = call.func
    if isinstance(fn, ast.Attribute) and fn.attr in ("write_text", "write_bytes", "mkdir"):
        return _root_name(fn.value)
    if isinstance(fn, ast.Name) and fn.id == "open" and len(call.args) >= 2:
        mode = call.args[1]
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                and mode.value[:1] in ("w", "a"):
            return _root_name(call.args[0])
    if isinstance(fn, ast.Attribute) and fn.attr == "open":
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant) \
                    and str(kw.value.value)[:1] in ("w", "a"):
                return _root_name(fn.value)
        if call.args and isinstance(call.args[0], ast.Constant) \
                and str(call.args[0].value)[:1] in ("w", "a"):
            return _root_name(fn.value)
    return None


def _safe_names_ast(tree) -> set[str]:
    """Имената в един тестов файл, сочещи към временна директория — от AST.

    Три чисти форми, и трите трябва да четат като чисти, иначе детекторът вика при
    всеки правилно написан тест:
        p = tmp_path / "x"                       -> p
        monkeypatch.setattr(mod, "FILE", tmp..)  -> mod.FILE и FILE
        def t(tmp_path):                         -> tmp_path
    Разпространява се до стабилност: q = p / "y" също е чисто.
    """
    safe = {"tmp_path", "tmpdir", "tmp_path_factory"}
    for _ in range(4):
        before = len(safe)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = {_root_name(t) for t in node.targets} - {None}
                if _mentions(node.value, safe):
                    safe |= names
            elif isinstance(node, ast.Call):
                fn = node.func
                is_setattr = (isinstance(fn, ast.Name) and fn.id == "setattr") or \
                             (isinstance(fn, ast.Attribute) and fn.attr == "setattr")
                if is_setattr and len(node.args) >= 3 and _mentions(node.args[2], safe):
                    mod = _root_name(node.args[0])
                    attr = node.args[1]
                    if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
                        safe.add(attr.value)
                        if mod:
                            safe.add(f"{mod}.{attr.value}")
        if len(safe) == before:
            break
    return safe


def _mentions(node, safe: set) -> bool:
    """Стъпва ли този израз върху нещо временно."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in safe:
            return True
        if isinstance(n, ast.Attribute) and n.attr in safe:
            return True
        if isinstance(n, ast.Call):
            fn = n.func
            nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if nm in ("mkdtemp", "TemporaryDirectory", "mktemp"):
                return True
    return False


# ── 4b. производители, които никой не пуска ──────────────────────────────────

def unscheduled_producers(files: list[Path]) -> list[dict]:
    """Модул, чийто ИЗХОД се чете всяка нощ, а самият той не се вика от нищо.

    Намерено на 12 Sep 2026 и това е причината проверката да съществува:
    core/consolidation.py пише memory/consolidation_queue.json; стъпка 20.06
    (core/hypothesis_intake.py) го чете ВСЯКА нощ. Но в целия fast_cycle_runner.py
    думата "consolidation" не се среща — производителят не е в цикъла. Всяка нощ
    системата приема като „тазвечерни хипотези" опашка, писана на ръка.

    Огледалният случай на ORPHAN: там изход без четец, тук четец без график.
    И двата минават всеки тест — нито един тест не пита „а кой го вика".
    """
    cache = repo_text(files)
    src = {rel: t for rel, t in cache.items()
           if rel.startswith("core/") and rel.endswith(".py")}
    entry = "\n".join([cache.get("fast_cycle_runner.py", "")] + [
        t for rel, t in cache.items()
        if rel.endswith((".ps1", ".bat")) or "scheduler" in rel or "supervisor" in rel])

    # ДОСТИЖИМОСТ, А НЕ САМО ПРЯКО ВИКАНЕ. core/usgs_quakes.py не се среща в бегача,
    # но core/daily_tier.py (стъпка 2.52) го ВНАСЯ — значи се изпълнява всяка нощ.
    # Без това затваряне проверката вика при всеки помощен модул и става безполезна.
    #
    # ПО ВНОС, НЕ ПО СПОМЕНАВАНЕ. Първата версия търсеше името на модула като дума
    # в текста и обяви core/consolidation.py за достижим, защото
    # core/hypothesis_intake.py има константа CONSOLIDATION_QUEUE и докстринг, който
    # го описва. Да опишеш нещо не значи да го изпълниш — точно обратното на това,
    # което проверката търси.
    def _imports(text: str, launcher: bool = False) -> set[str]:
        got = set()
        for m in re.finditer(r"^\s*(?:from\s+core(?:\.(\w+))?\s+import\s+([^\n#]+)"
                             r"|import\s+core\.(\w+))", text, re.M):
            if m.group(1):
                got.add(m.group(1))
            if m.group(3):
                got.add(m.group(3))
            if m.group(2):
                for n in re.split(r"[,\s]+", m.group(2)):
                    n = n.split(" as ")[0].strip().strip("()")
                    if n.isidentifier():
                        got.add(n)
        # Динамичните форми. Стъпка 2.52 вика __import__("core.daily_tier", ...),
        # а други стъпки подават "core/x.py" на подпроцес. И двете ИЗПЪЛНЯВАТ модула;
        # ако не се броят, одитът обявява живи стъпки за неизпълнявани — по-лошо от
        # мълчание, защото праща човек да поправя нещо, което работи.
        got |= set(re.findall(r'(?:__import__|import_module)\(\s*["\']core\.(\w+)', text))
        if launcher:
            # Само за бегача и планировчиците: "core/x.py", подадено на подпроцес,
            # ИЗПЪЛНЯВА модула. В тялото на друг модул същият низ обикновено е
            # произход в запис ({"origin": "core/consolidation.py"}) — описание,
            # не изпълнение. Без това разграничение core/consolidation.py минаваше
            # за пуснат, защото core/hypothesis_intake.py записва името му в реда.
            got |= set(re.findall(r'["\']core[/\\](\w+)\.py["\']', text))
        return got

    reach, frontier = set(), [(entry, True)]
    while frontier:
        text, launcher = frontier.pop()
        for stem in _imports(text, launcher):
            rel = f"core/{stem}.py"
            if rel in src and rel not in reach:
                reach.add(rel)
                frontier.append((src[rel], False))
    out = []
    for f in sorted((REPO / "core").glob("*.py")):
        stem = f.stem
        if stem.startswith("_"):
            continue
        rel = f"core/{stem}.py"
        declared = declared_outputs(rel)
        if not declared:
            continue
        read_by_live = [d for d in declared
                        if readers(Path(d).name, rel, files)["n_live"] > 0]
        if not read_by_live:
            continue
        if rel not in reach:
            out.append({"module": rel, "outputs_read_by_others": read_by_live})
    return out


# ── 5. прегледано ли е ───────────────────────────────────────────────────────

def reviewed(ledger: Path | None = None) -> dict:
    """Индексите, за които в docs/STEP_LEDGER.md има ред с дата.

    Формат на реда:  | 12.65 | deduction | <цел> | <фаза> | <точки> | <присъда> | 2026-09-12 |
    """
    p = ledger or LEDGER
    if not p.is_file():
        return {}
    seen = {}
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 8:
            continue
        idx, date = cells[1], cells[7]
        if re.fullmatch(r"[\d.]+", idx) and re.fullmatch(r"\d{4}-\d\d-\d\d", date):
            seen[idx] = {"verdict": cells[6][:120], "date": date,
                         "points": cells[5][:40], "phase": cells[4][:30]}
    return seen


# ── the run ──────────────────────────────────────────────────────────────────

def audit() -> dict:
    files = _repo_files()
    seen = reviewed()
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for st in steps():
        mods = modules_of(st["code"])
        outs = []
        for m in mods:
            for rel in declared_outputs(m):
                f = REPO / rel
                # Относителен път, който не съществува под корена, но съществува
                # под snapshots/, е изход на друг слой, а не липсващ файл: така
                # master/global_indicators_latest.json влизаше в MISSING.
                if not f.is_file():
                    alt = next((c for c in (REPO / "snapshots" / rel,
                                            REPO / "cortex_memory" / rel)
                                if c.is_file()), None)
                    if alt is not None:
                        f, rel = alt, str(alt.relative_to(REPO)).replace("\\", "/")
                base = Path(rel).name
                r = readers(base, m, files)
                age = None if not f.is_file() else round((now - f.stat().st_mtime) / 3600, 1)
                flags = []
                if not f.is_file():
                    flags.append("MISSING")
                else:
                    if age is not None and age > STALE_HOURS:
                        flags.append("STALE")
                    if r["n_live"] == 0 and r["n_tests"] == 0:
                        flags.append("ORPHAN")
                    elif r["n_live"] == 0:
                        flags.append("TEST_ONLY")
                outs.append({"path": rel, "owner": m, "age_hours": age,
                             "readers": r, "flags": flags})
        flags = sorted({f for o in outs for f in o["flags"]})
        if not mods:
            flags.append("NO_MODULE")
        if st["index"] not in seen:
            flags.append("UNREVIEWED")
        rows.append({"index": st["index"], "name": st["name"], "line": st["line"],
                     "block_lines": st["block_lines"], "modules": mods,
                     "outputs": outs, "flags": sorted(set(flags)),
                     "review": seen.get(st["index"])})

    leaks = test_writes_live_state(files)
    rec = {"ts": _now(), "steps": len(rows), "reviewed": len(seen),
           "unscheduled_producers": unscheduled_producers(files),
           "unreviewed": sum(1 for r in rows if "UNREVIEWED" in r["flags"]),
           "orphans": sum(1 for r in rows if "ORPHAN" in r["flags"]),
           "stale": sum(1 for r in rows if "STALE" in r["flags"]),
           "no_module": sum(1 for r in rows if "NO_MODULE" in r["flags"]),
           "test_writes_live_state": leaks, "rows": rows}
    return rec


def table(rec: dict, only: str | None = None) -> str:
    out = []
    for r in rec["rows"]:
        if only and only not in r["flags"]:
            continue
        f = ",".join(x for x in r["flags"] if x != "UNREVIEWED") or "-"
        seen = "✓" + r["review"]["date"][5:] if r["review"] else "—"
        out.append(f'{r["index"]:>7s} {r["name"]:<28s} {len(r["modules"]):>2d}mod '
                   f'{len(r["outputs"]):>2d}out  {seen:<8s} {f}')
    return "\n".join(out)


def _selftest() -> int:
    print("tools/step_audit --selftest")
    st = steps()
    print(f"  steps parsed from the runner : {len(st)}")
    assert st, "no beat() calls found — the runner shape changed, this tool is blind"
    idx = [s["index"] for s in st]
    assert len(idx) == len(set(idx)), f"duplicate step index: {sorted(idx)}"
    print(f"  first / last                 : {idx[0]} .. {idx[-1]}")
    thin = sum(1 for s in st if s["block_lines"] <= 30)
    print(f"  thin wrappers (<=30 lines)   : {thin}/{len(st)} — the work is in the modules")
    print(f"  ledger                       : "
          f"{'LIVE ' + str(len(reviewed())) + ' rows' if LEDGER.is_file() else 'ABSENT (every step UNREVIEWED)'}")
    return 0


# ── 6. паспорт на стъпката ───────────────────────────────────────────────────
#
# Механичен ред за всяка стъпка. НИКАКВА ПРЕЦЕНКА: паспортът описва, не съди.
# Присъдата, изречението какво прави стъпката и кои от 14-те точки обслужва
# стоят в docs/STEP_LEDGER.md и се пишат на ръка, с дата. Тук ледгерът се чете
# само ОБРАТНО — за да се отбележи кой ред още го няма.
#
# ПРАЗНОТО НЕ Е НУЛА. Колона, която не може да се сметне, връща UNKNOWN и
# причината. Нула чете като „няма нито едно"; тире чете като „не знам", и
# разликата е цялата стойност на този файл.
#
# КОЕ Е КОД И КОЕ Е СЪСТОЯНИЕ. Фаза, модули, таван, декларирани изходи, деца,
# вътрешни предели и повикване на модел се четат от кода и конфигурацията: два
# пуска над непроменено хранилище съвпадат. История, скорошни времена, убийства
# и „пипнато" четат ЗАПИСА — базата, логовете на циклите, дневника на часовоя —
# и се менят всяка нощ. Всеки ред носи state_derived със списъка им, за да не се
# чете като свойство на кода нещо, което е свойство на седмицата.

UNKNOWN = "—"

PASSPORT_MD = REPO / "claude" / "reports" / "STEP_PASSPORT.md"
PASSPORT_JSON = REPO / "claude" / "reports" / "STEP_PASSPORT.json"
BASELINE_FILE = REPO / "memory" / "step_contract_baseline.json"
SUPERVISOR_LOG = REPO / "logs" / "supervisor.log"
CYCLE_LOG_DIR = REPO / "memory" / "cycle_logs"
EXISTENCE_LEDGER = REPO / "memory" / "existence_ledger.jsonl"
PHASES_FILE = REPO / "config" / "cycle_phases.json"

STATE_COLUMNS = ["history", "recent_times", "kills", "outputs.touched_only"]

_SPAWN_CALLS = {"subprocess.run", "subprocess.Popen", "subprocess.call",
                "subprocess.check_call", "subprocess.check_output",
                "os.system", "os.popen", "os.spawnl", "os.spawnv",
                "Popen", "__import__"}
_SCRIPT_EXT = (".bat", ".ps1", ".cmd", ".exe")

# Имена, чието ПОВИКВАНЕ или ВНАСЯНЕ значи модел. Търсят се идентификатори през
# AST, не подниз в текста: докстринговете тук споменават ollama и groq, докато
# обещават да НЕ ги викат, и подниз не отличава обещание от повикване.
_MODEL_CALLS = {"think", "_llm", "call_groq", "call_groq_meta", "ask_groq",
                "ask_model", "chat", "generate"}
_MODEL_MODULES = {"groq_backend", "ollama_backend", "brain", "model_window",
                  "backend_policy", "cortex_reasoner", "ollama", "openai",
                  "groq", "anthropic"}

_CAP_NAME = re.compile(r"^(MAX|MIN)_|_(MAX|LIMIT|CAP|QUOTA)$|_PER_")
_TIME_NAME = re.compile(r"_(SEC|SECS|SECONDS|TIMEOUT|DEADLINE|BUDGET|MINUTES)$"
                        r"|^(TIMEOUT|DEADLINE|BUDGET)")
_RETRY_NAME = re.compile(r"retry|retries|attempt|attempts|backoff", re.I)
_RUN_LABEL = re.compile(r'_run\(\s*"([^"]+)"')
_SEC_IN_LINE = re.compile(r"\((\d+(?:\.\d+)?)s\)")
_KILL_LINE = re.compile(
    r"KILL POLICY: step='([^']+)' age=(\d+(?:\.\d+)?)s ceiling=(\d+(?:\.\d+)?)s "
    r"cpu=(\S+) io_idle=(\S+) degraded=(\S+) -> ([A-Z]+) \(([^)]*)\)")


def _ast_of(text: str):
    """AST или None. Никога не хвърля: един неразбираем файл не бива да отнеме
    паспорта на другите 73 стъпки."""
    try:
        return ast.parse(text)
    except Exception:
        return None


def _dotted(node) -> str:
    """Точковото име на извикваното, колкото се чете статично."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _trees_for(code: str, modules: list) -> list:
    """Дървото на блока плюс дърветата на модулите, които той вика."""
    out = []
    t = _ast_of(code)
    if t is not None:
        out.append(("block", t))
    for m in modules:
        try:
            src = (REPO / m).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        t = _ast_of(src)
        if t is not None:
            out.append((m, t))
    return out


def _phase_of(name: str, index: str) -> dict:
    """Фазата по (име, индекс) от config/cycle_phases.json.

    По ДВОЙКАТА, не по името: body_scan върви два пъти, в две различни фази, и
    карта по име не може да представи това — файлът сам го казва в ключа
    _identity_is_the_index_not_the_name.
    """
    try:
        blob = json.loads(PHASES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"value": UNKNOWN,
                "why": f"{PHASES_FILE.name} unreadable ({type(e).__name__})"}
    for phase, body in (blob.get("phases") or {}).items():
        for s in body.get("steps") or []:
            if s.get("name") == name and str(s.get("index")) == str(index):
                return {"value": phase, "why": None}
    return {"value": UNKNOWN,
            "why": f"({name}, {index}) is in the runner but not in {PHASES_FILE.name}"}


def _canonical(name: str) -> str:
    """Каноничното име — псевдонимите и подстъпките се разрешават през
    core.cycle_map, не през втора таблица тук."""
    try:
        from core.cycle_map import _canon
        return _canon(name) or name
    except Exception:
        return name


def _ceiling_of(step: str) -> dict:
    """core.step_budget.effective_ceiling — единственият източник, делегиран.

    config/scheduler.json сам забранява втора таблица с времена, затова тук няма
    резервен прочит на конфигурацията. Ако функцията не се зареди, редът казва
    UNKNOWN, вместо да отговори с второ мнение.
    """
    try:
        from core.step_budget import effective_ceiling
        return {"value": int(effective_ceiling(step)), "why": None}
    except Exception as e:
        return {"value": UNKNOWN,
                "why": f"core.step_budget.effective_ceiling unavailable "
                       f"({type(e).__name__}: {e})"}


def _contract_labels(code: str) -> list:
    """Етикетите на _run() в блока — точно тези, за които се пише договор.

    StepContract се отваря в fast_cycle_runner._run(). beat() пише пулс, не
    договор. Блок без нито един _run() никога не получава ред в базата — не
    защото стъпката е млада, а защото никой не пише за нея.
    """
    return sorted(set(_RUN_LABEL.findall(code)))


def _load_baseline() -> dict:
    try:
        return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _warmup_cycles() -> int:
    try:
        from core.step_contract import WARMUP_CYCLES
        return int(WARMUP_CYCLES)
    except Exception:
        return 3


def _p95(values: list):
    """Правилото на хранилището, взето назаем, не преписано."""
    try:
        from core.step_contract import p95 as _repo_p95
        return _repo_p95(list(values))
    except Exception:
        vals = sorted(values)
        if len(vals) < 2:
            return None
        return float(vals[max(0, min(len(vals) - 1,
                                     int(round(0.95 * (len(vals) - 1)))))])


def _history(name: str, labels: list, baseline: dict) -> dict:
    """Редовете в step_contract_baseline.json за тази стъпка — и ако няма, защо."""
    writer = ("core/step_contract.py, opened by fast_cycle_runner._run(); "
              "beat() writes a heartbeat, not a contract")
    keys = []
    for k in list(labels) + [name, _canonical(name)]:
        if k in baseline and k not in keys:
            keys.append(k)
    if not keys:
        why = ((f"no _run() call inside the block, so no StepContract is ever "
                f"opened for it — nobody writes rows. Writer: {writer}")
               if not labels else
               (f"the block calls _run({', '.join(labels)}) but no such key exists "
                f"in {BASELINE_FILE.name}. Writer: {writer}"))
        return {"has_history": False, "n": UNKNOWN, "median": UNKNOWN,
                "p95": UNKNOWN, "keys": labels, "touched": [], "why": why}
    secs, touched = [], set()
    for k in keys:
        for r in (baseline[k].get("runs") or []):
            if isinstance(r.get("seconds"), (int, float)):
                secs.append(float(r["seconds"]))
            for t in (r.get("touched") or []):
                touched.add(str(t).replace("\\", "/"))
    if not secs:
        return {"has_history": False, "n": 0, "median": UNKNOWN, "p95": UNKNOWN,
                "keys": keys, "touched": sorted(touched),
                "why": f"key(s) {keys} exist in {BASELINE_FILE.name} with no runs"}
    warm = _warmup_cycles()
    q = _p95(secs)
    return {"has_history": True, "n": len(secs),
            "median": round(statistics.median(secs), 1),
            "p95": (round(q, 1) if q is not None else UNKNOWN),
            "keys": keys, "touched": sorted(touched),
            "why": (None if len(secs) >= warm else
                    f"{len(secs)} of {warm} WARMUP_CYCLES — the contract's verdict "
                    f"stays UNKNOWN until the third run")}


def _recent_times(name: str, cycle_logs: list) -> dict:
    """Секунди, отпечатани ВЪТРЕ в блока на стъпката, в последните 10 цикъла.

    За стъпка без база това е единственото механично време, което съществува:
    редовете в memory/cycle_logs нямат собствен часовник, така че разлика между
    два реда не може да се вземе. Чете се само число, което самата стъпка е
    отпечатала в скоби, и се пази РЕДЪТ, за да може да се провери.
    """
    found = []
    for path, text in cycle_logs:
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines)
                      if l.startswith("[STEP] ") and l[7:].strip() == name), None)
        if start is None:
            continue
        end = next((j for j in range(start + 1, len(lines))
                    if lines[j].startswith("[STEP] ")), len(lines))
        best, best_line = None, None
        for l in lines[start:end]:
            for m in _SEC_IN_LINE.finditer(l):
                v = float(m.group(1))
                if best is None or v > best:
                    best, best_line = v, l.strip()[:120]
        if best is not None:
            found.append({"log": path.name, "seconds": best, "line": best_line})
    if not found:
        return {"value": UNKNOWN, "runs": [],
                "why": "the block prints no '(Ns)' of its own, and cycle-log lines "
                       "carry no timestamps, so no duration can be derived"}
    return {"value": round(statistics.median(f["seconds"] for f in found), 1),
            "runs": found, "why": None}


def _kill_index() -> dict:
    """Убийствата. АВТОРИТЕТЪТ Е ДНЕВНИКЪТ, не текстовият лог.

    memory/existence_ledger.jsonl носи CYCLE_KILLED с reason.wedged_step и е
    веригата, която само истински цикъл пише — 13 записа, daily_analysis 6,
    internet_intelligence 6, constancy_and_constellation 1. Това е колона 6.

    logs/supervisor.log остава ВТОРОСТЕПЕННО потвърждение и нищо повече, защото
    е ОТРОВЕН: измерено, 720+ от редовете KILL POLICY са синтетични — 144 за
    web_intelligence, 144 за trend_tracker и 432 за step='x', което дори не е
    стъпка. Всеки може да пише в текстов файл, и тестовете пишат.

    Затова тук се брои и колко РАЗЛИЧНИ наблюдения стоят зад редовете: фикстура
    се разпознава по това, че се повтаря дословно, така че 144 реда с едно
    различно наблюдение са едно наблюдение, повторено 144 пъти. Числото се
    показва; преценка не се прави.
    """
    by_step, text = {}, ""
    try:
        text = SUPERVISOR_LOG.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    for m in _KILL_LINE.finditer(text):
        step, age, ceil, cpu, io, degraded, verdict, cause = m.groups()
        d = by_step.setdefault(step, {"lines": 0, "by_rule": {},
                                      "_distinct": set(), "ages": set()})
        d["lines"] += 1
        rule = f"{verdict}({cause})"
        d["by_rule"][rule] = d["by_rule"].get(rule, 0) + 1
        d["_distinct"].add((age, ceil, cpu, io, degraded, verdict, cause))
        d["ages"].add(float(age))
    for d in by_step.values():
        d["distinct_observations"] = len(d.pop("_distinct"))
        d["ages"] = sorted(d["ages"])

    ledger = {}
    try:
        for line in EXISTENCE_LEDGER.read_text(encoding="utf-8",
                                               errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "CYCLE_KILLED":
                continue
            reason = rec.get("reason") or {}
            e = ledger.setdefault(str(reason.get("wedged_step")),
                                  {"count": 0, "ages": []})
            e["count"] += 1
            if isinstance(reason.get("heartbeat_age_sec"), (int, float)):
                e["ages"].append(round(float(reason["heartbeat_age_sec"]), 1))
    except Exception:
        pass
    ledger_read = EXISTENCE_LEDGER.is_file()
    return {"log": by_step, "ledger": ledger, "log_available": bool(text),
            "ledger_available": ledger_read}


def _kills_for(name: str, index: dict) -> dict:
    """Колона 6. Първо дневникът; логът само отдолу, с бележката какъв е."""
    led = index["ledger"].get(name) or {}
    if not index["ledger_available"]:
        row = {"kills": UNKNOWN, "ages_sec": [],
               "why": f"{EXISTENCE_LEDGER.name} unreadable — the authoritative "
                      f"record of a kill could not be read, so this is NOT zero"}
    else:
        row = {"kills": led.get("count", 0),
               "ages_sec": led.get("ages", []),
               "source": f"{EXISTENCE_LEDGER.name} CYCLE_KILLED.reason.wedged_step",
               "why": None}
    log = index["log"].get(name) or {}
    row["corroboration"] = (
        {"log_lines": UNKNOWN,
         "note": f"{SUPERVISOR_LOG.name} unreadable or absent"}
        if not index["log_available"] else
        {"log_lines": log.get("lines", 0),
         "log_by_rule": log.get("by_rule", {}),
         "log_distinct_observations": log.get("distinct_observations", 0),
         "log_ages_sec": log.get("ages", []),
         "note": "SECONDARY ONLY. logs/supervisor.log is plain text that tests "
                 "write to as well as the watchdog; 720+ of its KILL POLICY lines "
                 "are known fixtures (step='x' is not a step). distinct_observations "
                 "counts how many of these lines carry a different "
                 "(age, ceiling, cpu, io, degraded, verdict) tuple — a fixture "
                 "repeats verbatim, so 144 lines / 1 distinct is one observation."})
    return row


BLACKBOX = REPO / "memory" / "blackbox.jsonl"
_TERMINAL = {"CYCLE_FINISHED", "CYCLE_DIED", "CYCLE_KILLED",
             "CYCLE_REFUSED_SURVIVAL_GATE"}


def _cycle_context() -> dict:
    """Колона 14. Паметта, която ЦИКЪЛЪТ е имал — не стъпката.

    ЗАЩО Е В ПАСПОРТА НА СТЪПКАТА, ЕДНАКВА ЗА ВСИЧКИ РЕДОВЕ. Без нея „умря в
    composers" се чете като вина на composers. Цикълът от 12 сеп 20:04 тръгна с
    2063 MB свободни, при измерен апетит 1.9 GB типично и 2.7 GB в най-лошата от
    осем нощи — тоест нощта беше обречена, преди composers да съществува в нея.
    Стойността е свойство на вечерта, не на стъпката, и затова стои еднаква във
    всеки ред: това е контекстът, срещу който се чете всяко друго число.

    Сдвоява се по pid ВЪТРЕ в blackbox.jsonl, а изходът се взима от дневника по
    ВРЕМЕ: дневникът записва pid-а на venv launcher-а, blackbox — на истинския
    интерпретатор, и по pid двата файла не се съединяват.

    Убит цикъл не пише exit ред (coverage/blackbox пишат при излизане), така че
    „exit: —" НЕ е нула похарчена памет, а липсващо измерване — и е самият
    подпис на смъртта.
    """
    def _load(p):
        out = []
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        except OSError:
            pass
        return out

    def _t(s):
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))

    bb = [r for r in _load(BLACKBOX) if r.get("step") == "cycle"]
    if not bb:
        return {"value": UNKNOWN, "cycles": [],
                "why": f"{BLACKBOX.name} has no step=='cycle' rows — "
                       f"core/blackbox.py never wrote one"}
    led = _load(EXISTENCE_LEDGER)
    starts = [(_t(r["ts"]), r.get("cycle_id")) for r in led
              if r.get("event") == "CYCLE_STARTED" and r.get("ts")]
    term = {r["cycle_id"]: r["event"] for r in led
            if r.get("event") in _TERMINAL and r.get("cycle_id")}

    opened, pairs = {}, []
    for r in bb:
        if r.get("phase") == "start":
            opened[r.get("pid")] = r
        elif r.get("phase") == "exit" and r.get("pid") in opened:
            pairs.append((opened.pop(r["pid"]), r))
    for s in opened.values():
        pairs.append((s, None))
    pairs.sort(key=lambda p: _t(p[0]["utc"]))

    def _cid(row):
        best = None
        t = _t(row["utc"])
        for st, cid in starts:
            d = abs((st - t).total_seconds())
            if d <= 180 and (best is None or d < best[0]):
                best = (d, cid)
        return best[1] if best else None

    def _row(s, e):
        cid = _cid(s)
        return {
            "cycle_id": cid or f"(unmatched) {s['utc']}",
            "start_avail_mb": s.get("avail_mb"),
            "exit_avail_mb": (e.get("avail_mb") if e else UNKNOWN),
            "consumed_mb": (round(s["avail_mb"] - e["avail_mb"])
                            if e and s.get("avail_mb") is not None else UNKNOWN),
            "outcome": term.get(cid) or ("no exit row — killed, or still running"
                                         if e is None else "no ledger verdict"),
        }

    out = [_row(s, e) for s, e in pairs[-10:]]
    # ПРОЗОРЕЦЪТ НА АПЕТИТА Е ПО-ШИРОК ОТ ТАБЛИЦАТА, НАРОЧНО. Таблицата показва
    # последните десет пуска, защото това е контекстът на тазвечершната стъпка.
    # Апетитът обаче се брои по ВСИЧКИ завършили цикли във файла: една вечер с
    # четири прекъснати опита изтласква завършилите нощи от прозореца и оставя
    # n=2 — извадка, която казва повече за днешния ден, отколкото за цикъла.
    everything = [_row(s, e) for s, e in pairs]
    finished = [c for c in everything if c["outcome"] == "CYCLE_FINISHED"]
    used = [c["consumed_mb"] for c in finished if isinstance(c["consumed_mb"], int)]
    shown_finished = sum(1 for c in out if c["outcome"] == "CYCLE_FINISHED")
    return {
        "value": (f"{round(statistics.median(c['start_avail_mb'] for c in out))}MB "
                  f"median at start, {shown_finished}/{len(out)} finished"),
        "cycles": out,
        "finished_in_window": shown_finished,
        "appetite_window": "every paired cycle in the file, not only the last 10",
        "appetite_mb": {"n": len(used),
                        "median": (round(statistics.median(used)) if used else UNKNOWN),
                        "max": (max(used) if used else UNKNOWN),
                        "why": (None if used else
                                "no finished cycle in the window wrote both rows")},
        "why": None,
    }


def _declared_vs_touched(modules: list, touched: list, has_history: bool) -> dict:
    """Декларирано (константи на ниво модул) срещу пипнато (от историята)."""
    declared = set()
    for m in modules:
        for rel in declared_outputs(m):
            declared.add(rel.replace("\\", "/"))
    t = {x.replace("\\", "/") for x in touched}
    if not modules:
        return {"declared_only": [], "touched_only": [], "both": [],
                "why": "the block names no module, so there are no constants to "
                       "read a declaration from"}
    if not has_history:
        return {"declared_only": sorted(declared), "touched_only": [], "both": [],
                "why": "no history, so nothing is known to have been touched — "
                       "declared_only here is NOT evidence of a dead output"}
    return {"declared_only": sorted(declared - t),
            "touched_only": sorted(t - declared),
            "both": sorted(declared & t), "why": None}


def _spawns(code: str, modules: list) -> dict:
    """subprocess / Popen / os.system / __import__, и низове с .bat/.ps1/.cmd/.exe.

    Повикванията се четат от AST, разширенията — от низови КОНСТАНТИ. Така
    коментар, който споменава tools/install_media_deps.ps1, не се брои за
    раждане на процес.
    """
    hits = []
    for where, tree in _trees_for(code, modules):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                n = _dotted(node.func)
                if n in _SPAWN_CALLS:
                    hits.append({"where": where, "what": n,
                                 "line": getattr(node, "lineno", None)})
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.lower().endswith(_SCRIPT_EXT):
                    hits.append({"where": where, "what": node.value[-40:],
                                 "line": getattr(node, "lineno", None)})
    return {"spawns": bool(hits), "n": len(hits), "hits": hits[:12]}


def _internal_limits(code: str, modules: list) -> dict:
    """Какво ограничава стъпката ОТВЪТРЕ, независимо от тавана на часовоя."""
    timeouts, caps, times, retries, sleeps = [], {}, {}, set(), set()
    for where, tree in _trees_for(code, modules):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = _dotted(node.func)
                for kw in (node.keywords or []):
                    if kw.arg == "timeout":
                        v = (kw.value.value if isinstance(kw.value, ast.Constant)
                             else (_dotted(kw.value) or "<expr>"))
                        timeouts.append({"where": where, "call": called,
                                         "timeout": v,
                                         "line": getattr(node, "lineno", None)})
                if called == "time.sleep" and node.args:
                    a = node.args[0]
                    sleeps.add(str(a.value) if isinstance(a, ast.Constant)
                               else (_dotted(a) or "<expr>"))
            elif isinstance(node, ast.Name) and _RETRY_NAME.search(node.id):
                retries.add(node.id)
        for node in getattr(tree, "body", []):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            names = [t.id for t in getattr(node, "targets", [])
                     if isinstance(t, ast.Name)]
            if isinstance(getattr(node, "target", None), ast.Name):
                names.append(node.target.id)
            lit = node.value.value if isinstance(node.value, ast.Constant) else None
            for nm in names:
                if _TIME_NAME.search(nm) and isinstance(lit, (int, float)) \
                        and not isinstance(lit, bool):
                    times[f"{where}:{nm}"] = lit
                elif _CAP_NAME.search(nm) and isinstance(lit, int) \
                        and not isinstance(lit, bool):
                    caps[f"{where}:{nm}"] = lit
    subprocess_deadline = [t for t in timeouts
                           if t["call"].startswith(("subprocess.", "Popen"))
                           and t["timeout"] not in (None, "None")]
    return {
        "request_timeouts": {"n": len(timeouts), "sample": timeouts[:6]},
        "count_caps": caps or UNKNOWN,
        "count_caps_why": (None if caps else
                           "no module-level int constant named MAX_*/*_LIMIT/"
                           "*_CAP/*_QUOTA/*_PER_*; a cap inside a function body is "
                           "invisible to a constant scan"),
        "internal_time_cap": bool(times or subprocess_deadline),
        "internal_time_constants": times or UNKNOWN,
        "subprocess_deadlines": subprocess_deadline[:4],
        "retry_identifiers": sorted(retries)[:8] or UNKNOWN,
        "sleep_values": sorted(sleeps)[:8] or UNKNOWN,
    }


def _model_calls(code: str, modules: list) -> dict:
    """Вика ли модел, и с кои ключови думи.

    През идентификатори — извикано име, внесен модул — не през текст. Иначе този
    файл би обявил за викащ модел всеки модул, чийто докстринг ОБЕЩАВА, че не
    вика, което е точно обратното на истината.
    """
    calls, mods, kwargs = set(), set(), {}
    for _where, tree in _trees_for(code, modules):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                dotted = _dotted(node.func)
                if not dotted:
                    continue
                tail = dotted.split(".")[-1]
                head = dotted.split(".")[0]
                if tail in _MODEL_CALLS or head in _MODEL_MODULES:
                    calls.add(dotted)
                    for kw in (node.keywords or []):
                        if kw.arg in ("fast", "lean") and \
                                isinstance(kw.value, ast.Constant):
                            key = f"{kw.arg}={kw.value.value}"
                            kwargs[key] = kwargs.get(key, 0) + 1
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[-1] in _MODEL_MODULES:
                        mods.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[-1] in _MODEL_MODULES:
                    mods.add(node.module)
    return {"calls_model": bool(calls or mods), "calls": sorted(calls)[:8],
            "modules": sorted(mods)[:8], "kwargs": kwargs or UNKNOWN}


def passport(rec: dict) -> dict:
    """Един механичен ред за всяка стъпка, от вече изчисления одит."""
    baseline = _load_baseline()
    kill_index = _kill_index()
    ctx = _cycle_context()
    logs = []
    try:
        for p in sorted(CYCLE_LOG_DIR.glob("cycle_*.log"),
                        key=lambda f: f.stat().st_mtime)[-10:]:
            logs.append((p, p.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        logs = []
    src = RUNNER.read_text(encoding="utf-8", errors="ignore").splitlines()

    rows = []
    for r in rec["rows"]:
        code = "\n".join(src[r["line"] - 1: r["line"] - 1 + r["block_lines"]])
        labels = _contract_labels(code)
        hist = _history(r["name"], labels, baseline)
        rows.append({
            "index": r["index"],
            "name": r["name"],
            "canonical": _canonical(r["name"]),
            "phase": _phase_of(r["name"], r["index"]),
            "modules": r["modules"],
            "block_lines": r["block_lines"],
            "runner_line": r["line"],
            # Колона 13. Договор се отваря в _run(); beat() пише само пулс. Един
            # булев отговаря на „защо няма история" за всичките 31 стъпки без
            # редове, без нито едно предположение — включително composers и
            # web_intelligence, които минават само през beat().
            "through_run": {"value": bool(labels), "labels": labels,
                            "why": (None if labels else
                                    "the block calls beat() but never _run(), so "
                                    "StepContract is never opened and no row is "
                                    "ever written for it")},
            "ceiling_sec": _ceiling_of(_canonical(r["name"])),
            "history": hist,
            "recent_times": _recent_times(r["name"], logs),
            "kills": _kills_for(r["name"], kill_index),
            "outputs": _declared_vs_touched(r["modules"], hist["touched"],
                                            hist["has_history"]),
            "child_processes": _spawns(code, r["modules"]),
            "internal_limits": _internal_limits(code, r["modules"]),
            "model": _model_calls(code, r["modules"]),
            "audit_flags": [f for f in r["flags"] if f != "UNREVIEWED"],
            "review": (r["review"] or {"verdict": "UNREVIEWED", "date": None}),
            # Колона 14. Еднаква във всеки ред НАРОЧНО: тя описва вечерта, не
            # стъпката. Подробностите са в cycle_context на горното ниво.
            "cycle_context": {"value": ctx["value"], "why": ctx["why"]},
            "state_derived": STATE_COLUMNS,
        })

    no_time_cap = [r["name"] for r in rows
                   if not r["internal_limits"]["internal_time_cap"]]
    touched_undeclared = [r["name"] for r in rows if r["outputs"]["touched_only"]]
    declared_untouched = [r["name"] for r in rows
                          if r["outputs"]["declared_only"] and not r["outputs"]["why"]]
    spawners = [r["name"] for r in rows if r["child_processes"]["spawns"]]

    no_history, by_reason = [r for r in rows if not r["history"]["has_history"]], {}
    for r in no_history:
        why = r["history"]["why"] or ""
        key = ("no _run() in the block — nobody ever writes a row for it"
               if "no _run() call" in why else
               "the _run() label is absent from the baseline file"
               if "no such key" in why else
               "key present, zero runs recorded" if "with no runs" in why else
               "other")
        by_reason.setdefault(key, []).append(r["name"])

    # Подредено по ДНЕВНИКА. Логът е само придружаваща бележка: подредба по него
    # би сложила най-често ТЕСТВАНАТА стъпка на върха на списъка с най-често
    # УБИВАНИТЕ, което е точно грешката, която колоната вече не прави.
    killed = [{"step": r["name"],
               "kills": r["kills"].get("kills"),
               "ages_sec": r["kills"].get("ages_sec", []),
               "corroboration": r["kills"].get("corroboration", {})}
              for r in rows if isinstance(r["kills"].get("kills"), int)
              and r["kills"]["kills"]]
    killed.sort(key=lambda d: d["kills"], reverse=True)

    no_run = [r["name"] for r in rows if not r["through_run"]["value"]]

    return {"ts": _now(), "steps": len(rows),
            "cycle_context": ctx,
            "summary": {
                "no_internal_time_cap": {"n": len(no_time_cap), "steps": no_time_cap},
                "touched_undeclared": {"n": len(touched_undeclared),
                                       "steps": touched_undeclared},
                "declared_untouched": {"n": len(declared_untouched),
                                       "steps": declared_untouched},
                "spawn_child": {"n": len(spawners), "steps": spawners},
                "no_history": {"n": len(no_history),
                               "by_reason": {k: {"n": len(v), "steps": v}
                                             for k, v in by_reason.items()}},
                "never_through_run": {"n": len(no_run), "steps": no_run},
                "most_killed": killed[:10]},
            "rows": rows}


def _cell(v) -> str:
    if v is None:
        return UNKNOWN
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, dict) and "value" in v:
        return str(v["value"])
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) if v else UNKNOWN
    return str(v)


def passport_md(p: dict) -> str:
    L = ["# STEP PASSPORT", "",
         f"Generated {p['ts']} by `tools/step_audit.py`. {p['steps']} steps.", "",
         "One mechanical row per step. **No judgement lives here.** What the step is "
         "for, which of the 14 points it serves, and the verdict are written by hand "
         "in `docs/STEP_LEDGER.md` with a date; this file reads that back only to "
         "mark what is still unreviewed.", "",
         f"`{UNKNOWN}` means NOT KNOWN, and the reason is listed at the bottom. It is "
         "never a zero: zero reads as \"none of them\", a dash reads as \"the question "
         "could not be answered\", and the difference is the point.", "",
         "**Code or state.** Phase, modules, ceiling, declared outputs, child "
         "processes, internal limits and model calls come from the code and the "
         "config, so two runs over an unchanged repo agree. History, recent times, "
         "kills and *touched* read the record — the baseline, the cycle logs, the "
         "supervisor log — and move every night. Every row carries `state_derived` "
         "naming them, so a property of this week is not read as a property of the "
         "code.", "",
         "**The kill column is the ledger, and only the ledger.** `kills` counts "
         "`CYCLE_KILLED` in `memory/existence_ledger.jsonl`, read off "
         "`reason.wedged_step` — the hash-chained record that only a real cycle "
         "writes. `logs/supervisor.log` appears in the JSON under `corroboration` "
         "and nowhere in this table, because it is poisoned: 720+ of its "
         "`KILL POLICY:` lines are fixtures, including 432 for `step='x'`, which is "
         "not a step. A fixture repeats verbatim, so `distinct_observations` there "
         "says how many real observations hide behind N identical lines.", ""]
    s = p["summary"]
    L += ["## Summary", "",
          f"- no internal time cap: **{s['no_internal_time_cap']['n']}** of {p['steps']}",
          f"- touch files they do not declare: **{s['touched_undeclared']['n']}**",
          f"- declare files never seen touched: **{s['declared_untouched']['n']}**",
          f"- spawn a child process: **{s['spawn_child']['n']}**",
          f"- never go through `_run()`, so no row is ever written for them: "
          f"**{s['never_through_run']['n']}**",
          f"- no history in the baseline: **{s['no_history']['n']}**"]
    for reason, d in sorted(s["no_history"]["by_reason"].items()):
        L.append(f"    - {d['n']}: {reason}")

    ctx = p.get("cycle_context") or {}
    L += ["", "## The memory the cycle had (column 14)", "",
          "A property of the NIGHT, not of any step, which is exactly why it is "
          "here: without it, \"died in composers\" reads as composers' fault. The "
          "cycle of 12 Sep 20:04 started with 2063 MB free against a measured "
          "appetite of ~1.9 GB typical and 2.7 GB at worst — the night was lost "
          "before composers had a turn.", ""]
    if ctx.get("why"):
        L += [f"{UNKNOWN} — {ctx['why']}", ""]
    else:
        ap = ctx.get("appetite_mb") or {}
        L += [f"Appetite over the finished cycles in this window: n={ap.get('n')}, "
              f"median {ap.get('median')} MB, max {ap.get('max')} MB. An exit row is "
              "written on the way out, so a killed cycle contributes none — "
              f"`{UNKNOWN}` in the exit column is a missing measurement, not zero "
              "memory spent, and is itself the signature of the death.", "",
              "| cycle | avail at start | avail at exit | consumed | outcome |",
              "|---|--:|--:|--:|---|"]
        for c in ctx.get("cycles", []):
            L.append(f"| {str(c['cycle_id'])[:30]} | {_cell(c['start_avail_mb'])} "
                     f"| {_cell(c['exit_avail_mb'])} | {_cell(c['consumed_mb'])} "
                     f"| {c['outcome']} |")
        L.append("")
    L += ["", "## Steps", "",
          "| # | step | phase | _run | modules | blk | ceil | n | med | p95 | recent "
          "| kills | decl-only | touch-only | both | child | req timeout | count cap "
          "| int time cap | retries | model | night | flags | reviewed |",
          "|---|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|--:|---|---|---|---|---|---|---|"]
    for r in p["rows"]:
        k, o, il, m, h = (r["kills"], r["outputs"], r["internal_limits"],
                          r["model"], r["history"])
        caps = il["count_caps"]
        L.append("| {i} | {nm} | {ph} | {ru} | {mo} | {bl} | {ce} | {n} | {md} | {q} "
                 "| {rc} | {kl} | {do} | {to} | {bo} | {ch} | {rt} | {cc} | {tc} "
                 "| {rr} | {ml} | {ni} | {fl} | {rv} |".format(
                     i=r["index"], nm=r["name"], ph=_cell(r["phase"]),
                     ru=("yes: " + ", ".join(r["through_run"]["labels"][:2])
                         if r["through_run"]["value"] else "**no**"),
                     mo=(", ".join(r["modules"]) if r["modules"]
                         else f"{UNKNOWN} inline"),
                     bl=r["block_lines"], ce=_cell(r["ceiling_sec"]),
                     n=_cell(h["n"]), md=_cell(h["median"]), q=_cell(h["p95"]),
                     rc=_cell(r["recent_times"]["value"]),
                     kl=_cell(k.get("kills")),
                     do=(len(o["declared_only"]) if not o["why"] else UNKNOWN),
                     to=(len(o["touched_only"]) if not o["why"] else UNKNOWN),
                     bo=(len(o["both"]) if not o["why"] else UNKNOWN),
                     ch=(f"yes ({r['child_processes']['n']})"
                         if r["child_processes"]["spawns"] else "no"),
                     rt=(il["request_timeouts"]["n"] or UNKNOWN),
                     cc=(", ".join(f"{a.split(':')[-1]}={b}"
                                   for a, b in list(caps.items())[:2])
                         if isinstance(caps, dict) else UNKNOWN),
                     tc=("yes" if il["internal_time_cap"] else "no"),
                     rr=(", ".join(il["retry_identifiers"][:2])
                         if isinstance(il["retry_identifiers"], list) else UNKNOWN),
                     ml=("yes: " + ", ".join((m["calls"] or m["modules"])[:2])
                         if m["calls_model"] else "no"),
                     ni=_cell(r["cycle_context"]),
                     fl=", ".join(r["audit_flags"]) or "-",
                     rv=(r["review"].get("date") or "UNREVIEWED")))
    L += ["", "## Why a cell is empty", ""]
    for r in p["rows"]:
        whys = [f"{lab}: {why}" for lab, why in (
            ("phase", r["phase"].get("why")),
            ("ceiling", r["ceiling_sec"].get("why")),
            ("history", r["history"].get("why")),
            ("recent times", r["recent_times"].get("why")),
            ("declared vs touched", r["outputs"].get("why")),
            ("count cap", r["internal_limits"].get("count_caps_why")),
            ("kills", r["kills"].get("why")),
            ("_run", r["through_run"].get("why"))) if why]
        if whys:
            L.append(f"- **{r['index']} {r['name']}** — " + "; ".join(whys))
    return "\n".join(L) + "\n"


def write_passport(rec: dict) -> dict:
    p = passport(rec)
    PASSPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    PASSPORT_JSON.write_text(json.dumps(p, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    PASSPORT_MD.write_text(passport_md(p), encoding="utf-8")
    return p


def main(argv: list) -> int:
    if "--selftest" in argv:
        return _selftest()
    rec = audit()
    only = argv[argv.index("--flag") + 1] if "--flag" in argv else None
    print(table(rec, only))
    print(f"\n{rec['steps']} steps | unreviewed {rec['unreviewed']} | "
          f"orphan {rec['orphans']} | stale {rec['stale']} | inline {rec['no_module']} | "
          f"tests writing live state: {len(rec['test_writes_live_state'])} | "
          f"unscheduled producers: {len(rec['unscheduled_producers'])}")
    for h in rec["test_writes_live_state"][:10]:
        print(f"  LIVE-STATE WRITE FROM TEST  {h['file']}:{h['line']}  {h['code']}")
    for u in rec["unscheduled_producers"]:
        print(f"  UNSCHEDULED PRODUCER        {u['module']} -> "
              f"{', '.join(u['outputs_read_by_others'])} (read nightly, run by nobody)")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {OUT.relative_to(REPO)}")

    p = write_passport(rec)
    s = p["summary"]
    print()
    print(f"PASSPORT  {p['steps']} steps | "
          f"no internal time cap {s['no_internal_time_cap']['n']} | "
          f"touch undeclared {s['touched_undeclared']['n']} | "
          f"declare untouched {s['declared_untouched']['n']} | "
          f"spawn a child {s['spawn_child']['n']} | "
          f"no history {s['no_history']['n']} | "
          f"never through _run() {s['never_through_run']['n']}")
    for reason, d in sorted(s["no_history"]["by_reason"].items()):
        print(f"  no history x{d['n']:<3} {reason}")
    for k in s["most_killed"][:10]:
        print(f"  KILLED {k['kills']}x  {k['step']}  "
              f"(ledger; log says {k['corroboration'].get('log_lines')} lines / "
              f"{k['corroboration'].get('log_distinct_observations')} distinct)")
    print(f"-> {PASSPORT_MD.relative_to(REPO)}  and  "
          f"{PASSPORT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

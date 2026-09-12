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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

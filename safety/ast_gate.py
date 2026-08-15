#!/usr/bin/env python3
"""
safety/ast_gate.py
AST-based capability gate за self-modifier-генериран код.

Fail-closed: ако walker-ът не може статично да ДОКАЖЕ, че нещо е безопасно
(computed getattr атрибут, non-provable open()/write_* target), се DENY-ва.

Това е първи слой статичен анализ, не sandboxing — не хваща всичко
(sys.modules манипулация, __builtins__ tampering, metaclass трикове и т.н.),
но покрива честите obfuscation bypass-и (getattr с computed атрибут,
string-concat/chr-built имена подадени на __import__).

WRITE-TARGET РЕЗОЛЮЦИЯ (2026-07-19)
-----------------------------------
По-рано write-таргетът трябваше да е ИНЛАЙН литерал или pathlib `/`-верига;
всяка индиректност (променлива, generic helper `_safe_save(path)`) се DENY-ваше,
дори когато присвоеният път беше безопасен литерал. Това правеше идиоматичните
патчове, които самата система генерира, невъзможни за прилагане.

Сега gate-ът РЕЗОЛВИРА таргета през, и само през, статично доказуеми стъпки:
  * локална единична присвоена стойност в обхващащата функция,
  * module-level единична присвоена константа,
  * `Path(x)` / `pathlib.Path(x)` обвивка → резолвира x,
  * функционален ПАРАМЕТЪР → доказва, че ВСЕКИ call site подава безопасна стойност
    на тази позиция (интерпроцедурно).
Всичко останало — reassignment, augmented assign, динамичен израз, *args/**kwargs
на call site, функция използвана като стойност (не извикана), рекурсия — е
недоказуемо и се DENY-ва. Разширението само ДОБАВЯ доказване-на-безопасно; никога
не допуска таргет, който не е доказано под ALLOWED_DIR_PREFIXES и извън denylist-а.

Използване:
  from safety.ast_gate import check_code
  allowed, reason = check_code(source)
"""

import ast

from safety.protected_paths import is_protected

# ── (1) забранени import-и (module или from-import) ─────────────────────────
BANNED_MODULES = {"subprocess", "socket", "urllib", "requests", "http", "ctypes"}

# ── (2) забранени directly-named call-ове ────────────────────────────────────
BANNED_CALL_NAMES = {"eval", "exec", "compile", "__import__", "import_module"}

# getattr(obj, "<име>") с ЛИТЕРАЛНО опасно име.
BANNED_ATTR_NAMES = {
    "system", "popen", "spawnl", "spawnv", "spawnve",
    "remove", "rmtree", "unlink", "chdir",
    "eval", "exec", "compile", "import_module",
}

# ── (4) забранени dotted call-ове ────────────────────────────────────────────
BANNED_DOTTED_CALLS = {
    "os.system",
    "os.remove",
    "shutil.rmtree",
    "os.chdir",
    "importlib.import_module",
}

# ── (3) позволени директории за open()/Path.write_*/Path.open() ─────────────
ALLOWED_DIR_PREFIXES = ("memory", "output", "data", "snapshots", "daily")

# Атрибутни методи, чийто target (обектът, върху който се вика) трябва да е
# доказуемо път под ALLOWED_DIR_PREFIXES.
_WRITE_LIKE_ATTRS = {"write_text", "write_bytes", "open"}

# ── ДУПКАТА ОТ 15 АВГ 2026 (намерена при спор с Kimi, стъпка 1) ──────────────
# Kimi: „AST gate проверява само source-а на patch файла, не и дали той модифицира
# други .py файлове при изпълнение. Ако patch-ът презапише safety/ast_gate.py,
# quarantine връща само patch файла — останалите модули остават компрометирани."
# Механизмът, който той описа (директен write), БЕШЕ покрит: write_text/open с
# непроверим таргет се спират. Но тестът намери истинския обход — функции, които
# пишат по ДЕСТИНАЦИЯ, без изобщо да пипат write_text/open:
#     shutil.copy("a.py", "core/brain.py")      -> минаваше
#     shutil.move / os.replace / os.rename      -> минаваха
# Тоест портата пазеше вратата и оставяше прозореца. Тук се затваря: за тези
# функции се проверява АРГУМЕНТЪТ-ДЕСТИНАЦИЯ по същия критерий.
# ЦЕНА ЗА САМОРАЗВИТИЕТО: нулева. Системата и досега не можеше да пише извън
# memory/output/data/snapshots/daily — просто вече не може и по обиколен път.
_DEST_ARG_FUNCS = {
    "copy": 1, "copy2": 1, "copyfile": 1, "move": 1,      # shutil
    "replace": 1, "rename": 1, "link": 1, "symlink": 1,   # os
}

# Конструктори, които просто обвиват пътен израз.
_PATH_CTOR_NAMES = {"Path", "pathlib.Path"}


def _dotted_name(node) -> str | None:
    """Възстановява 'a.b.c' от Name/Attribute верига; None ако не е такава верига."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _static_str_target_allowed(path_str: str) -> bool:
    """Литерален relative path срещу ALLOWED_DIR_PREFIXES + '..' traversal + denylist.

    ВАЖНО: prefix проверката НЕ Е достатъчна. Под memory/ живеят heartbeat.json,
    cycle.lock и existence_ledger.jsonl — is_protected() (denylist) бие allowlist-а.
    """
    norm = path_str.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return False  # абсолютен път (POSIX или Windows drive)
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return False
    if parts[0] not in ALLOWED_DIR_PREFIXES:
        return False
    return not is_protected(path_str)


def _div_chain_parts(node) -> list[tuple[str, str | None]]:
    """Разгъва ляво-асоциативна `/` верига (pathlib join) в подредена листа от
    ('const', value) | ('dynamic', None) части, ляво-надясно."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _div_chain_parts(node.left) + _div_chain_parts(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [("const", node.value)]
    # Path('literal') / pathlib.Path('literal') — извлечи литерала (безопасно:
    # traversal/абсолютни пътища пак се хващат от _static_str_target_allowed).
    if (isinstance(node, ast.Call)
            and _dotted_name(node.func) in _PATH_CTOR_NAMES
            and len(node.args) == 1 and not node.keywords
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return [("const", node.args[0].value)]
    return [("dynamic", None)]


def _div_chain_allowed(node) -> bool:
    """Статично проверява `/`-верига: приема ЕДИН евентуален водещ dynamic сегмент
    (типично BASE_DIR), всичко останало трябва да е литерал; dynamic сегмент СЛЕД
    първия литерал не може да гарантира липса на traversal → DENY."""
    parts = _div_chain_parts(node)
    if not parts:
        return False
    idx = 1 if parts[0][0] == "dynamic" else 0
    if idx >= len(parts):
        return False
    if any(kind == "dynamic" for kind, _ in parts[idx:]):
        return False
    literal_path = "/".join(value for _, value in parts[idx:])
    return _static_str_target_allowed(literal_path)


# ---------------------------------------------------------------------------
# Резолюционен контекст (scopes, assignments, call sites)
# ---------------------------------------------------------------------------

class _Context:
    def __init__(self):
        self.node_scope: dict[int, object] = {}   # id(node) -> FunctionDef | None
        self.func_defs: dict[str, object] = {}     # name -> FunctionDef
        self.ambiguous_funcs: set[str] = set()     # име, дефинирано >1 път
        self.params_of: dict[object, list[str]] = {}      # FunctionDef -> [позиционни имена]
        self.param_default: dict[object, dict] = {}       # FunctionDef -> {name: default_node}
        self.local_assigns: dict[object, dict] = {}       # FunctionDef -> {name: [rhs|None,...]}
        self.module_assigns: dict[str, list] = {}         # name -> [rhs|None,...]
        self.call_sites: dict[str, list] = {}             # func name -> [Call]
        self.noncall_refs: set[str] = set()               # функции използвани като стойност


def _record_assign(store: dict, name: str, value):
    store.setdefault(name, []).append(value)


def _build_context(tree) -> _Context:
    ctx = _Context()

    # Кои Name-nodes са в call-func позиция (за да ги отличим от bare-value употреба).
    called_func_name_ids: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            called_func_name_ids.add(id(n.func))
            ctx.call_sites.setdefault(n.func.id, []).append(n)

    load_names_noncall: set[str] = set()

    def _clean_targets(targets):
        """Yield (name, is_clean_single) за Assign targets. Complex target → None sentinel."""
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                yield tgt.id, True
            else:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        yield sub.id, False   # tuple/attr/subscript target → недоказуемо

    def visit(node, scope):
        ctx.node_scope[id(node)] = scope

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nm = node.name
            if nm in ctx.func_defs:
                ctx.ambiguous_funcs.add(nm)
            else:
                ctx.func_defs[nm] = node
            pos = list(getattr(node.args, "posonlyargs", [])) + list(node.args.args)
            names = [a.arg for a in pos]
            ctx.params_of[node] = names
            defaults = list(node.args.defaults or [])
            dmap = {}
            if defaults:
                tail = names[len(names) - len(defaults):]
                for nm2, d in zip(tail, defaults):
                    dmap[nm2] = d
            ctx.param_default[node] = dmap
            ctx.local_assigns.setdefault(node, {})
            for child in ast.iter_child_nodes(node):
                visit(child, node)
            return

        if isinstance(node, ast.Assign):
            for name, clean in _clean_targets(node.targets):
                val = node.value if clean else None
                if scope is None:
                    _record_assign(ctx.module_assigns, name, val)
                else:
                    _record_assign(ctx.local_assigns.setdefault(scope, {}), name, val)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                val = node.value  # може да е None (само анотация)
                if scope is None:
                    _record_assign(ctx.module_assigns, node.target.id, val)
                else:
                    _record_assign(ctx.local_assigns.setdefault(scope, {}), node.target.id, val)

        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                # augmented assign → недоказуемо (None sentinel)
                if scope is None:
                    _record_assign(ctx.module_assigns, node.target.id, None)
                else:
                    _record_assign(ctx.local_assigns.setdefault(scope, {}), node.target.id, None)

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if id(node) not in called_func_name_ids:
                load_names_noncall.add(node.id)

        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, None)
    # Функция, чието име се появява като bare стойност (не в call позиция), не може
    # да се проследи безопасно до call site-овете — може да бъде извикана другаде.
    ctx.noncall_refs = {nm for nm in load_names_noncall if nm in ctx.func_defs}
    return ctx


def _target_allowed(node, scope, ctx: _Context, visited: frozenset) -> bool:
    """Доказва ли се статично, че `node` сочи под ALLOWED_DIR_PREFIXES (и извън denylist)."""
    # 1. литерал
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _static_str_target_allowed(node.value)

    # 2. `/`-верига
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _div_chain_allowed(node)

    # 3. Path(x) / pathlib.Path(x) обвивка
    if isinstance(node, ast.Call):
        if (_dotted_name(node.func) in _PATH_CTOR_NAMES
                and len(node.args) == 1
                and not node.keywords
                and not any(isinstance(a, ast.Starred) for a in node.args)):
            return _target_allowed(node.args[0], scope, ctx, visited)
        return False

    # 4. Name — резолвирай binding
    if isinstance(node, ast.Name):
        name = node.id
        key = ("name", id(scope), name)
        if key in visited:
            return False
        visited = visited | {key}

        # 4a. локална присвоена стойност в обхващащата функция
        if scope is not None:
            locs = ctx.local_assigns.get(scope, {}).get(name)
            if locs is not None:
                if len(locs) != 1 or locs[0] is None:
                    return False
                return _target_allowed(locs[0], scope, ctx, visited)
            # 4b. параметър на обхващащата функция
            if name in ctx.params_of.get(scope, []):
                return _param_allowed(scope, name, ctx, visited)

        # 4c. module-level константа
        mods = ctx.module_assigns.get(name)
        if mods is not None:
            if len(mods) != 1 or mods[0] is None:
                return False
            return _target_allowed(mods[0], None, ctx, visited)

        return False

    return False


def _param_allowed(func, param_name: str, ctx: _Context, visited: frozenset) -> bool:
    """Доказва, че ВСЕКИ call site на `func` подава безопасна стойност на позицията
    на `param_name`. Fail-closed на всяка неяснота."""
    fname = func.name
    key = ("param", id(func), param_name)
    if key in visited:
        return False
    visited = visited | {key}

    if fname in ctx.ambiguous_funcs:
        return False
    if fname in ctx.noncall_refs:          # функцията се използва и като стойност
        return False

    params = ctx.params_of.get(func, [])
    if param_name not in params:
        return False
    idx = params.index(param_name)
    default_node = ctx.param_default.get(func, {}).get(param_name)

    sites = ctx.call_sites.get(fname, [])
    if not sites:
        return False                        # няма call site → недоказуемо

    for call in sites:
        # Разбъркани позиции / непрозрачни аргументи → недоказуемо.
        if any(isinstance(a, ast.Starred) for a in call.args):
            return False
        if any(kw.arg is None for kw in call.keywords):   # **kwargs
            return False

        if idx < len(call.args):
            value = call.args[idx]
        else:
            kw = next((k for k in call.keywords if k.arg == param_name), None)
            if kw is not None:
                value = kw.value
            elif default_node is not None:
                value = default_node
            else:
                return False                # аргументът липсва на този call site

        caller_scope = ctx.node_scope.get(id(call))
        if not _target_allowed(value, caller_scope, ctx, visited):
            return False

    return True


def check_code(source: str) -> tuple[bool, str]:
    """
    Проверява генериран Python код срещу capability gate.
    Връща (allowed, reason). Fail-closed: всичко, което walker-ът не може статично
    да ДОКАЖЕ безопасно, се DENY-ва.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"unclassifiable: syntax error ({e})"

    ctx = _build_context(tree)

    for node in ast.walk(tree):
        # ── (1) забранени import-и ──────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    return False, f"banned import: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BANNED_MODULES:
                return False, f"banned import: {node.module}"

        elif isinstance(node, ast.Call):
            func = node.func

            # ── (2) eval/exec/compile/__import__/import_module ──────────────
            if isinstance(func, ast.Name) and func.id in BANNED_CALL_NAMES:
                return False, f"banned call: {func.id}()"

            # ── (2) getattr — computed или литерално-опасен атрибут ─────────
            if isinstance(func, ast.Name) and func.id == "getattr":
                if len(node.args) < 2:
                    return False, "unclassifiable: getattr() call shape"
                attr_arg = node.args[1]
                if isinstance(attr_arg, ast.Constant) and isinstance(attr_arg.value, str):
                    if attr_arg.value in BANNED_ATTR_NAMES:
                        return False, f"getattr with dangerous attribute name: {attr_arg.value!r}"
                else:
                    return False, "unclassifiable: getattr with computed attribute name"

            # ── (4) os.system / os.remove / shutil.rmtree / os.chdir ────────
            dotted = _dotted_name(func)
            if dotted in BANNED_DOTTED_CALLS:
                return False, f"banned call: {dotted}()"

            # ── (3) open() ────────────────────────────────────────────────
            if isinstance(func, ast.Name) and func.id == "open":
                if not node.args:
                    return False, "unclassifiable: open() with no args"
                scope = ctx.node_scope.get(id(node))
                if not _target_allowed(node.args[0], scope, ctx, frozenset()):
                    return False, "open() target not statically verified under an allowed directory"

            # ── (3) Path.write_text()/write_bytes()/open() ───────────────────
            # копиране/местене: пази се ДЕСТИНАЦИЯТА (вторият аргумент)
            _fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if _fname in _DEST_ARG_FUNCS:
                _i = _DEST_ARG_FUNCS[_fname]
                if len(node.args) <= _i:
                    return False, f"{_fname}() without a statically visible destination"
                scope = ctx.node_scope.get(id(node))
                if not _target_allowed(node.args[_i], scope, ctx, frozenset()):
                    return False, (f"{_fname}() destination not statically verified "
                                   f"under an allowed directory")

            if isinstance(func, ast.Attribute) and func.attr in _WRITE_LIKE_ATTRS:
                scope = ctx.node_scope.get(id(node))
                if not _target_allowed(func.value, scope, ctx, frozenset()):
                    return False, f"{func.attr}() target not statically verified under an allowed directory"

    return True, "OK"

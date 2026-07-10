#!/usr/bin/env python3
"""
safety/ast_gate.py
AST-based capability gate за self-modifier-генериран код.

Fail-closed: ако walker-ът не може статично да класифицира нещо (computed
getattr атрибут, non-literal open()/write_* target), се DENY-ва, не се
допуска по подразбиране.

Това е първи слой статичен анализ, не sandboxing — не хваща всичко
(sys.modules манипулация, __builtins__ tampering, metaclass трикове и
т.н.), но покрива честите obfuscation bypass-и (getattr с computed
атрибут, string-concat/chr-built имена подадени на __import__).

Използване:
  from safety.ast_gate import check_code
  allowed, reason = check_code(source)
"""

import ast

# ── (1) забранени import-и (module или from-import) ─────────────────────────
BANNED_MODULES = {"subprocess", "socket", "urllib", "requests", "http", "ctypes"}

# ── (2) забранени directly-named call-ове ────────────────────────────────────
# import_module е включен защото е функционален еквивалент на __import__.
BANNED_CALL_NAMES = {"eval", "exec", "compile", "__import__", "import_module"}

# getattr(obj, "<име>") с ЛИТЕРАЛНО име, което директно съответства на опасен
# извикваем атрибут — затваря bypass-а на правило (4) през getattr.
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
    "importlib.import_module",  # __import__-еквивалент
}

# ── (3) позволени директории за open()/Path.write_*/Path.open() ─────────────
ALLOWED_DIR_PREFIXES = ("memory", "output", "data", "snapshots", "daily")

# Атрибутни методи, за които target-ът (обектът, върху който се вика) трябва
# да е статично проверим път под ALLOWED_DIR_PREFIXES.
_WRITE_LIKE_ATTRS = {"write_text", "write_bytes", "open"}


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
    """Проверява литерален relative path срещу ALLOWED_DIR_PREFIXES + '..' traversal."""
    norm = path_str.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return False  # абсолютен път (POSIX или Windows drive)
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return False
    return parts[0] in ALLOWED_DIR_PREFIXES


def _div_chain_parts(node) -> list[tuple[str, str | None]]:
    """Разгъва ляво-асоциативна верига от `/` (pathlib join) в подредена листа
    от ('const', value) | ('dynamic', None) части, ляво-надясно."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _div_chain_parts(node.left) + _div_chain_parts(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [("const", node.value)]
    return [("dynamic", None)]


def _path_target_allowed(node) -> bool:
    """
    Статично проверява дали Path-израз сочи под ALLOWED_DIR_PREFIXES.
    Приема ЕДИН евентуален водещ dynamic сегмент (типично BASE_DIR), всичко
    останало трябва да е литерал; ако dynamic сегмент се появи ПОСЛЕ първия
    литерал — не може да се гарантира липса на traversal → DENY.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _static_str_target_allowed(node.value)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
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

    return False  # Name/Call/Attribute/f-string и т.н. — не е статично проверимо


def check_code(source: str) -> tuple[bool, str]:
    """
    Проверява генериран Python код срещу capability gate.
    Връща (allowed, reason). Fail-closed: всичко, което walker-ът не може
    статично да класифицира, се DENY-ва.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"unclassifiable: syntax error ({e})"

    for node in ast.walk(tree):
        # ── (1) забранени import-и ──────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BANNED_MODULES:
                    return False, f"banned import: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in BANNED_MODULES:
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
                if not _path_target_allowed(node.args[0]):
                    return False, "open() target not statically verified under an allowed directory"

            # ── (3) Path.write_text()/write_bytes()/open() ───────────────────
            if isinstance(func, ast.Attribute) and func.attr in _WRITE_LIKE_ATTRS:
                if not _path_target_allowed(func.value):
                    return False, f"{func.attr}() target not statically verified under an allowed directory"

    return True, "OK"

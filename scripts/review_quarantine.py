#!/usr/bin/env python3
"""
scripts/review_quarantine.py
Human-only CLI за преглед на quarantine-нати self-modifier patches.

НЕ Е ЧАСТ ОТ АВТОМАТИЗИРАНИЯ ЦИКЪЛ — нищо във fast_cycle_runner.py,
execute_patches.py, self_modifier.py или patch_guardian.py не го извиква.
Само човек го пуска ръчно.

Usage:
  python scripts/review_quarantine.py                     # списък (таблица)
  python scripts/review_quarantine.py --show <name>       # пълен код + sidecar
  python scripts/review_quarantine.py --approve <name>    # ре-submit през PatchGuardian
  python scripts/review_quarantine.py --approve <name> --force-gate   # заобикаля AST gate (ОПАСНО)
  python scripts/review_quarantine.py --reject <name>     # premesti в quarantine/rejected/ (не се трие)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[1]
QUARANTINE_DIR = BASE_DIR / "patches" / "quarantine"
REJECTED_DIR = QUARANTINE_DIR / "rejected"

sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("CORTEX_BASE", str(BASE_DIR))


def _list_entries():
    """Всеки .py в quarantine/ (не в rejected/) с матчващ .json sidecar."""
    if not QUARANTINE_DIR.exists():
        return []
    entries = []
    for py in sorted(QUARANTINE_DIR.glob("*.py")):
        sidecar = py.parent / f"{py.name}.json"
        meta = {}
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        entries.append((py, sidecar, meta))
    return entries


def _component_of(meta: dict, py: Path) -> str:
    orig = meta.get("original_filename", py.name)
    name = Path(orig).name
    if name.endswith("_patch.py"):
        return name[: -len("_patch.py")]
    return name


def cmd_list():
    entries = _list_entries()
    if not entries:
        print("Quarantine е празна.")
        return
    print(f"{'DATE':20}  {'COMPONENT':16}  {'REASON':42}  CODE PREVIEW")
    print("-" * 110)
    for py, _sidecar, meta in entries:
        ts = meta.get("timestamp", "")
        date_str = ts[:19] if ts else "?"
        component = _component_of(meta, py)
        reason = (meta.get("deny_reason") or "")[:42]
        try:
            lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            lines = []
        code_lines = [l.strip() for l in lines if l.strip()][:3]
        preview = " / ".join(code_lines)[:60]
        print(f"{date_str:20}  {component:16}  {reason:42}  {preview}")
    print(f"\n{len(entries)} quarantined patch(es). Виж --show <name> за детайли.")


def _find(name: str):
    """Точно съвпадение на .py име/stem, иначе уникален substring match."""
    entries = _list_entries()
    exact = [e for e in entries if e[0].name == name or e[0].stem == name]
    if exact:
        return exact[0]
    partial = [e for e in entries if name in e[0].name]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        print(f"Няколко съвпадения за '{name}':")
        for py, _, _ in partial:
            print(f"  {py.name}")
        return None
    print(f"Няма quarantine entry, съвпадащ с '{name}'.")
    return None


def cmd_show(name: str):
    found = _find(name)
    if not found:
        return
    py, _sidecar, meta = found
    print("=" * 70)
    print(f"PATCH: {py.name}")
    print("=" * 70)
    print(py.read_text(encoding="utf-8", errors="replace"))
    print("=" * 70)
    print("SIDECAR:")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def cmd_reject(name: str):
    found = _find(name)
    if not found:
        return
    py, sidecar, _meta = found
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    dest_py = REJECTED_DIR / py.name
    shutil.move(str(py), str(dest_py))
    if sidecar.exists():
        shutil.move(str(sidecar), str(REJECTED_DIR / sidecar.name))
    print(f"Отхвърлен -> {dest_py.relative_to(BASE_DIR)} (никога не се трие).")


def _guess_original_target(py: Path, meta: dict) -> str:
    target = meta.get("original_filename")
    if target:
        return target
    # fallback: strip trailing .<timestamp>[.n] segments от quarantine-натото име
    parts = py.stem.split(".")
    while parts and parts[-1].isdigit():
        parts.pop()
    return f"agents/core/{'.'.join(parts)}.py"


async def cmd_approve(name: str, force_gate: bool):
    found = _find(name)
    if not found:
        return
    py, sidecar, meta = found
    source = py.read_text(encoding="utf-8", errors="replace")
    target = _guess_original_target(py, meta)

    if force_gate:
        print("!" * 70)
        print("!!  --force-gate: AST CAPABILITY GATE Е РЪЧНО ЗАОБИКОЛЕН ОТ ЧОВЕК.  !!")
        print("!!  Кодът отива директно към PatchGuardian БЕЗ статичен анализ.     !!")
        print("!" * 70)
    else:
        from safety.ast_gate import check_code
        allowed, reason = check_code(source)
        if not allowed:
            print(f"⛔ AST gate все още отхвърля този patch: {reason}")
            print("   Използвай --force-gate за да заобиколиш (не препоръчително).")
            return
        print("✔ AST gate: разрешен.")

    from patch_guardian import PatchGuardian

    print(f"Ре-submit -> {target} през PatchGuardian.apply_patch()...")
    guardian = PatchGuardian()
    prev_cwd = os.getcwd()
    os.chdir(BASE_DIR)
    try:
        result = await guardian.apply_patch(target, source)
    finally:
        os.chdir(prev_cwd)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if result.success:
        py.unlink(missing_ok=True)
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)
        print("✅ Одобрен и приложен. Премахнат от quarantine.")
    else:
        print(f"❌ PatchGuardian отхвърли patch-а [{result.stage}]: {result.error}")
        print("   Остава в quarantine (guardian-ът отново quarantine-на новия опит отделно).")


def main():
    parser = argparse.ArgumentParser(
        description="Преглед на quarantine-нати self-modifier patches (само за хора — не се вика от автоматизирания цикъл)."
    )
    parser.add_argument("--show", metavar="NAME", help="Покажи пълен код + sidecar за един patch")
    parser.add_argument("--approve", metavar="NAME", help="Ре-submit patch през PatchGuardian pipeline-а")
    parser.add_argument("--reject", metavar="NAME", help="Премести в patches/quarantine/rejected/ (не се трие)")
    parser.add_argument(
        "--force-gate", action="store_true",
        help="При --approve: заобикаля AST capability gate-а (ОПАСНО, само ръчно)",
    )
    args = parser.parse_args()

    if args.show:
        cmd_show(args.show)
    elif args.approve:
        asyncio.run(cmd_approve(args.approve, args.force_gate))
    elif args.reject:
        cmd_reject(args.reject)
    else:
        cmd_list()


if __name__ == "__main__":
    main()

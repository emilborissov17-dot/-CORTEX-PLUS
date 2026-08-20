"""
Bring agi_axes_spec.txt under the same 5 subgoals as config/target_config.json,
and add the three axis definitions that never existed.

agi_axes_spec.txt held a THIRD copy of the tree structure, in its TOP_LEVEL_AXES
block: HUMAN / PLANET / CIVILIZATION / COSMOS with CHILD_AXES lists. Three copies
of one structure in three files is how the three missing HUMAN definitions
survived for months -- no copy was authoritative, so no copy was wrong.

After this script the structure exists in exactly one authoritative place
(civilization_goal.txt), target_config.json groups by it, and this file's
TOP_LEVEL_AXES is GENERATED from target_config.json. The CI guard fails the
build if they diverge.

Every pre-existing axis block is copied byte-for-byte. The script asserts this;
it does not ask to be trusted.

Usage:
    python scripts/regroup_axis_spec_to_subgoals.py            # dry run
    python scripts/regroup_axis_spec_to_subgoals.py --write
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
from collections import OrderedDict

BASE = pathlib.Path(__file__).resolve().parents[1]
SPEC = BASE / "agi_axes_spec.txt"
CFG = BASE / "config" / "target_config.json"
GOAL = BASE / "civilization_goal.txt"
NEW_DEFS = BASE / "scripts" / "_new_axis_defs.txt"

RULE = "#" * 60


def parse_axis_blocks(text: str) -> "OrderedDict[str, str]":
    """AXIS_NAME -> verbatim block text (from its AXIS_NAME line to just before
    the next AXIS_NAME line or the next ### rule)."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.startswith("AXIS_NAME:")]
    blocks: "OrderedDict[str, str]" = OrderedDict()
    for n, start in enumerate(starts):
        end = len(lines)
        limit = starts[n + 1] if n + 1 < len(starts) else len(lines)
        for i in range(start + 1, limit):
            if lines[i].startswith("#" * 10):
                end = i
                break
        else:
            end = limit
        name = lines[start].split(":", 1)[1].strip()
        if name in blocks:
            raise SystemExit(f"FATAL: axis {name} defined twice in the spec")
        blocks[name] = "".join(lines[start:end]).rstrip() + "\n"
    return blocks


def parse_goal(text: str) -> "OrderedDict[int, dict]":
    out: "OrderedDict[int, dict]" = OrderedDict()
    current = None
    for raw in text.splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.+?)\s*$", raw)
        if m:
            current = int(m.group(1))
            out[current] = {"title": m.group(2).strip(), "bullets": []}
            continue
        b = re.match(r"^\s*-\s+(.+?)\s*$", raw)
        if b and current is not None:
            out[current]["bullets"].append(b.group(1).strip())
    return out


def build(spec_text: str, cfg: dict, goal: dict, new_defs: str) -> str:
    blocks = parse_axis_blocks(spec_text)
    blocks.update(parse_axis_blocks(new_defs))

    branches_meta = cfg["_meta"]["branches"]
    tree = OrderedDict(
        (k, list(v.keys())) for k, v in cfg.items() if not str(k).startswith("_")
    )

    declared = {a for axes in tree.values() for a in axes}
    missing = sorted(declared - set(blocks))
    orphan = sorted(set(blocks) - declared)
    if missing:
        raise SystemExit(f"FATAL: config carries axes with no definition: {missing}")
    if orphan:
        raise SystemExit(f"FATAL: spec defines axes the config does not carry: {orphan}")

    out: list = []
    out.append("AGI AXES SPEC – CIVILIZATION ALIGNED\n")
    out.append("Версия: 3.0\n")
    out.append("Описание:\n")
    out.append("  Този файл дефинира какво ЗНАЧИ LOW / MEDIUM / HIGH за всяка ос,\n")
    out.append("  по която CORTEX++ оценява състоянието и движението на цивилизацията.\n")
    out.append("  Тегло без дефиниция зад него е число, което никой не може да обори.\n")
    out.append("\n")
    out.append("  СТРУКТУРА: топ-нивото тук НЕ е самостоятелна таксономия. То е\n")
    out.append("  списъкът на подцелите от civilization_goal.txt — същият, по който\n")
    out.append("  config/target_config.json групира осите. Разминаване между трите\n")
    out.append("  файла проваля test/test_axis_tree_contract.py.\n")
    out.append("\n")
    out.append("  Четирите домена (PLANET / HUMAN / CIVILIZATION / COSMOS) остават,\n")
    out.append("  но на СЕТИВНАТА страна — в config/domains_tree.json те казват откъде\n")
    out.append("  ИДВА измерването. Тук се казва към коя ЦЕЛ то служи. Всяка ос пази\n")
    out.append("  legacy_domain в target_config.json, за да останат сравними сериите\n")
    out.append("  отпреди пренареждането.\n")
    out.append("\n")
    out.append(f"{RULE}\n# TOP LEVEL AXES — генерирано от config/target_config.json\n{RULE}\n")
    out.append("\n")
    out.append("TOP_LEVEL_AXES:\n")

    for branch, axes in tree.items():
        meta = branches_meta[branch]
        idx = meta["subgoal_index"]
        sub = goal[idx]
        out.append(f"  - {branch}:\n")
        out.append(f"      SUBGOAL: {idx}. {sub['title']}\n")
        out.append("      DESCRIPTION:\n")
        for bullet in sub["bullets"]:
            out.append(f"        - {bullet}\n")
        out.append("      CHILD_AXES:\n")
        for axis in axes:
            out.append(f"        - {axis}\n")
        out.append("\n")

    for branch, axes in tree.items():
        out.append("\n")
        out.append(f"{RULE}\n# {branch}\n{RULE}\n")
        out.append("\n")
        for axis in axes:
            out.append(blocks[axis])
            out.append("\n")

    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    spec_text = SPEC.read_text(encoding="utf-8")
    original = parse_axis_blocks(spec_text)
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    goal = parse_goal(GOAL.read_text(encoding="utf-8"))
    new_defs = NEW_DEFS.read_text(encoding="utf-8")

    result = build(spec_text, cfg, goal, new_defs)

    # every pre-existing block must survive byte-for-byte
    rebuilt = parse_axis_blocks(result)
    for name, block in original.items():
        if rebuilt[name] != block:
            raise SystemExit(f"FATAL: block for {name} was altered by the rewrite")
    added = sorted(set(rebuilt) - set(original))

    print(f"axis blocks before : {len(original)}")
    print(f"axis blocks after  : {len(rebuilt)}")
    print(f"added definitions  : {added}")
    print(f"top-level branches : {[k for k in cfg if not k.startswith('_')]}")
    print("all pre-existing blocks byte-identical: OK")

    if args.write:
        shutil.copy2(SPEC, SPEC.with_suffix(".txt.bak"))
        SPEC.write_text(result, encoding="utf-8")
        print(f"\nWRITTEN: {SPEC}   (backup: {SPEC.with_suffix('.txt.bak')})")
    else:
        print("\nDRY RUN. Nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

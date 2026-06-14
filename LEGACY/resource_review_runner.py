#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime, timezone
import subprocess
from pathlib import Path

BASEDIR = Path(os.path.dirname(os.path.abspath(__file__)))

HISTORYDIR = BASEDIR / "history"
CONFIGDIR = BASEDIR / "config"
KNOWLEDGEDIR = BASEDIR / "knowledge"

JOURNAL_RESOURCE_ACT = BASEDIR / "journal_resource_act.txt"
SELF_IMPROVEMENT_FILE = CONFIGDIR / "self_improvement_suggestions.txt"

ENERGY_SNAPSHOTS_DIR = KNOWLEDGEDIR / "energy_snapshots"
WATER_SNAPSHOTS_DIR = KNOWLEDGEDIR / "water_snapshots"
FOOD_SNAPSHOTS_DIR = KNOWLEDGEDIR / "food_snapshots"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs():
    HISTORYDIR.mkdir(exist_ok=True)
    CONFIGDIR.mkdir(exist_ok=True)
    KNOWLEDGEDIR.mkdir(exist_ok=True)


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_snapshot_files(directory: Path, summary_marker: str):
    if not directory.exists():
        return []
    files = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix == ".json":
            if summary_marker in f.name:
                continue
            files.append(f)
    return files


def build_energy_review_prompt(summary_data, snapshot_files):
    lines = []
    ts = utc_iso()
    lines.append("TITLE: ENERGY REVIEW")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append("")
    lines.append("You are the ENERGY REVIEW agent of the CORTEX system.")
    lines.append("Your task is to evaluate the global energy system from the perspective of a sustainable, equitable civilization.")
    lines.append("")
    lines.append("1) INPUT DATA")
    lines.append("1.1) High-level summary from ENERGY_QUERY:")
    try:
        pretty_summary = json.dumps(summary_data, ensure_ascii=False, indent=2)
    except Exception:
        pretty_summary = str(summary_data)
    lines.append(pretty_summary)
    lines.append("")
    lines.append("1.2) Snapshot files list:")
    for f in snapshot_files:
        lines.append(f"- {f.name}")
    lines.append("")
    lines.append("2) REQUIRED OUTPUT FORMAT (STRICT):")
    lines.append("You MUST answer in valid JSON with the following top-level keys:")
    lines.append("""
{
  "diagnosis": {
    "status": "OK / STRESSED / CRITICAL",
    "short_summary_bg": "...",
    "key_metrics": [
      {"name": "...", "value": "...", "interpretation_bg": "..."}
    ]
  },
  "risks": [
    {"name": "...", "description_bg": "...", "time_horizon": "short/medium/long"}
  ],
  "opportunities": [
    {"name": "...", "description_bg": "..."}
  ],
  "recommended_actions": [
    {"id": "ENERGY-ACT-001", "title_bg": "...", "description_bg": "...", "priority": "low/medium/high"}
  ],
  "notes_for_cortex_self_improvement": [
    "..."
  ]
}
    """.strip())
    lines.append("")
    lines.append("All Bulgarian text must be clear and concise.")
    lines.append("Do not include any text outside the JSON object.")
    return "\n".join(lines)


def build_water_review_prompt(summary_data, snapshot_files):
    lines = []
    ts = utc_iso()
    lines.append("TITLE: WATER REVIEW")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append("")
    lines.append("You are the WATER REVIEW agent of the CORTEX system.")
    lines.append("Your task is to evaluate the global water system (availability, quality, access, risks) from the perspective of a sustainable, equitable civilization.")
    lines.append("")
    lines.append("1) INPUT DATA")
    lines.append("1.1) High-level summary from WATER_QUERY:")
    try:
        pretty_summary = json.dumps(summary_data, ensure_ascii=False, indent=2)
    except Exception:
        pretty_summary = str(summary_data)
    lines.append(pretty_summary)
    lines.append("")
    lines.append("1.2) Snapshot files list:")
    for f in snapshot_files:
        lines.append(f"- {f.name}")
    lines.append("")
    lines.append("2) REQUIRED OUTPUT FORMAT (STRICT):")
    lines.append("You MUST answer in valid JSON with the following top-level keys:")
    lines.append("""
{
  "diagnosis": {
    "status": "OK / STRESSED / CRITICAL",
    "short_summary_bg": "...",
    "key_metrics": [
      {"name": "...", "value": "...", "interpretation_bg": "..."}
    ]
  },
  "risks": [
    {"name": "...", "description_bg": "...", "time_horizon": "short/medium/long"}
  ],
  "opportunities": [
    {"name": "...", "description_bg": "..."}
  ],
  "recommended_actions": [
    {"id": "WATER-ACT-001", "title_bg": "...", "description_bg": "...", "priority": "low/medium/high"}
  ],
  "notes_for_cortex_self_improvement": [
    "..."
  ]
}
    """.strip())
    lines.append("")
    lines.append("All Bulgarian text must be clear and concise.")
    lines.append("Do not include any text outside the JSON object.")
    return "\n".join(lines)


def build_food_review_prompt(summary_data, snapshot_files):
    lines = []
    ts = utc_iso()
    lines.append("TITLE: FOOD REVIEW")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append("")
    lines.append("You are the FOOD REVIEW agent of the CORTEX system.")
    lines.append("Your task is to evaluate the global food system (production, access, nutrition, waste) from the perspective of a sustainable, equitable civilization.")
    lines.append("")
    lines.append("1) INPUT DATA")
    lines.append("1.1) High-level summary from FOOD_QUERY:")
    try:
        pretty_summary = json.dumps(summary_data, ensure_ascii=False, indent=2)
    except Exception:
        pretty_summary = str(summary_data)
    lines.append(pretty_summary)
    lines.append("")
    lines.append("1.2) Snapshot files list:")
    for f in snapshot_files:
        lines.append(f"- {f.name}")
    lines.append("")
    lines.append("2) REQUIRED OUTPUT FORMAT (STRICT):")
    lines.append("You MUST answer in valid JSON with the following top-level keys:")
    lines.append("""
{
  "diagnosis": {
    "status": "OK / STRESSED / CRITICAL",
    "short_summary_bg": "...",
    "key_metrics": [
      {"name": "...", "value": "...", "interpretation_bg": "..."}
    ]
  },
  "risks": [
    {"name": "...", "description_bg": "...", "time_horizon": "short/medium/long"}
  ],
  "opportunities": [
    {"name": "...", "description_bg": "..."}
  ],
  "recommended_actions": [
    {"id": "FOOD-ACT-001", "title_bg": "...", "description_bg": "...", "priority": "low/medium/high"}
  ],
  "notes_for_cortex_self_improvement": [
    "..."
  ]
}
    """.strip())
    lines.append("")
    lines.append("All Bulgarian text must be clear and concise.")
    lines.append("Do not include any text outside the JSON object.")
    return "\n".join(lines)


def call_cortex_llm_resource(domain: str, prompt_text: str) -> str:
    """
    Вика cortex_llm_resource.py така, както очаква: с --input/--output файлове.
    """
    ts = utc_iso().replace(":", "").replace("-", "")
    tmp_in = BASEDIR / f"tmp_resource_review_{domain}_{ts}.txt"
    tmp_out = BASEDIR / f"tmp_resource_review_{domain}_{ts}_out.txt"

    try:
        with tmp_in.open("w", encoding="utf-8") as f:
            f.write(prompt_text)
    except Exception as e:
        return f"ERROR: cannot write temp input file: {e}"

    cmd = [
        sys.executable,
        str(BASEDIR / "cortex_llm_resource.py"),
        f"--domain={domain}",
        f"--input={tmp_in}",
        f"--output={tmp_out}",
    ]

    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False
        )
    except Exception as e:
        return f"ERROR: subprocess failed: {e}"

    if result.returncode != 0:
        err = result.stderr.strip() if result.stderr else ""
        try:
            if tmp_in.exists():
                tmp_in.unlink()
            if tmp_out.exists():
                tmp_out.unlink()
        except Exception:
            pass
        return f"ERROR: cortex_llm_resource.py exited with {result.returncode}: {err}"

    try:
        if tmp_out.exists():
            with tmp_out.open("r", encoding="utf-8") as f:
                out_text = f.read().strip()
        else:
            out_text = ""
    except Exception as e:
        out_text = f"ERROR: cannot read temp output file: {e}"

    try:
        if tmp_in.exists():
            tmp_in.unlink()
        if tmp_out.exists():
            tmp_out.unlink()
    except Exception:
        pass

    return out_text


def append_journal_entry(domain: str, prompt_text: str, llm_output: str):
    ensure_dirs()
    ts = utc_iso()
    lines = []
    lines.append("===== RESOURCE_REVIEW ENTRY START =====")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append(f"DOMAIN: {domain}")
    lines.append("")
    lines.append("PROMPT:")
    lines.append(prompt_text)
    lines.append("")
    lines.append("LLM_OUTPUT:")
    lines.append(llm_output)
    lines.append("===== RESOURCE_REVIEW ENTRY END =====")
    lines.append("")
    try:
        with JOURNAL_RESOURCE_ACT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[{ts}] ERROR: write journal_resource_act.txt - {e}", flush=True)


def append_self_improvement(domain: str, llm_output: str):
    """
    Ако JSON има notes_for_cortex_self_improvement, append-ваме ги в self_improvement_suggestions.txt.
    """
    ensure_dirs()
    ts = utc_iso()
    notes = []
    try:
        data = json.loads(llm_output)
        raw_notes = data.get("notes_for_cortex_self_improvement", [])
        if isinstance(raw_notes, list):
            notes = [str(x) for x in raw_notes]
    except Exception:
        notes = [f"RAW_OUTPUT ({domain}) not JSON, see journal_resource_act.txt"]

    if not notes:
        return

    lines = []
    lines.append("SELF_IMPROVEMENT_ENTRY_START")
    lines.append(f"TIMESTAMP_UTC: {ts}")
    lines.append(f"DOMAIN: {domain}")
    for n in notes:
        lines.append(f"- {n}")
    lines.append("SELF_IMPROVEMENT_ENTRY_END")
    lines.append("")
    try:
        with SELF_IMPROVEMENT_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[{ts}] ERROR: write self_improvement_suggestions.txt - {e}", flush=True)


def run_energy_review():
    summary = load_json(ENERGY_SNAPSHOTS_DIR / "energy_query_summary.json")
    if summary is None:
        print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: no energy_query_summary.json, skipping", flush=True)
        return

    snapshot_files = list_snapshot_files(ENERGY_SNAPSHOTS_DIR, "energy_query_summary")
    prompt = build_energy_review_prompt(summary, snapshot_files)
    llm_output = call_cortex_llm_resource("energy", prompt)

    ts = utc_iso()
    print(f"[{ts}] ENERGY_REVIEW_RUNNER: LLM call finished, length={len(llm_output)}", flush=True)

    append_journal_entry("energy", prompt, llm_output)
    append_self_improvement("energy", llm_output)


def run_water_review():
    summary = load_json(WATER_SNAPSHOTS_DIR / "water_query_summary.json")
    if summary is None:
        print(f"[{utc_iso()}] WATER_REVIEW_RUNNER: no water_query_summary.json, skipping", flush=True)
        return

    snapshot_files = list_snapshot_files(WATER_SNAPSHOTS_DIR, "water_query_summary")
    prompt = build_water_review_prompt(summary, snapshot_files)
    llm_output = call_cortex_llm_resource("water", prompt)

    ts = utc_iso()
    print(f"[{ts}] WATER_REVIEW_RUNNER: LLM call finished, length={len(llm_output)}", flush=True)

    append_journal_entry("water", prompt, llm_output)
    append_self_improvement("water", llm_output)


def run_food_review():
    summary = load_json(FOOD_SNAPSHOTS_DIR / "food_query_summary.json")
    if summary is None:
        print(f"[{utc_iso()}] FOOD_REVIEW_RUNNER: no food_query_summary.json, skipping", flush=True)
        return

    snapshot_files = list_snapshot_files(FOOD_SNAPSHOTS_DIR, "food_query_summary")
    prompt = build_food_review_prompt(summary, snapshot_files)
    llm_output = call_cortex_llm_resource("food", prompt)

    ts = utc_iso()
    print(f"[{ts}] FOOD_REVIEW_RUNNER: LLM call finished, length={len(llm_output)}", flush=True)

    append_journal_entry("food", prompt, llm_output)
    append_self_improvement("food", llm_output)


def main():
    ensure_dirs()
    if len(sys.argv) < 2:
        print("Usage: resource_review_runner.py --domain=energy|water|food", flush=True)
        sys.exit(1)

    domain_arg = sys.argv[1]
    if domain_arg.startswith("--domain="):
        domain = domain_arg.split("=", 1)[1].strip()
    else:
        domain = domain_arg.strip()

    d = domain.lower()
    if d == "energy":
        run_energy_review()
    elif d == "water":
        run_water_review()
    elif d == "food":
        run_food_review()
    else:
        print(f"[{utc_iso()}] RESOURCE_REVIEW_RUNNER: unknown domain '{domain}' (only 'energy','water','food' supported now)", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()

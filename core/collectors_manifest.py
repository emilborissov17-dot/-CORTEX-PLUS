"""
core/collectors_manifest.py — what the collectors fetched, when, and on what footing.

Task #8 B.B (25 Sep 2026). web_intelligence and data_scout no longer run inside the
spine. collectors_runner.py runs them before it, in their own witnessed process, and
writes one manifest per run. The spine reads the collectors ONLY through this
manifest: which files a collector wrote, when it fetched (fetched_at - a spelling
registered in config/field_names.json), and its provenance level.

THE LEVELS. There are exactly three, and a collector entry always carries one:
  MODEL_ANSWERED  at least one model call made under the collector's step answered ok;
  NO_MODEL_CALL   the collector finished and recorded no model call at all (cache,
                  plain fetch) - nothing was asked of a model, so nothing is claimed;
  UNVERIFIED      the collector failed, ran out of budget, or asked a model and got no
                  answer. The entry then carries `reason`, never a blank.
A manifest entry with no level, or UNVERIFIED with no reason, is refused by
validate() - an unknown origin is what this file exists to prevent.

This module imports no model and nothing that does; the spine imports it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DIR = BASE / "memory" / "collectors"
LATEST = DIR / "manifest_latest.json"
PROVENANCE = BASE / "memory" / "llm_provenance.jsonl"

COLLECTORS = ("web_intelligence", "data_scout")
MODEL_ANSWERED = "MODEL_ANSWERED"
NO_MODEL_CALL = "NO_MODEL_CALL"
UNVERIFIED = "UNVERIFIED"
LEVELS = (MODEL_ANSWERED, NO_MODEL_CALL, UNVERIFIED)
MAX_AGE_H = 26.0     # a manifest from before yesterday's collectors is stale


def _parse(ts) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def model_calls(step: str, since: datetime, path: Path | None = None) -> dict:
    """Outcome counts of the llm_door rows written under `step` since `since`."""
    out = {"ok": 0, "refused": 0, "error": 0, "reasons": []}
    try:
        lines = (path or PROVENANCE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("step") != step:
            continue
        t = _parse(r.get("ts"))
        if t is None or t < since:
            continue
        o = r.get("outcome")
        if o in out:
            out[o] += 1
            if o != "ok" and r.get("error") and len(out["reasons"]) < 3:
                out["reasons"].append(str(r.get("error"))[:120])
    return out


def level_for(status: str, calls: dict) -> tuple[str, str | None]:
    """(level, reason). status is the collector's own ending: ok | failed | timeout."""
    if status != "ok":
        return UNVERIFIED, f"the collector ended {status}"
    if calls.get("ok", 0) > 0:
        return MODEL_ANSWERED, None
    asked = calls.get("refused", 0) + calls.get("error", 0)
    if asked:
        why = "; ".join(calls.get("reasons") or []) or "no reason recorded"
        return UNVERIFIED, (f"ran without its model: {calls.get('refused', 0)} refused, "
                            f"{calls.get('error', 0)} error, 0 answered ({why})")
    return NO_MODEL_CALL, None


def entry(name: str, started: datetime, status: str, written: list, calls: dict,
          detail: str = "") -> dict:
    lvl, reason = level_for(status, calls)
    e = {"collector": name, "fetched_at": started.isoformat(), "status": status,
         "level": lvl, "model_calls": {k: calls.get(k, 0) for k in ("ok", "refused", "error")},
         "outputs": sorted(written)}
    if reason:
        e["reason"] = reason
    if detail:
        e["detail"] = detail
    return e


def write(manifest: dict, base: Path | None = None) -> Path:
    d = (base / "memory" / "collectors") if base else DIR
    day = str(manifest.get("collector_run_id", ""))[:10] or datetime.now().date().isoformat()
    (d / day).mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (d / day / "manifest.json").write_text(text, encoding="utf-8")
    (d / "manifest_latest.json").write_text(text, encoding="utf-8")
    return d / "manifest_latest.json"


def validate(name: str, now: datetime | None = None, path: Path | None = None) -> dict:
    """What the spine may say about one collector. Reads only; never runs anything.

    Returns {ok, collector, level, fetched_at, age_h, outputs, problems}. `ok` is
    False when the manifest is missing, unreadable, stale, lacks this collector, or
    the entry breaks the level rule - each such case is named in `problems`.
    """
    now = now or datetime.now(timezone.utc)
    res = {"ok": False, "collector": name, "level": None, "fetched_at": None,
           "age_h": None, "outputs": [], "problems": []}
    p = path or LATEST
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        res["problems"].append(f"no collectors manifest at {p.name} - the collectors never ran")
        return res
    except Exception as exc:  # noqa: BLE001
        res["problems"].append(f"manifest unreadable ({type(exc).__name__}: {exc})")
        return res
    e = (m.get("collectors") or {}).get(name)
    if not isinstance(e, dict):
        res["problems"].append(f"{name} is not in the manifest of {m.get('collector_run_id')}")
        return res
    res["level"] = e.get("level")
    res["fetched_at"] = e.get("fetched_at")
    res["outputs"] = list(e.get("outputs") or [])
    if res["level"] not in LEVELS:
        res["problems"].append(f"level {res['level']!r} is not one of {LEVELS} - unknown origin")
    if res["level"] == UNVERIFIED and not e.get("reason"):
        res["problems"].append("UNVERIFIED without a reason")
    t = _parse(res["fetched_at"])
    if t is None:
        res["problems"].append("no fetched_at - no observation date")
    else:
        res["age_h"] = round((now - t).total_seconds() / 3600, 1)
        if res["age_h"] > MAX_AGE_H:
            res["problems"].append(f"stale: fetched {res['age_h']} h ago (> {MAX_AGE_H} h)")
    base = p.parents[2] if p.parent.name == "collectors" else BASE
    missing = [o for o in res["outputs"] if not (base / o).exists()]
    if missing:
        res["problems"].append(f"{len(missing)} listed output(s) missing, e.g. {missing[0]}")
    res["ok"] = not res["problems"]
    return res

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/vector.py — THE CHAIN FROM SENSORS TO A GLYPH, AND THE REFUSAL TO RUSH IT.

WHAT THE VECTOR IS
-------------------
Twenty-five dimensions, assembled at cycle end from the somatic probe plus the
cycle's own metrics. Version tagged. A dimension that could not be measured is
None and stays None — never zero, because a sensor that could not be read must
not look like a sensor that read zero.

THE 25th DIMENSION WAS NOT MISSING. IT WAS MISSPELLED.
--------------------------------------------------------
COMMAND 21 shipped VECTOR_FIELDS containing `event_log_errors` while the sensor
emits `event_log_errors_24h`. The lookup silently returned None and the report
said "24 of 25 dims measured", which read as a hardware limitation and was
nothing of the kind — the Windows Event Log was being read correctly the whole
time and thrown away on a name.

That is the exact failure CLAUDE.md names: a consumer that defaults on a key
mismatch instead of refusing. Fixed here by matching the sensor's name, and
guarded by assert_fields_resolve(), which fails loudly if any field ever again
has no sensor behind it. No migration is needed: the vector store did not exist,
so nothing was ever fitted from the broken vector.

TWENTY CYCLES BEFORE THE FIRST GLYPH
--------------------------------------
k-means over four points invents four clusters and names them; that is not a
language, it is a coincidence with Greek letters. Until MIN_CYCLES vectors exist
the expression window shows the RAW VECTOR SUMMARY, labelled

    lexicon warming: N/20 cycles

and no glyph is produced. Not a placeholder glyph, not Δ0 as a default — the
absence is displayed as an absence. A STATUS line cannot be emitted while warming
because the grammar requires exactly one glyph and there is none to give.

    venv/Scripts/python.exe -m cockpit.vector --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import lexicon as lx           # noqa: E402
from cockpit import somatic as som          # noqa: E402

# Vectors are appended here, one per completed cycle.
STORE = BASE / "memory" / "state_vectors.jsonl"

# Below this, there is no lexicon. See the module docstring.
MIN_CYCLES = 20

# The cycle-side dimensions. They arrive from the cycle's own metrics rather
# than from hardware, and they are named here so the vector's provenance is
# readable in one place.
# FIVE ORTHOGONAL SCALARS, 27 Aug 2026. flow_score was here, and it was a
# completeness ratio MULTIPLIED BY a speed — so the learning trace could not
# separate "did less work" from "took longer", and any lexicon fitted on it
# would have clustered the two together forever. Confounding is not a feature.
CYCLE_FIELDS = ("integrity_ratio", "degraded_ratio", "failed_ratio",
                "cloud_success_ratio", "pace_median_s",
                "steps_completed", "duration_sec")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_fields_resolve(probe: Optional[dict] = None) -> list:
    """VECTOR_FIELDS with no sensor behind them. Empty list is the contract.

    Exists because the 25th dimension spent a whole command reading None for a
    spelling reason while the report called it a hardware limitation.
    """
    p = probe if probe is not None else som.probe()
    keys = {row["key"] for rows in p.get("groups", {}).values() for row in rows}
    return [f for f in som.VECTOR_FIELDS if f not in keys]


def assemble(probe: Optional[dict] = None,
             cycle_metrics: Optional[dict] = None) -> dict:
    """One 25-dim vector. Missing dims are None, never 0.0."""
    p = probe if probe is not None else som.probe()
    v = som.state_vector(p)
    metrics = dict(cycle_metrics or {})
    return {
        "ts": _now(),
        "version": v["version"],
        "fields": v["fields"],
        "vector": v["vector"],
        "dims": v["dims"],
        "measured": v["measured"],
        "unresolved_fields": assert_fields_resolve(p),
        "cycle": {k: metrics.get(k) for k in CYCLE_FIELDS},
        "cycle_id": metrics.get("cycle_id"),
    }


def append(vector: dict, store_path: pathlib.Path) -> pathlib.Path:
    """Append one cycle-end vector. `store_path` is REQUIRED — no default."""
    p = pathlib.Path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(vector, ensure_ascii=False) + "\n")
    return p


def load(store_path: pathlib.Path, limit: int = 5000) -> list:
    """Stored vectors, oldest first. `store_path` is REQUIRED."""
    try:
        lines = pathlib.Path(store_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def warming(store_path: pathlib.Path) -> dict:
    """How far off a lexicon is. `store_path` is REQUIRED.

    `label` is what the expression window prints. It says N/20 while warming and
    never implies a glyph exists.
    """
    rows = load(store_path)
    n = len(rows)
    warm = n >= MIN_CYCLES
    return {
        "cycles": n,
        "needed": MIN_CYCLES,
        "warm": warm,
        "label": ("lexicon warm: {} cycles".format(n) if warm else
                  "lexicon warming: {}/{} cycles".format(n, MIN_CYCLES)),
        "why": (None if warm else
                "k-means over {} points would invent {} clusters and name them; "
                "that is a coincidence with Greek letters, not a language".format(
                    n, min(n, lx.SEED_K))),
    }


def usable_matrix(rows: list) -> tuple:
    """(matrix, kept_field_indices). Columns that are None anywhere are dropped.

    Dropping rather than imputing: a zero standing in for an unread sensor would
    become a cluster centre, and the glyph named after it would mean "the sensor
    we could not read", which is not a state of the world.
    """
    if not rows:
        return [], []
    dims = len(rows[0]["vector"])
    keep = [i for i in range(dims)
            if all(isinstance(r["vector"][i], (int, float))
                   and not isinstance(r["vector"][i], bool) for r in rows)]
    matrix = [[float(r["vector"][i]) for i in keep] for r in rows]
    return matrix, keep


def fit_if_warm(store_path: pathlib.Path, seed: int = 0):
    """A Lexicon, or None with the reason. `store_path` is REQUIRED."""
    state = warming(store_path)
    if not state["warm"]:
        return None, state
    rows = load(store_path)
    matrix, keep = usable_matrix(rows)
    if len(keep) < 2:
        return None, {**state, "warm": False,
                      "why": "only {} dimension(s) are complete across all "
                             "{} cycles".format(len(keep), len(rows))}
    return lx.fit(matrix, k=lx.SEED_K, seed=seed), state


def raw_summary(vector: dict, top: int = 6) -> str:
    """What the window shows INSTEAD of a glyph while warming.

    The largest-magnitude measured dimensions, named. It is a description of the
    reading, not a compression of it, and it is labelled as such so nobody reads
    it as a state name.
    """
    pairs = [(f, v) for f, v in zip(vector.get("fields", []),
                                    vector.get("vector", []))
             if isinstance(v, (int, float)) and not isinstance(v, bool)]
    pairs.sort(key=lambda kv: -abs(kv[1]))
    head = ", ".join("{}={}".format(k, round(v, 2)) for k, v in pairs[:top])
    return "{}/{} dims measured — {}".format(
        vector.get("measured"), vector.get("dims"), head)


def glyph_for(vector: dict, store_path: pathlib.Path, seed: int = 0) -> dict:
    """{glyph|None, label, warming}. NEVER fabricates a glyph."""
    lexicon, state = fit_if_warm(store_path, seed=seed)
    if lexicon is None:
        return {"glyph": None, "warming": state, "label": state["label"],
                "raw_summary": raw_summary(vector),
                "status_lines_possible": False,
                "why": "the grammar requires STATUS to carry exactly one glyph, "
                       "and there is no glyph yet"}
    rows = load(store_path)
    _, keep = usable_matrix(rows)
    point = [float(vector["vector"][i]) for i in keep]
    return {"glyph": lexicon.assign(point), "warming": state,
            "label": state["label"], "raw_summary": raw_summary(vector),
            "status_lines_possible": True,
            "silhouette": round(lexicon.silhouette, 4)}


def _selftest() -> int:
    print("cockpit/vector.py --selftest")
    unresolved = assert_fields_resolve()
    print("  fields with no sensor  {}".format(unresolved or "NONE — all 25 resolve"))

    v = assemble()
    print("  vector                 {} v{} — {}/{} measured".format(
        len(v["vector"]), v["version"], v["measured"], v["dims"]))
    print("  cycle dims             {}".format(list(v["cycle"])))

    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp()) / "vec.jsonl"
    print("  warming (empty store)  {}".format(warming(tmp)["label"]))
    for i in range(19):
        append({**v, "ts": "t{}".format(i)}, store_path=tmp)
    st = warming(tmp)
    print("  after 19 cycles        {} | warm={}".format(st["label"], st["warm"]))
    g = glyph_for(v, store_path=tmp)
    print("  glyph while warming    {}  (STATUS possible: {})".format(
        g["glyph"], g["status_lines_possible"]))
    print("  shown instead          {}".format(g["raw_summary"][:76]))
    append(v, store_path=tmp)
    st = warming(tmp)
    print("  after 20 cycles        {} | warm={}".format(st["label"], st["warm"]))
    lexicon, _ = fit_if_warm(tmp)
    print("  lexicon                {}".format(
        "k={}".format(lexicon.k) if lexicon else "still None"))
    print("  RESULT: OK")
    return 0 if not unresolved else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())

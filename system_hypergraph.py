#!/usr/bin/env python3
"""
system_hypergraph.py
Builds a hypergraph of the CORTEX++ system as RDF-style triples.

Triples generated:
  (agent, "follows", agent)  — execution order from _run() calls in fast_cycle_runner.py
  (agent, "writes",  file)   — from decisions.json / results.json in last 10 Merkle cycles
"""
import json
import re
import pathlib
from datetime import datetime, timezone

BASE    = pathlib.Path(__file__).resolve().parent
RUNNER  = BASE / "fast_cycle_runner.py"
ARCHIVE = BASE / "cortex_memory" / "archive"
OUT     = BASE / "data" / "cortex_hypergraph.json"


def _extract_run_agents() -> list[tuple[str, int]]:
    """Return [(label, line_no), ...] in execution order from _run() calls."""
    agents = []
    for lineno, line in enumerate(RUNNER.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r'\s+_run\(\s*"([^"]+)"', line)
        if m:
            agents.append((m.group(1), lineno))
    return agents


def _follows_triples(agents: list[tuple[str, int]]) -> list[dict]:
    """Sequential (agent, follows, agent) pairs."""
    triples = []
    for i in range(len(agents) - 1):
        triples.append({
            "subject":      agents[i][0],
            "predicate":    "follows",
            "object":       agents[i + 1][0],
            "subject_line": agents[i][1],
            "object_line":  agents[i + 1][1],
        })
    return triples


def _writes_triples(last_n: int = 10) -> list[dict]:
    """(agent, writes, file) triples from decisions.json and results.json."""
    triples = []
    if not ARCHIVE.exists():
        return triples

    cycle_dirs = sorted(ARCHIVE.glob("cycle_*"))[-last_n:]

    for cycle_dir in cycle_dirs:
        cycle_name = cycle_dir.name

        # ── decisions.json ────────────────────────────────────────────────────
        dec_path = cycle_dir / "decisions.json"
        if dec_path.exists():
            rel = f"cortex_memory/archive/{cycle_name}/decisions.json"
            try:
                data = json.loads(dec_path.read_text(encoding="utf-8"))
                decisions = data.get("decisions", [])
                if decisions:
                    for dec in decisions:
                        # prefer generated_by (set by openclaw/hyperclaw proposals)
                        agent = dec.get("generated_by") or dec.get("component") or "fast_cycle_runner"
                        triples.append({
                            "subject":   agent,
                            "predicate": "writes",
                            "object":    rel,
                            "cycle":     cycle_name,
                            "action":    dec.get("action") or dec.get("solution", ""),
                        })
                else:
                    # file written by MerkleMemory with no decisions this cycle
                    triples.append({
                        "subject":   "merkle_memory",
                        "predicate": "writes",
                        "object":    rel,
                        "cycle":     cycle_name,
                    })
            except Exception:
                pass

        # ── results.json ──────────────────────────────────────────────────────
        res_path = cycle_dir / "results.json"
        if res_path.exists():
            rel = f"cortex_memory/archive/{cycle_name}/results.json"
            try:
                data = json.loads(res_path.read_text(encoding="utf-8"))
                results = data.get("results", [])
                if results:
                    for res in results:
                        # patch verdict tells us which agent produced the result
                        agent = res.get("patch") or "execute_patches"
                        triples.append({
                            "subject":   agent,
                            "predicate": "writes",
                            "object":    rel,
                            "cycle":     cycle_name,
                            "verdict":   res.get("verdict"),
                            "goal_score": data.get("goal_score"),
                        })
                else:
                    triples.append({
                        "subject":   "execute_patches",
                        "predicate": "writes",
                        "object":    rel,
                        "cycle":     cycle_name,
                        "goal_score": data.get("goal_score"),
                    })
            except Exception:
                pass

    return triples


def build_hypergraph() -> dict:
    agents  = _extract_run_agents()
    follows = _follows_triples(agents)
    writes  = _writes_triples(last_n=10)

    # Compute per-node degree (how many follows triples touch this node)
    degree: dict[str, int] = {}
    for t in follows:
        degree[t["subject"]] = degree.get(t["subject"], 0) + 1
        degree[t["object"]]  = degree.get(t["object"],  0) + 1

    # Isolated = appear in writes but not in any follows triple
    follow_nodes = set(degree.keys())
    write_subjects = {t["subject"] for t in writes}
    isolated = sorted(write_subjects - follow_nodes)

    graph = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "source_file":   "fast_cycle_runner.py",
        "agents_order":  [{"agent": a, "line": ln} for a, ln in agents],
        "node_degree":   degree,
        "isolated_nodes": isolated,
        "triples_count": len(follows) + len(writes),
        "triples":       follows + writes,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[HYPERGRAPH] {len(agents)} agents | {len(follows)} follows | {len(writes)} writes | {len(isolated)} isolated")
    print(f"[HYPERGRAPH] -> {OUT}")
    return graph


def query_hypergraph(node: str) -> dict:
    """
    Return all triples touching `node` plus upstream/downstream summary.
    Safe to call even if the file doesn't exist yet.
    """
    if not OUT.exists():
        return {"error": "cortex_hypergraph.json not found — run build_hypergraph() first", "node": node}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e), "node": node}

    triples = data.get("triples", [])
    connected = [t for t in triples if t.get("subject") == node or t.get("object") == node]

    downstream = [t["object"]  for t in connected if t.get("subject") == node and t.get("predicate") == "follows"]
    upstream   = [t["subject"] for t in connected if t.get("object")  == node and t.get("predicate") == "follows"]
    writes_to  = [t["object"]  for t in connected if t.get("subject") == node and t.get("predicate") == "writes"]

    return {
        "node":              node,
        "degree":            len(connected),
        "upstream_agents":   upstream,
        "downstream_agents": downstream,
        "writes_to":         writes_to,
        "is_isolated":       len(connected) == 0,
        "sample_triples":    connected[:5],
    }


# backward-compat alias
build = build_hypergraph


if __name__ == "__main__":
    build_hypergraph()

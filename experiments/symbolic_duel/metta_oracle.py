"""
CORTEX++ | metta_oracle — the Hyperon/MeTTa sidecar as a callable duel partner
=============================================================================
ISOLATED, NON-INVASIVE, FAIL-OPEN — the cross_check.py discipline, one process
boundary further out.

WHY A SIDECAR
-------------
hyperon ships no wheel for the main venv's Python 3.14, so it cannot live beside
the rest of the system. Rather than hold the whole repo back a version, the engine
runs in its own 3.12 venv (venv312_metta) and is spoken to over stdin/stdout JSON.
The main venv gains a reasoning oracle and NOT a dependency: if the sidecar is
absent, broken, or slow, the caller gets ok=False and carries on.

NOT WIRED INTO THE CYCLE, deliberately. cross_check.py's audit (21 Jul 2026) still
stands: MeTTa earns its place only when cortex_scoring_engine.CORRELATION_MATRIX
becomes CONDITIONAL + MULTI-HOP — contradictions spanning >=3 axes needing a proof
trace. Until that threshold it stays a callable duel partner, invoked by hand.

  from experiments.symbolic_duel.metta_oracle import ask
  ask({"WATER_REVIEW": 2, "HUMAN_WELL_BEING_REVIEW": 1})

  venv/Scripts/python.exe experiments/symbolic_duel/metta_oracle.py   # self-test
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SIDECAR_PY = REPO / "venv312_metta" / "Scripts" / "python.exe"      # Windows
SIDECAR_PY_POSIX = REPO / "venv312_metta" / "bin" / "python"        # if ever on Linux
WORKER = Path(__file__).resolve().parent / "metta_oracle_worker.py"

DEFAULT_TIMEOUT = 60

# Seed rulebook, mirrored from metta_reason_live.py. (id, src, need, target, floor)
# in concern units 0=LOW..3=CRIT. This is a SEED, not the rulebook: it becomes real
# when grown out of cortex_scoring_engine.CORRELATION_MATRIX.
DEFAULT_RULES = [
    ("R1", "CLIMATE_GLOBAL_RISK_REVIEW", 2, "MATERIALS_WASTE_REVIEW", 2),
    ("R2", "CLIMATE_GLOBAL_RISK_REVIEW", 2, "FOOD_REVIEW", 2),
    ("R3", "FOOD_REVIEW", 2, "SOCIAL_RELATIONS_REVIEW", 2),
    ("R4", "INEQUALITY_POVERTY_REVIEW", 2, "SOCIAL_RELATIONS_REVIEW", 2),
    ("R5", "WATER_REVIEW", 2, "HUMAN_WELL_BEING_REVIEW", 2),
    ("R6", "ENERGY_REVIEW", 2, "PLANETARY_POTENTIAL_REVIEW", 2),
]


def sidecar_python():
    for p in (SIDECAR_PY, SIDECAR_PY_POSIX):
        if p.exists():
            return p
    return None


def ask(levels: dict, rules=None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Put a concern map to the MeTTa engine, get derived floors + proofs back.

    FAIL-OPEN in every direction: a missing sidecar, a crash, a timeout or garbage
    on the pipe all return ok=False with a named reason. Never raises, never blocks
    past `timeout`. The caller is expected to treat ok=False as "no opinion", which
    is why the reason is always stated — a silent empty answer would be
    indistinguishable from "the oracle found nothing wrong".
    """
    t0 = time.time()
    py = sidecar_python()
    if py is None:
        return {"ok": False, "error": f"sidecar venv not found at {SIDECAR_PY} — "
                                      f"run experiments/symbolic_duel/setup_sidecar.ps1",
                "latency_s": 0.0, "inconsistencies": []}
    if not WORKER.exists():
        return {"ok": False, "error": f"worker missing at {WORKER}",
                "latency_s": 0.0, "inconsistencies": []}

    payload = json.dumps({"levels": levels,
                          "rules": [list(r) for r in (rules or DEFAULT_RULES)]})
    try:
        proc = subprocess.run([str(py), str(WORKER)], input=payload, capture_output=True,
                              text=True, timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"sidecar timed out after {timeout}s",
                "latency_s": round(time.time() - t0, 3), "inconsistencies": []}
    except Exception as e:
        return {"ok": False, "error": f"sidecar launch failed: {type(e).__name__}: {e}",
                "latency_s": round(time.time() - t0, 3), "inconsistencies": []}

    lat = round(time.time() - t0, 3)
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"ok": False, "error": f"sidecar exit {proc.returncode}: "
                                      f"{(proc.stderr or '').strip()[:200]}",
                "latency_s": lat, "inconsistencies": []}
    try:
        out = json.loads(proc.stdout)
    except Exception as e:
        return {"ok": False, "error": f"unparseable sidecar answer ({type(e).__name__}): "
                                      f"{proc.stdout[:160]}",
                "latency_s": lat, "inconsistencies": []}
    out.setdefault("inconsistencies", [])
    out["latency_s"] = lat
    return out


def levels_from_scores(path=None) -> dict:
    """Live CORTEX scores -> concern levels, the same mapping metta_reason_live uses."""
    p = Path(path or (REPO / "output" / "cortex_scores_latest.json"))
    scores = json.loads(p.read_text(encoding="utf-8"))["scores"]

    def concern(s):
        if s is None:
            return None
        return 0 if s >= 0.75 else 1 if s >= 0.55 else 2 if s >= 0.35 else 3

    return {ax: concern(v.get("score")) for ax, v in scores.items()
            if v.get("score") is not None}


# ---- self-test (pre-declared pass/fail) -------------------------------------
# EXPECT: WATER at HIGH(2) fires R5 -> HUMAN_WELL_BEING floor HIGH(2) while it is
#         scored MOD(1)  => exactly one inconsistency, with a proof naming R5.
#         Control: the same map with WATER at LOW(0) => no inconsistency.
def _self_test() -> int:
    print(f"[metta_oracle] sidecar: {sidecar_python()}")

    case = {"WATER_REVIEW": 2, "HUMAN_WELL_BEING_REVIEW": 1}
    got = ask(case)
    print(f"[metta_oracle] ok={got.get('ok')} hyperon={got.get('hyperon_version')} "
          f"python={got.get('python')} latency={got.get('latency_s')}s")
    if not got.get("ok"):
        print(f"[metta_oracle] SELF-TEST FAIL — {got.get('error')}")
        return 1
    bad = got["inconsistencies"]
    for b in bad:
        print(f"  [!] {b['axis']}: scored {b['scored']} but rules imply >= {b['implied']}")
        for pr in b["proofs"]:
            print(f"      proof: {pr}")
    fired = len(bad) == 1 and bad[0]["axis"] == "HUMAN_WELL_BEING_REVIEW" \
        and any("R5" in p for p in bad[0]["proofs"])

    ctrl = ask({"WATER_REVIEW": 0, "HUMAN_WELL_BEING_REVIEW": 1})
    quiet = ctrl.get("ok") and not ctrl["inconsistencies"]
    print(f"[metta_oracle] control (WATER LOW): inconsistencies="
          f"{len(ctrl.get('inconsistencies', []))} latency={ctrl.get('latency_s')}s")

    fo = ask({"A": 1}, timeout=0)
    failopen = fo.get("ok") is False and "inconsistencies" in fo
    print(f"[metta_oracle] fail-open on timeout=0 -> ok={fo.get('ok')} "
          f"error={str(fo.get('error'))[:60]}")

    ok = fired and quiet and failopen
    print(f"[metta_oracle] SELF-TEST {'PASS' if ok else 'REVIEW'} "
          f"(rule fired={fired}, control quiet={quiet}, fail-open={failopen})")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--live" in sys.argv:
        lv = levels_from_scores()
        res = ask(lv)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0)
    sys.exit(_self_test())

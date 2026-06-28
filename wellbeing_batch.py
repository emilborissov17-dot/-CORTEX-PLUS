#!/usr/bin/env python3
"""
Phase 2b: batch WellbeingProfile for all ~215 WB sovereign countries.

Usage:
    python wellbeing_batch.py [--workers N] [--resume]

Output:
    output/wellbeing_all_countries.json
"""
from __future__ import annotations

import io, json, sys, time, contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE        = Path(__file__).parent
OUTPUT_FILE = BASE / "output" / "wellbeing_all_countries.json"
WB_API      = "https://api.worldbank.org/v2"
MAX_WORKERS = 8

ZONE_ORDER = ["In Crisis", "Precarious", "Secure", "Thriving", "Dignified Life",
              "UNKNOWN", "ERROR"]


# ── Country list ──────────────────────────────────────────────────────────────

def fetch_country_list() -> list[dict]:
    """Return all sovereign countries from WB (region.id != 'NA', ISO2 codes)."""
    r = requests.get(f"{WB_API}/country?format=json&per_page=300", timeout=30)
    r.raise_for_status()
    raw = r.json()[1]
    countries = []
    for c in raw:
        region = c.get("region", {}).get("id", "")
        iso2   = c.get("iso2Code", "")          # WB uses iso2Code, not id (id is 3-letter)
        if region != "NA" and len(iso2) == 2:
            countries.append({
                "iso2":   iso2,
                "name":   c.get("name", iso2),
                "region": region,
                "income": c.get("incomeLevel", {}).get("id", ""),
            })
    return countries


# ── Per-country runner (suppresses inner print noise) ────────────────────────

def _run_one(c: dict) -> dict:
    """Call country_wellbeing; return a lean summary dict."""
    from wellbeing_country import country_wellbeing
    iso2 = c["iso2"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):   # silence WB fetch prints
            result = country_wellbeing(iso2)
        p  = result["profile"]
        dq = result["data_quality"]
        return {
            "iso2":       iso2,
            "name":       c["name"],
            "region":     c["region"],
            "income":     c["income"],
            "zone":       p.zone,
            "deprivation":  round(p.deprivation,  3),
            "strain":       round(p.strain,       3),
            "flourishing":  round(p.flourishing,  3),
            "confidence":   dq["confidence"],
            "completeness": dq["summary"],
            "null_axes":    dq["null_axes"],
            "suspect_axes": [ax for ax, _ in dq["suspect_axes"]],
            "computed_at":  result["computed_at"],
            "status":       "ok",
        }
    except Exception as e:
        return {
            "iso2":       iso2,
            "name":       c["name"],
            "region":     c["region"],
            "income":     c["income"],
            "zone":       "ERROR",
            "confidence": "FAILED",
            "status":     f"error: {e}",
        }


# ── Batch run ─────────────────────────────────────────────────────────────────

def run_batch(countries: list[dict], resume: bool = False) -> list[dict]:
    """Run all countries with ThreadPoolExecutor; print live progress."""
    # Resume: skip already-computed
    done: dict[str, dict] = {}
    if resume and OUTPUT_FILE.exists():
        prev = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        done = {r["iso2"]: r for r in prev.get("countries", []) if r.get("status") == "ok"}
        print(f"[resume] {len(done)} countries already computed — skipping")

    todo = [c for c in countries if c["iso2"] not in done]
    total = len(todo)
    print(f"[batch] {total} countries to process  ({MAX_WORKERS} workers)\n")

    results: list[dict] = list(done.values())
    completed = len(done)
    errors    = 0
    t0        = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {pool.submit(_run_one, c): c for c in todo}
        for fut in as_completed(futs):
            completed += 1
            r = fut.result()
            results.append(r)

            elapsed = time.time() - t0
            rate    = (completed - len(done)) / max(elapsed, 1)
            remain  = (total - (completed - len(done))) / max(rate, 0.01)
            status  = "✓" if r["status"] == "ok" else "✗"
            conf    = r.get("confidence", "?")[:3]
            zone    = r.get("zone", "?")[:16]
            print(f"  {status} [{completed:3d}/{completed + total - (completed - len(done)):3d}]"
                  f"  {r['iso2']:<4}  {zone:<16}  {conf:<6}"
                  f"  elapsed {elapsed:5.0f}s  ~{remain:4.0f}s left")

            if r["status"] != "ok":
                errors += 1

            # Incremental save every 10 countries
            if completed % 10 == 0:
                _save(results)

    _save(results)
    print(f"\n[batch] done. {completed} total, {errors} errors, {time.time()-t0:.0f}s elapsed")
    return results


def _save(results: list[dict]) -> None:
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    out = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "total":       len(results),
        "countries":   sorted(results, key=lambda r: r.get("iso2", "")),
    }
    OUTPUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    ok = [r for r in results if r.get("status") == "ok"]

    # Zone distribution
    from collections import Counter
    zones = Counter(r["zone"] for r in ok)
    confs = Counter(r["confidence"] for r in ok)
    regs  = Counter(r["region"] for r in ok)

    print("\n" + "=" * 60)
    print("WELLBEING BATCH — SUMMARY")
    print("=" * 60)
    print(f"\nTotal countries processed : {len(results)}")
    print(f"  OK         : {len(ok)}")
    print(f"  Errors     : {len(results) - len(ok)}")

    print("\n── Zone distribution ──")
    for z in ZONE_ORDER:
        n = zones.get(z, 0)
        if n:
            bar = "█" * n
            pct = 100 * n / max(len(ok), 1)
            print(f"  {z:<20}  {n:>3}  ({pct:4.1f}%)  {bar}")

    print("\n── Confidence distribution ──")
    for lvl in ["HIGH", "MEDIUM", "LOW", "FAILED"]:
        n = confs.get(lvl, 0)
        if n:
            pct = 100 * n / max(len(ok), 1)
            icon = {"HIGH": "✅", "MEDIUM": "⚡", "LOW": "⚠️ ", "FAILED": "✗"}.get(lvl, "?")
            print(f"  {icon} {lvl:<8}  {n:>3}  ({pct:4.1f}%)")

    reliable = sum(1 for r in ok if r["confidence"] in ("HIGH", "MEDIUM"))
    low_conf = sum(1 for r in ok if r["confidence"] == "LOW")
    print(f"\n  Reliable (HIGH+MEDIUM) : {reliable}  ({100*reliable/max(len(ok),1):.1f}%)")
    print(f"  LOW CONFIDENCE         : {low_conf}  ({100*low_conf/max(len(ok),1):.1f}%)")
    print(f"  → Zone labels unreliable for {low_conf} countries")

    print("\n── Zones by confidence level ──")
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        subset = [r for r in ok if r["confidence"] == conf]
        if not subset:
            continue
        z_sub = Counter(r["zone"] for r in subset)
        parts = ", ".join(f"{z}: {n}" for z, n in sorted(z_sub.items(),
                          key=lambda x: ZONE_ORDER.index(x[0]) if x[0] in ZONE_ORDER else 99))
        print(f"  {conf:<8}: {parts}")

    print("\n── Suspect axes (most common) ──")
    from collections import Counter as C2
    all_suspect = []
    for r in ok:
        all_suspect.extend(r.get("suspect_axes", []))
    for ax, n in C2(all_suspect).most_common(6):
        print(f"  {n:>3}×  {ax}")

    print("\n── Lowest-scoring countries (deprivation) ──")
    worst_dep = sorted([r for r in ok if r.get("deprivation", -1) >= 0],
                       key=lambda r: -r["deprivation"])[:10]
    for r in worst_dep:
        print(f"  {r['iso2']:<4}  {r['name']:<30}  dep={r['deprivation']:.3f}"
              f"  {r['zone']:<16}  [{r['confidence']}]")

    print("\n── Highest-flourishing countries ──")
    best_flo = sorted([r for r in ok if r.get("flourishing", -1) >= 0],
                      key=lambda r: -r["flourishing"])[:10]
    for r in best_flo:
        print(f"  {r['iso2']:<4}  {r['name']:<30}  flo={r['flourishing']:.3f}"
              f"  {r['zone']:<16}  [{r['confidence']}]")

    print("=" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--resume",  action="store_true")
    args = ap.parse_args()
    MAX_WORKERS = args.workers

    print("[1/3] Fetching country list from World Bank API...")
    countries = fetch_country_list()
    print(f"      {len(countries)} sovereign countries found\n")

    print("[2/3] Running wellbeing profiles...")
    results = run_batch(countries, resume=args.resume)

    print("\n[3/3] Summary:")
    print_summary(results)

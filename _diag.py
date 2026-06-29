import json, sys
from collections import Counter
from pathlib import Path

BASE = Path(".")

# 1. improvement_proposals
p = json.loads((BASE/"memory"/"improvement_proposals.json").read_text(encoding="utf-8"))
proposals = p.get("proposals", [])
by_comp = Counter(x.get("component","?") for x in proposals)
by_gen  = Counter(x.get("generated_by","?") for x in proposals)
print(f"=== improvement_proposals: {len(proposals)} total ===")
for comp, cnt in by_comp.most_common(12):
    print(f"  {cnt:3d}x  {comp}")
print("  generators:", dict(by_gen))

# 2. web_intel
wi = json.loads((BASE/"memory"/"web_intelligence"/"latest.json").read_text(encoding="utf-8"))
print(f"\n=== web_intelligence ===")
print(f"  axes_covered: {wi['axes_covered']}")
print(f"  total_sources: {wi['total_sources']}")
print(f"  YT_videos: {wi['youtube_videos_total']}")
print(f"  critical_axes ({len(wi['critical_axes'])}):", wi["critical_axes"])

# 3. dependency_check
dep = json.loads((BASE/"snapshots"/"master"/"dependency_check_latest.json").read_text(encoding="utf-8"))
print(f"\n=== dependency_check ===")
print(f"  all_critical_ok: {dep['all_critical_ok']}")
for k, v in dep["checks"].items():
    print(f"  {k}: {v}")

# 4. media_seen transcript_status
ms = json.loads((BASE/"cortex_memory"/"media_seen.json").read_text(encoding="utf-8"))
ts = Counter(v.get("transcript_status","unknown") for v in ms.values())
ft = Counter(v.get("fallback_type","none") for v in ms.values())
print(f"\n=== media_seen: {len(ms)} entries ===")
print("  transcript_status:", dict(ts))
print("  fallback_type:    ", dict(ft))

# 5. cortex_strategist latest
oc_path = BASE/"snapshots"/"cortex_strategist"/"cortex_strategist_snapshot_latest.json"
if oc_path.exists():
    oc = json.loads(oc_path.read_text(encoding="utf-8"))
    print(f"\n=== cortex_strategist_snapshot ===")
    print(f"  system_health: {oc.get('system_health')}")
    print(f"  mission_alignment_pct: {oc.get('mission_alignment_pct')}")
    print(f"  critical_gaps ({len(oc.get('critical_gaps',[]))}):", oc.get("critical_gaps",[]))
    print(f"  immediate_actions ({len(oc.get('immediate_actions',[]))}):")
    for a in oc.get("immediate_actions", []):
        print(f"    - {a}")
else:
    print("\n=== cortex_strategist_snapshot: NOT FOUND ===")

# 6. recent plans
plan_dir = BASE/"plans"
if plan_dir.exists():
    plans = sorted(plan_dir.glob("plan-*.md"), key=lambda p: p.name, reverse=True)
    if plans:
        print(f"\n=== most recent plan: {plans[0].name} ===")
        print(plans[0].read_text(encoding="utf-8", errors="ignore")[:800])

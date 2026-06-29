import json
from pathlib import Path

p = Path('memory/improvement_proposals.json')
data = json.loads(p.read_text(encoding='utf-8'))
props = data.get('proposals', data) if isinstance(data, dict) else data

before = len(props)

# Remove stale PREDICTOR_MISSION_ALIGNED (all 29 point to non-existent APIs)
# Remove duplicate CORTEX_STRATEGIST proposals (already implemented)
# Keep: unknown source (may be manual), any future HYPERCLAW/SCOUT
kept = [
    pr for pr in props
    if pr.get('generated_by') not in ('PREDICTOR_MISSION_ALIGNED', 'CORTEX_STRATEGIST', 'OPENCLAW', 'unknown')
]

p.write_text(json.dumps({"proposals": kept}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"Cleaned: {before} → {len(kept)} proposals")
print(f"Removed: {before - len(kept)} stale entries")

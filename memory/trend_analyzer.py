#!/usr/bin/env python3
"""
memory/trend_analyzer.py
Анализира тенденции в snapshots-ите
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime
from typing import List, Dict

MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024  # a properly-truncated self-snapshot is a few KB; anything past 5MB is a bug

class TrendAnalyzer:
    def __init__(self):
        self.snapshots_dir = Path(__file__).parent.parent / "snapshots" / "self"

    def load_snapshots(self) -> List[Dict]:
        if not self.snapshots_dir.exists():
            return []
        snapshots = sorted(self.snapshots_dir.glob("*.json"))
        data = []
        for s in snapshots[-5:]:
            try:
                size = s.stat().st_size
                if size > MAX_SNAPSHOT_BYTES:
                    print(f"[TREND_ANALYZER] skipping {s.name}: {size/1024/1024:.1f}MB "
                          f"exceeds {MAX_SNAPSHOT_BYTES/1024/1024:.0f}MB sanity cap — not loading")
                    continue
                with open(s) as f:
                    data.append(json.load(f))
            except Exception as e:
                print(f"[TREND_ANALYZER] failed to load {s.name}: {type(e).__name__}: {e}")
        return data
    
    def analyze_memory_trend(self) -> Dict:
        data = self.load_snapshots()
        if len(data) < 2:
            return {"trend": "insufficient_data", "values": [], "change_percent": 0}
            
        mem_values = [d.get("resources_current", {}).get("memory_percent", 0) for d in data]
        timestamps = [d.get("timestamp", "") for d in data]
        
        trend = "stable"
        if mem_values and len(mem_values) > 1:
            if mem_values[-1] > mem_values[0] * 1.1:
                trend = "increasing"
            elif mem_values[-1] < mem_values[0] * 0.9:
                trend = "decreasing"
            
        return {
            "trend": trend,
            "values": mem_values,
            "timestamps": timestamps,
            "change_percent": round((mem_values[-1] - mem_values[0]) / mem_values[0] * 100, 2) if mem_values and mem_values[0] else 0
        }
    
    def predict_next(self) -> Dict:
        data = self.load_snapshots()
        if len(data) < 2:
            return {"prediction": "need_more_data"}
            
        mem_values = [d.get("resources_current", {}).get("memory_percent", 0) for d in data]
        avg_change = (mem_values[-1] - mem_values[0]) / len(mem_values)
        next_value = mem_values[-1] + avg_change
        
        return {
            "next_predicted_memory_percent": round(next_value, 2),
            "based_on": len(data),
            "trend": "up" if avg_change > 0 else "down"
        }

if __name__ == "__main__":
    ta = TrendAnalyzer()
    print("MEMORY TREND:", ta.analyze_memory_trend())
    print("PREDICTION:", ta.predict_next())

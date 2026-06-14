#!/usr/bin/env python3
"""
agents/self/self_awareness_agent.py
Агент, който следи и анализира самото AGI
"""

import json
from pathlib import Path
from datetime import datetime
from memory.self_awareness import SelfAwareness

class SelfAwarenessAgent:
    """Агент за самонаблюдение на AGI-то"""
    
    def __init__(self):
        self.self_awareness = SelfAwareness()
        self.snapshots_dir = Path(__file__).parents[2] / "snapshots" / "self"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        
    def run(self):
        """Основен цикъл на самонаблюдение"""
        current_state = self.self_awareness.to_dict()
        
        snapshot_file = self.snapshots_dir / f"self_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(snapshot_file, 'w') as f:
            json.dump(current_state, f, indent=2)
        
        improvements = self.suggest_improvements(current_state)
        self_level = current_state["self_assessment"]["level"]
        
        return {
            "snapshot": str(snapshot_file),
            "self_level": self_level,
            "improvements": improvements
        }
    
    def suggest_improvements(self, state):
        suggestions = []
        if state["resources_current"]["memory_percent"] > 80:
            suggestions.append({
                "type": "resource_optimization",
                "suggestion": "⚠️ Висока RAM употреба - оптимизирай кеширането",
                "priority": "HIGH"
            })
        return suggestions

if __name__ == "__main__":
    agent = SelfAwarenessAgent()
    result = agent.run()
    print(json.dumps(result, indent=2))

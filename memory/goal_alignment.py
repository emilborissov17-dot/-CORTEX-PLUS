#!/usr/bin/env python3
"""
memory/goal_alignment.py
Оценява колко добре AGI-то служи на CIVILIZATION_GOAL
"""

import json
from pathlib import Path
from typing import Dict, List

class GoalAlignment:
    def __init__(self):
        self.root = Path(__file__).parent.parent
        self.goal = self.load_goal()
        
    def load_goal(self):
        goal_file = self.root / "civilization_goal.txt"
        if goal_file.exists():
            return goal_file.read_text(encoding='utf-8')
        return "CIVILIZATION_GOAL not found"
    
    def assess_self_goal_connection(self, self_awareness):
        """Оценява дали AGI-то знае целта си"""
        if hasattr(self_awareness, 'goal'):
            return True
        return False

if __name__ == "__main__":
    ga = GoalAlignment()
    print(ga.goal[:100] + "...")

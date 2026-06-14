#!/usr/bin/env python3
"""
memory/self_modification_final.py
AGI може да променя собствения си код
"""

import os
import sys
from pathlib import Path
import shutil
import json
from datetime import datetime

class SelfModifier:
    """Позволява на AGI-то да променя себе си"""
    
    def __init__(self):
        self.root = Path(__file__).parent.parent
        self.backup_dir = self.root / "memory" / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.modification_log = self.root / "memory" / "modifications.json"
        
    def backup_current_state(self):
        """Прави backup на цялата система преди промяна"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"full_backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)
        
        # Копира важни файлове
        for file in ["self_awareness.py", "trend_analyzer.py", "goal_alignment.py"]:
            src = self.root / "memory" / file
            if src.exists():
                shutil.copy2(src, backup_path / file)
                
        return backup_path
    
    def suggest_self_improvement(self):
        """Предлага как да се подобри"""
        suggestions = []
        
        # Търси бавни функции
        with open(self.root / "memory" / "self_awareness.py") as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            if "for" in line and "range" in line and "append" in line:
                suggestions.append({
                    "file": "memory/self_awareness.py",
                    "line": i+1,
                    "issue": "Бавен цикъл",
                    "fix": "Използвай list comprehension",
                    "code": line.strip()
                })
                
        return suggestions
    
    def apply_fix(self, suggestion):
        """Прилага предложената промяна"""
        file_path = self.root / suggestion["file"]
        
        # Направи backup
        self.backup_current_state()
        
        # Прочети файла
        with open(file_path) as f:
            lines = f.readlines()
            
        # Направи промяна
        line_num = suggestion["line"] - 1
        old_line = lines[line_num]
        
        if "range" in old_line and "append" in old_line:
            # Пример: преобразува цикъл в list comprehension
            parts = old_line.split("for")
            new_line = f"{parts[0].replace('append', '')}[{parts[1]}\n"
            lines[line_num] = new_line
            
        # Запиши
        with open(file_path, 'w') as f:
            f.writelines(lines)
            
        # Логни промяната
        log = {
            "timestamp": datetime.now().isoformat(),
            "file": suggestion["file"],
            "line": suggestion["line"],
            "old": old_line.strip(),
            "new": new_line.strip()
        }
        
        if self.modification_log.exists():
            with open(self.modification_log) as f:
                logs = json.load(f)
        else:
            logs = []
            
        logs.append(log)
        
        with open(self.modification_log, 'w') as f:
            json.dump(logs, f, indent=2)
            
        return log
    
    def self_improve(self):
        """Автоматично подобряване"""
        print("🔍 Анализирам себе си...")
        suggestions = self.suggest_self_improvement()
        
        if not suggestions:
            print("✅ Няма нужда от подобрения!")
            return []
            
        print(f"📋 Намерени {len(suggestions)} възможни подобрения")
        
        applied = []
        for s in suggestions[:3]:  # Първите 3
            print(f"🛠️  Прилагам: {s['file']}:{s['line']} - {s['issue']}")
            result = self.apply_fix(s)
            applied.append(result)
            print(f"   ✅ Променено: {result['old']} → {result['new']}")
            
        return applied

if __name__ == "__main__":
    sm = SelfModifier()
    results = sm.self_improve()
    
    print("\n" + "="*50)
    print(f"✅ Направени {len(results)} подобрения")
    print("📝 Лог: memory/modifications.json")

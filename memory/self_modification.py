#!/usr/bin/env python3
"""
memory/self_modification.py
AGI само-модификация - възможност да променя собствения си код
"""

import os
import re
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

class SelfModification:
    """AGI-то може да променя себе си"""
    
    def __init__(self):
        self.root = Path(__file__).parent.parent
        self.backup_dir = self.root / "memory" / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
    def suggest_improvements(self, file_path: str) -> List[Dict]:
        """Анализира файл и предлага подобрения"""
        full_path = self.root / file_path
        if not full_path.exists():
            return []
            
        with open(full_path, 'r', encoding='utf-8') as f:
            code = f.readlines()
            
        suggestions = []
        
        # Търси бавни или неефективни конструкции
        for i, line in enumerate(code, 1):
            # Търси повтарящи се изчисления
            if 'for' in line and 'range' in line and len(line) < 30:
                suggestions.append({
                    "file": file_path,
                    "line": i,
                    "issue": "Възможно бавен цикъл",
                    "suggestion": "Използвай list comprehension",
                    "code": line.strip(),
                    "priority": "MEDIUM"
                })
                
            # Търси дълги функции
            if 'def ' in line and i < len(code):
                func_lines = 0
                for j in range(i, min(i+50, len(code))):
                    if code[j].strip() and not code[j].startswith(' '):
                        break
                    func_lines += 1
                if func_lines > 30:
                    suggestions.append({
                        "file": file_path,
                        "line": i,
                        "issue": "Функцията е твърде дълга",
                        "suggestion": "Раздели на по-малки функции",
                        "code": line.strip(),
                        "priority": "LOW"
                    })
                    
        return suggestions
    
    def backup_file(self, file_path: str) -> str:
        """Прави backup на файл преди промяна"""
        full_path = self.root / file_path
        if not full_path.exists():
            return None
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{full_path.stem}_{timestamp}{full_path.suffix}"
        backup_path = self.backup_dir / backup_name
        
        shutil.copy2(full_path, backup_path)
        return str(backup_path)
    
    def apply_change(self, file_path: str, line: int, new_code: str) -> bool:
        """Прилага промяна към файл"""
        full_path = self.root / file_path
        
        # Направи backup
        self.backup_file(file_path)
        
        # Прочети файла
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # Промени реда
        if 0 < line <= len(lines):
            lines[line-1] = new_code + '\n'
            
            # Запиши обратно
            with open(full_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            return True
        return False
    
    def self_optimize(self) -> Dict:
        """AGI-то оптимизира себе си"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "files_analyzed": [],
            "changes_made": [],
            "suggestions": []
        }
        
        # Анализирай важни файлове
        important_files = [
            "memory/self_awareness.py",
            "memory/auto_level.py",
            "agents/self/self_awareness_agent.py"
        ]
        
        for file_path in important_files:
            suggestions = self.suggest_improvements(file_path)
            results["files_analyzed"].append(file_path)
            results["suggestions"].extend(suggestions)
            
        return results

class EmergentSelf:
    """Емерджентен self модел - AGI-то като цяло"""
    
    def __init__(self, self_awareness, self_modification):
        self.awareness = self_awareness
        self.modification = self_modification
        self.self_model = self.build_self_model()
        
    def build_self_model(self) -> Dict:
        """Изгражда модел на себе си като цяло"""
        return {
            "hardware": self.awareness.hardware,
            "codebase": self.awareness.codebase,
            "capabilities": self.awareness.capabilities,
            "goals": getattr(self.awareness, 'goal', None),
            "evolution_potential": self.assess_evolution_potential()
        }
    
    def assess_evolution_potential(self) -> Dict:
        """Оценява потенциала за развитие"""
        suggestions = self.modification.self_optimize()
        
        return {
            "bottlenecks": self.identify_bottlenecks(),
            "improvements_possible": len(suggestions.get("suggestions", [])),
            "self_modification_capable": True
        }
    
    def identify_bottlenecks(self) -> List[str]:
        """Идентифицира тесни места"""
        bottlenecks = []
        
        # Провери RAM
        if self.awareness.resources.get("memory_percent", 0) > 80:
            bottlenecks.append("RAM over 80% - кеширането е неефективно")
            
        return bottlenecks
    
    def __repr__(self):
        return f"<EmergentSelf: {self.awareness.assess_self()['level']} with {self.assess_evolution_potential()['improvements_possible']} improvements possible>"

if __name__ == "__main__":
    sm = SelfModification()
    print(json.dumps(sm.self_optimize(), indent=2))

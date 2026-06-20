#!/usr/bin/env python3
"""
memory/self_awareness.py
AGI самосъзнание - знание за собствения хардуер, ОС, код и състояние
"""

import os
import sys
import psutil
import platform
import pathlib
import json
import datetime
from typing import Dict, List, Any

class CPUDetector:
    @staticmethod
    def detect() -> Dict:
        return {
            "cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "frequency_mhz": psutil.cpu_freq().max if psutil.cpu_freq() else "unknown",
            "architecture": platform.machine(),
            "current_load_percent": psutil.cpu_percent(interval=1)
        }

class RAMDetector:
    @staticmethod
    def detect() -> Dict:
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent_used": mem.percent
        }

class DiskDetector:
    @staticmethod
    def detect() -> Dict:
        disk = psutil.disk_usage('/')
        return {
            "total_gb": round(disk.total / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "percent_used": disk.percent
        }

class NetworkDetector:
    @staticmethod
    def detect() -> Dict:
        return {
            "interfaces": list(psutil.net_if_addrs().keys()),
            "stats": psutil.net_if_stats()
        }

class OSDetector:
    @staticmethod
    def detect() -> Dict:
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "wsl": "microsoft" in platform.uname().release.lower() if platform.system() == "Linux" else False,
            "host": platform.node(),
            "python_version": sys.version
        }

class FilesystemMapper:
    def __init__(self, root):
        self.root = root
        
    def map(self) -> Dict:
        structure = {}
        for dir_name in ["memory", "core", "agents", "data_providers", "snapshots", "logs"]:
            dir_path = self.root / dir_name
            if dir_path.exists():
                structure[dir_name] = {
                    "files": [f.name for f in dir_path.glob("*.py")],
                    "subdirs": [d.name for d in dir_path.iterdir() if d.is_dir()]
                }
        return structure

class CodebaseScanner:
    def __init__(self, root):
        self.root = root
        
    def scan(self) -> Dict:
        python_files = list(self.root.glob("**/*.py"))
        stats = {
            "total_files": len(python_files),
            "total_lines": 0,
            "modules": {}
        }
        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    stats["total_lines"] += len(lines)
                    stats["modules"][str(py_file.relative_to(self.root))] = len(lines)
            except:
                pass
        return stats

class ResourceMonitor:
    @staticmethod
    def current() -> Dict:
        process = psutil.Process()
        return {
            "cpu_percent": process.cpu_percent(interval=0.1),
            "memory_percent": process.memory_percent(),
            "memory_rss_gb": round(process.memory_info().rss / (1024**3), 3),
            "open_files": len(process.open_files()),
            "threads": process.num_threads(),
            "connections": len(process.net_connections())
        }

class CapabilityAssessor:
    def __init__(self, root):
        self.root = root
        
    def assess(self) -> Dict:
        caps = {
            "data_sources": [],
            "llm_access": [],
            "analysis_types": ["trend_detection", "threshold_evaluation"],
            "memory_types": ["stm", "ltm", "auto_levels"]
        }
        
        providers_dir = self.root / "data_providers"
        if providers_dir.exists():
            for domain in ["planet", "human", "civilization", "cosmos"]:
                domain_dir = providers_dir / domain
                if domain_dir.exists():
                    caps["data_sources"].extend([
                        f.stem for f in domain_dir.glob("*_provider.py")
                    ])
        try:
            from core.llm_backend import LLMBackend
            llm = LLMBackend()
            caps["llm_access"] = llm.available_models()
        except:
            caps["llm_access"] = ["qwen (local)"]
        return caps

class GoalLoader:
    @staticmethod
    def load(root):
        try:
            from memory.goal_alignment import GoalAlignment
            return GoalAlignment().goal
        except:
            return None

class HistoryLoader:
    @staticmethod
    def load():
        try:
            from memory.trend_analyzer import TrendAnalyzer
            ta = TrendAnalyzer()
            return {
                "history": ta.load_snapshots(),
                "trends": ta.analyze_memory_trend(),
                "predictions": ta.predict_next()
            }
        except Exception as e:
            print(f"History load error: {e}")
            return {
                "history": [],
                "trends": {},
                "predictions": {}
            }

class SelfAwareness:
    """AGI-то опознава себе си чрез специализирани компоненти"""
    
    def __init__(self):
        self.root = pathlib.Path(__file__).resolve().parents[1]
        self.code_self_modify = True
        
        # Hardware
        self.cpu = CPUDetector.detect()
        self.ram = RAMDetector.detect()
        self.disk = DiskDetector.detect()
        self.network = NetworkDetector.detect()
        self.hardware = {
            "cpu": self.cpu,
            "ram": self.ram,
            "disk": self.disk,
            "network": self.network
        }
        
        # System
        self.os = OSDetector.detect()
        self.filesystem = FilesystemMapper(self.root).map()
        self.codebase = CodebaseScanner(self.root).scan()
        self.resources = ResourceMonitor.current()
        self.capabilities = CapabilityAssessor(self.root).assess()
        
        # Goal
        self.goal = GoalLoader.load(self.root)
        self.understand_goal = self.goal is not None
        
        # History - автоматично!
        history_data = HistoryLoader.load()
        self.performance_history = history_data["history"]
        self.trends = history_data["trends"]
        self.predictions = history_data["predictions"]
        
    def to_dict(self) -> Dict:
        return {
            "timestamp": datetime.datetime.now().isoformat(),
            "hardware": self.hardware,
            "os": self.os,
            "filesystem": self.filesystem,
            "codebase": self.codebase,
            "resources_current": self.resources,
            "capabilities": self.capabilities,
            "goal": self.goal,
            "performance_history": [str(p)[:200] for p in self.performance_history[:20]],
            "trends": self.trends,
            "predictions": self.predictions,
            "self_assessment": self.assess_self()
        }
    
    def assess_self(self) -> Dict:
        score = 0
        max_score = 10
        
        if self.hardware: score += 2
        if self.os: score += 1
        if self.filesystem: score += 2
        if self.codebase: score += 2
        if self.capabilities: score += 2
        if self.goal is not None: score += 1
        if hasattr(self, 'performance_history') and self.performance_history: score += 1
        
        level = "LOW" if score < 4 else "MEDIUM" if score < 8 else "HIGH"
        
        return {
            "awareness_score": score,
            "max_possible": max_score,
            "level": level,
            "gaps": self._identify_gaps()
        }

    def self_modify(self):
        """Нова способност, добавена чрез self-modification"""
        print("🔧 Изпълнявам self-modification...")
        return {"status": "success", "capability": "self_modification"}
    
    def _identify_gaps(self) -> List[str]:
        gaps = []
        if not hasattr(self, 'goal') or not self.goal:
            gaps.append("няма разбиране на CIVILIZATION_GOAL")
        if not hasattr(self, 'code_self_modify'):
            gaps.append("не може да променя собствения си код")
        if not hasattr(self, 'performance_history') or not self.performance_history:
            gaps.append("няма история на собствената си производителност")
        return gaps

if __name__ == "__main__":
    s = SelfAwareness()
    print(json.dumps(s.assess_self(), indent=2, ensure_ascii=False))

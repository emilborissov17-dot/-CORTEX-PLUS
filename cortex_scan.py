#!/usr/bin/env python3
"""
CORTEX++_QWEN Vulnerability Scanner
Run: python3 cortex_scan.py   (от root на CORTEX++_QWEN)
"""

import ast
import json
from pathlib import Path

BASE_PATH = Path.cwd().resolve()
REPORT_FILE = BASE_PATH / "cortex_scan_report.json"

# Файлове, които често липсват / са критични за флоувете
MISSING_FILES = [
    "config_fresco_agent.json",
    "knowledge/energy_snapshots/energy_query_summary.json",
    "data/next_actions.json",
    "data/civilization_vision.json",
    "core/cortex4_v2.py",
    "cortex/agent_loop.py",
]

# Python файлове, в които вече сме имали syntax проблеми
SYNTAX_FILES = [
    "cortex/agent_loop.py",
    "cortex4_v2.py",
    "tools.py",
]

# Директории, които често липсват
PATH_DIRS = [
    "knowledge/energy_snapshots/",
    "core/",
    "knowledge/",
    "logs/",
]

# Модули, които може да липсват в средата
TEST_IMPORTS = ["cortex", "psutil", "ollama"]


def check_files():
    issues = []
    for rel in MISSING_FILES:
        p = BASE_PATH / rel
        if not p.exists():
            issues.append({
                "type": "MISSING_FILE",
                "path": str(p),
                "fix": f"Create {rel} или коригирай пътя в кода"
            })
    return issues


def check_syntax():
    issues = []
    for rel in SYNTAX_FILES:
        p = BASE_PATH / rel
        if p.exists():
            try:
                ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                issues.append({
                    "type": "SYNTAX_ERROR",
                    "file": rel,
                    "line": e.lineno,
                    "msg": str(e)
                })
    return issues


def check_dirs():
    issues = []
    for rel in PATH_DIRS:
        p = BASE_PATH / rel
        if not p.exists():
            issues.append({
                "type": "MISSING_DIR",
                "path": str(p),
                "fix": f"mkdir -p {rel}"
            })
    return issues


def check_imports():
    issues = []
    for mod in TEST_IMPORTS:
        try:
            __import__(mod)
        except ImportError:
            issues.append({
                "type": "MISSING_MODULE",
                "module": mod,
                "fix": f"pip install {mod} или премахни зависимостта ако не се ползва"
            })
    return issues


def ai_safety_checks():
    issues = []
    has_shutdown = False
    for p in BASE_PATH.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if "shutdown" in text or "off_switch" in text:
            has_shutdown = True
            break

    if not has_shutdown:
        issues.append({
            "type": "SAFETY_GAP",
            "issue": "No explicit shutdown/off-switch logic found",
            "fix": "Добави функция напр. def shutdown_agent(): sys.exit(0) и я извикай от контролното ядро при нужда"
        })

    return issues


def generate_report():
    report = {
        "scan_date": "2026-03-14",
        "base_path": str(BASE_PATH),
        "total_issues": 0,
        "issues": []
    }

    checks = [
        check_files,
        check_syntax,
        check_dirs,
        check_imports,
        ai_safety_checks,
    ]

    for check in checks:
        report["issues"].extend(check())

    report["total_issues"] = len(report["issues"])

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"SCAN COMPLETE: {report['total_issues']} issues found")
    print(f"Report: {REPORT_FILE}")

    if report["total_issues"] == 0:
        print("CORTEX++_QWEN: OK – no critical issues.")
    else:
        print("Top 5:")
        for i in report["issues"][:5]:
            loc = i.get("path") or i.get("file") or i.get("module")
            print(f"  - {i['type']} -> {loc}")


if __name__ == "__main__":
    generate_report()

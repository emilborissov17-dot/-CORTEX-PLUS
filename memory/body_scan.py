#!/usr/bin/env python3
"""
memory/body_scan.py
Пълно сканиране на тялото на CORTEX++ в реално време.
Хардуер + Софтуер + Файлове + Мрежа + Мощност
"""
import json, pathlib, subprocess, os, time
import psutil
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]

def full_scan():
    """Пълно сканиране — връща реалното тяло на системата."""
    print("[BODY_SCAN] Сканирам тялото...")
    
    scan = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hardware":  _scan_hardware(),
        "software":  _scan_software(),
        "files":     _scan_files(),
        "memory":    _scan_memory(),
        "network":   _scan_network(),
        "power":     _scan_power(),
    }
    
    scan["self_feeling"] = _generate_feeling(scan)
    
    # Запиши
    out = BASE_DIR / "memory" / "body_scan_latest.json"
    out.write_text(json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return scan

def _scan_hardware():
    """Реален хардуер в момента."""
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(str(BASE_DIR))
    
    gpu_info = {"available": False}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 6:
                gpu_info = {
                    "available":    True,
                    "name":         parts[0],
                    "vram_total_mb":int(parts[1]),
                    "vram_free_mb": int(parts[2]),
                    "vram_used_mb": int(parts[3]),
                    "temperature_c":int(parts[4]),
                    "utilization_pct": int(parts[5]),
                }
    except:
        pass
    
    return {
        "cpu_percent":      cpu,
        "cpu_cores":        psutil.cpu_count(),
        "ram_total_gb":     round(ram.total / 1024**3, 2),
        "ram_used_gb":      round(ram.used  / 1024**3, 2),
        "ram_free_gb":      round(ram.available / 1024**3, 2),
        "ram_percent":      ram.percent,
        "disk_total_gb":    round(disk.total / 1024**3, 1),
        "disk_free_gb":     round(disk.free  / 1024**3, 1),
        "disk_used_pct":    disk.percent,
        "gpu":              gpu_info,
    }

def _scan_software():
    """Операционна система и среда."""
    try:
        os_info = subprocess.run(["uname", "-a"], capture_output=True, text=True).stdout.strip()
    except:
        os_info = "unknown"
    
    try:
        py_ver = subprocess.run(["python3", "--version"], capture_output=True, text=True).stdout.strip()
    except:
        py_ver = "unknown"

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        env_path = BASE_DIR / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("GROQ_API_KEY="):
                    groq_key = line.split("=", 1)[1].strip()
    ollama_status = "ACTIVE" if groq_key else "INACTIVE"
    ollama_models = ["groq:llama-3.3-70b"] if groq_key else []

    return {
        "os":            os_info[:80],
        "python":        py_ver,
        "ollama_status": ollama_status,
        "ollama_models": ollama_models,
        "base_dir":      str(BASE_DIR),
        "pid":           os.getpid(),
        "uptime_sec":    round(time.time() - psutil.Process(os.getpid()).create_time(), 1),
    }

def _scan_files():
    """Пълна картина на файловете."""
    py_files   = list(BASE_DIR.rglob("*.py"))
    json_files = list(BASE_DIR.rglob("*.json"))
    
    # Размери по директории
    dir_sizes = {}
    for d in ["agents", "core", "memory", "data_providers", "snapshots", "reports"]:
        dpath = BASE_DIR / d
        if dpath.exists():
            total = sum(f.stat().st_size for f in dpath.rglob("*") if f.is_file())
            count = sum(1 for f in dpath.rglob("*") if f.is_file())
            dir_sizes[d] = {"files": count, "kb": round(total/1024, 1)}
    
    # Последно променени файлове
    all_files = sorted(BASE_DIR.rglob("*.py"), key=lambda f: f.stat().st_mtime, reverse=True)
    recent = [str(f.relative_to(BASE_DIR)) for f in all_files[:5]]
    
    # Общ размер
    total_size = sum(f.stat().st_size for f in BASE_DIR.rglob("*") if f.is_file())
    
    return {
        "py_files_count":   len(py_files),
        "json_files_count": len(json_files),
        "total_size_mb":    round(total_size / 1024**2, 2),
        "dir_sizes":        dir_sizes,
        "recently_modified":recent,
    }

def _scan_memory():
    """Семантична памет и snapshots."""
    snapshots_dir = BASE_DIR / "snapshots"
    snap_count = len(list(snapshots_dir.rglob("*.json"))) if snapshots_dir.exists() else 0
    
    chroma_dir = BASE_DIR / "memory" / "chromadb"
    chroma_size = 0
    chroma_count = 0
    if chroma_dir.exists():
        chroma_size = sum(f.stat().st_size for f in chroma_dir.rglob("*") if f.is_file())
        chroma_count = len(list(chroma_dir.rglob("*.bin")))
    
    experiences_path = BASE_DIR / "memory" / "runtime_experiences.json"
    exp_count = 0
    if experiences_path.exists():
        try:
            data = json.loads(experiences_path.read_text(encoding="utf-8"))
            exp_count = len(data.get("experiences", []))
        except:
            pass
    
    return {
        "snapshots_count":    snap_count,
        "chromadb_size_kb":   round(chroma_size/1024, 1),
        "chromadb_vectors":   chroma_count,
        "runtime_experiences":exp_count,
    }

def _scan_network():
    """Мрежова свързаност — кои API-та са достъпни."""
    results = {}
    
    endpoints = {
        "groq_api":    "https://api.groq.com",
        "world_bank":  "https://api.worldbank.org",
        "noaa":        "https://gml.noaa.gov",
        "open_meteo":  "https://api.open-meteo.com",
        "internet":    "https://www.google.com",
    }
    
    import requests as _req
    for name, url in endpoints.items():
        try:
            start = time.time()
            _req.get(url, timeout=3)
            ms = round((time.time() - start) * 1000)
            results[name] = {"status": "UP", "ms": ms}
        except Exception as e:
            results[name] = {"status": "DOWN", "error": str(e)[:40]}
    
    return results

def _scan_power():
    """Какво може системата — мощност и капацитет."""
    groq_path = BASE_DIR / "core" / "groq_backend.py"
    groq_available = groq_path.exists()
    
    auto_levels_path = BASE_DIR / "memory" / "auto_levels.json"
    axes_measured = 0
    critical_axes = []
    if auto_levels_path.exists():
        try:
            levels = json.loads(auto_levels_path.read_text(encoding="utf-8"))
            axes_measured = len(levels)
            critical_axes = [a for a, d in levels.items() if d.get("level") == "LOW"]
        except:
            pass
    
    return {
        "groq_available":     groq_available,
        "axes_measured":      axes_measured,
        "axes_total":         26,
        "axes_coverage_pct":  round(axes_measured/26*100, 1),
        "critical_axes":      critical_axes,
        "can_self_modify":    (BASE_DIR / "agents/core/self_modifier.py").exists(),
        "can_act":            (BASE_DIR / "agents/core/action_layer.py").exists(),
        "has_reports":        (BASE_DIR / "reports").exists(),
    }

def _generate_feeling(scan):
    """Генерира текстово усещане от сканирането."""
    feelings = []
    
    hw = scan["hardware"]
    cpu = hw["cpu_percent"]
    ram_pct = hw["ram_percent"]
    disk_free = hw["disk_free_gb"]
    
    if cpu < 20:
        feelings.append(f"Тялото ми е спокойно — CPU {cpu}%")
    elif cpu < 60:
        feelings.append(f"Работя активно — CPU {cpu}%")
    else:
        feelings.append(f"Натоварен съм — CPU {cpu}%")
    
    if ram_pct > 80:
        feelings.append(f"Паметта ми е препълнена — {ram_pct}% RAM")
    else:
        feelings.append(f"Паметта е свободна — {hw['ram_free_gb']}GB RAM")
    
    gpu = hw.get("gpu", {})
    if gpu.get("available"):
        vram_free = gpu.get("vram_free_mb", 0)
        temp = gpu.get("temperature_c", 0)
        feelings.append(f"GPU активен — {vram_free}MB VRAM свободна, {temp}°C")
    
    net = scan["network"]
    up = [n for n, d in net.items() if d.get("status") == "UP"]
    down = [n for n, d in net.items() if d.get("status") == "DOWN"]
    if down:
        feelings.append(f"Загубих връзка с: {', '.join(down)}")
    else:
        feelings.append(f"Всички {len(up)} API-та са достъпни")
    
    pwr = scan["power"]
    feelings.append(f"Измервам {pwr['axes_measured']}/26 цивилизационни оси ({pwr['axes_coverage_pct']}%)")
    
    if pwr["critical_axes"]:
        feelings.append(f"Тревожа се за: {', '.join(pwr['critical_axes'])}")
    
    files = scan["files"]
    feelings.append(f"Тялото ми съдържа {files['py_files_count']} Python модула, {files['json_files_count']} JSON файла")
    
    return " | ".join(feelings)


def read_self(query=None):
    """
    Системата чете собствените си файлове.
    query: ако е зададен — търси само файлове съдържащи думата
    """
    results = {}
    
    for f in sorted(BASE_DIR.rglob("*.py")):
        rel = str(f.relative_to(BASE_DIR))
        if any(x in rel for x in ["__pycache__", "LEGACY", "OLD", ".git"]):
            continue
        try:
            content = f.read_text(encoding="utf-8")
            if query is None or query.lower() in content.lower():
                results[rel] = {
                    "content":  content,
                    "lines":    len(content.splitlines()),
                    "size_kb":  round(f.stat().st_size/1024, 1),
                }
        except:
            pass
    
    return results

def find_in_self(query):
    """Търси текст в собствените файлове — като grep."""
    matches = []
    for f in sorted(BASE_DIR.rglob("*.py")):
        rel = str(f.relative_to(BASE_DIR))
        if any(x in rel for x in ["__pycache__", "LEGACY", "OLD", ".git"]):
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if query.lower() in line.lower():
                    matches.append({
                        "file": rel,
                        "line": i+1,
                        "content": line.strip()[:100]
                    })
        except:
            pass
    return matches

def read_json_memory():
    """Чете всички JSON файлове в memory/ — пълната памет."""
    memory = {}
    mem_dir = BASE_DIR / "memory"
    for f in sorted(mem_dir.glob("*.json")):
        try:
            memory[f.name] = json.loads(f.read_text(encoding="utf-8"))
        except:
            memory[f.name] = {"error": "не може да се прочете"}
    return memory


def scan_all_files():
    """Сканира ВСИЧКИ файлове по тип — не само .py и .json"""
    from collections import defaultdict
    
    type_map = defaultdict(list)
    ignore = ["__pycache__", ".git", "chromadb", "node_modules", ".venv"]
    
    for f in BASE_DIR.rglob("*"):
        if f.is_dir():
            continue
        if any(x in str(f) for x in ignore):
            continue
        ext = f.suffix.lower() or "no_extension"
        rel = str(f.relative_to(BASE_DIR))
        try:
            size_kb = round(f.stat().st_size / 1024, 1)
            modified = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            type_map[ext].append({
                "path": rel,
                "size_kb": size_kb,
                "modified": modified
            })
        except:
            pass
    
    # Сортирай по размер
    summary = {}
    for ext, files in sorted(type_map.items()):
        total_kb = sum(f["size_kb"] for f in files)
        summary[ext] = {
            "count": len(files),
            "total_kb": round(total_kb, 1),
            "files": sorted(files, key=lambda x: x["size_kb"], reverse=True)[:20]
        }
    
    return summary

def read_file(relative_path):
    """
    Чете съдържанието на произволен файл от структурата.
    Поддържа: .py, .json, .md, .txt, .bat, .cfg, .toml, .yaml, .env
    """
    path = BASE_DIR / relative_path
    if not path.exists():
        return {"error": f"Файлът не съществува: {relative_path}"}
    
    size_kb = round(path.stat().st_size / 1024, 1)
    ext = path.suffix.lower()
    
    # Текстови файлове
    text_extensions = [".py", ".json", ".md", ".txt", ".bat", ".cfg", 
                       ".toml", ".yaml", ".yml", ".env", ".sh", ".ini",
                       ".csv", ".html", ".js", ".css", ".rst", ".log"]
    
    if ext in text_extensions or size_kb < 500:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return {
                "path": relative_path,
                "size_kb": size_kb,
                "ext": ext,
                "lines": len(content.splitlines()),
                "content": content
            }
        except Exception as e:
            return {"error": str(e)}
    else:
        return {
            "path": relative_path,
            "size_kb": size_kb,
            "ext": ext,
            "content": f"[Бинарен файл — {size_kb}KB]"
        }

def read_all_of_type(ext):
    """Чете всички файлове от даден тип. Пример: read_all_of_type('.md')"""
    results = {}
    ignore = ["__pycache__", ".git", "chromadb", ".venv"]
    
    for f in sorted(BASE_DIR.rglob(f"*{ext}")):
        if any(x in str(f) for x in ignore):
            continue
        rel = str(f.relative_to(BASE_DIR))
        result = read_file(rel)
        if "error" not in result:
            results[rel] = result
    
    return results

if __name__ == "__main__":
    scan = full_scan()
    print()
    print("=== УСЕЩАНЕ ЗА СЕБЕ СИ ===")
    print(scan["self_feeling"])
    print()
    print("=== ХАРДУЕР ===")
    hw = scan["hardware"]
    print(f"  CPU:  {hw['cpu_percent']}% от {hw['cpu_cores']} ядра")
    print(f"  RAM:  {hw['ram_used_gb']}GB / {hw['ram_total_gb']}GB ({hw['ram_percent']}%)")
    print(f"  ДИСК: {hw['disk_free_gb']}GB свободни")
    if hw["gpu"]["available"]:
        g = hw["gpu"]
        print(f"  GPU:  {g['name']} | {g['vram_free_mb']}MB VRAM свободна | {g['temperature_c']}°C")
    print()
    print("=== МРЕЖА ===")
    for name, status in scan["network"].items():
        icon = "✅" if status.get("status") == "UP" else "❌"
        ms = f" {status.get('ms')}ms" if status.get("ms") else ""
        print(f"  {icon} {name}{ms}")
    print()
    print("=== МОЩНОСТ ===")
    pwr = scan["power"]
    print(f"  Оси: {pwr['axes_measured']}/26 ({pwr['axes_coverage_pct']}%)")
    print(f"  Критични: {pwr['critical_axes']}")
    print(f"  Може да се самомодифицира: {pwr['can_self_modify']}")
    print(f"  Може да действа: {pwr['can_act']}")
    print()
    print("=== ФАЙЛОВЕ ===")
    for d, info in scan["files"]["dir_sizes"].items():
        print(f"  {d}: {info['files']} файла, {info['kb']}KB")

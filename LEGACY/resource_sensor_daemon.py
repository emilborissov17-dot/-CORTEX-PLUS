import subprocess
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path("/mnt/c/Users/emilb/Desktop/AGI/CORTEX++")

LOG_FILE = BASE_DIR / "logs" / "resource_sensor_daemon.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Колко секунди да чака между пълни цикли на query-тата (напр. 3600 = 1 час)
SLEEP_BETWEEN_CYCLES = 3600


def log(msg: str):
    ts = datetime.utcnow().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_script(label: str, script_name: str):
    """
    Пуска един от *query_all.py скриптовете като отделен процес.
    """
    script_path = BASE_DIR / script_name
    if not script_path.exists():
        log(f"{label}: script not found: {script_path}")
        return

    log(f"{label}: START {script_name}")
    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        log(f"{label}: RETURN CODE {result.returncode}")
        if result.stdout:
            log(f"{label}: STDOUT:\n{result.stdout.strip()}")
        if result.stderr:
            log(f"{label}: STDERR:\n{result.stderr.strip()}")
    except Exception as e:
        log(f"{label}: EXCEPTION: {repr(e)}")


def one_cycle():
    """
    Един пълен цикъл през всички PLANET домейни.
    """
    log("=== RESOURCE_SENSOR: BEGIN CYCLE ===")

    run_script("ENERGY_QUERY", "energy_query_all.py")
    run_script("WATER_QUERY", "water_query_all.py")
    run_script("FOOD_QUERY", "food_query_all.py")
    run_script("MATERIALS_QUERY", "materials_query_all.py")

    log("=== RESOURCE_SENSOR: END CYCLE ===")


def main():
    log("RESOURCE_SENSOR_DAEMON: started")
    while True:
        start_ts = datetime.utcnow().isoformat()
        log(f"RESOURCE_SENSOR_DAEMON: cycle start at {start_ts}")

        one_cycle()

        log(f"RESOURCE_SENSOR_DAEMON: sleeping {SLEEP_BETWEEN_CYCLES} seconds...")
        try:
            time.sleep(SLEEP_BETWEEN_CYCLES)
        except KeyboardInterrupt:
            log("RESOURCE_SENSOR_DAEMON: interrupted by KeyboardInterrupt, exiting.")
            break


if __name__ == "__main__":
    main()

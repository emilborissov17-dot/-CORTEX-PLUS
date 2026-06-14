from __future__ import annotations
from pathlib import Path
import subprocess

BASE_DIR = Path(__file__).resolve().parent
REQ_DIR = BASE_DIR / "internet_requests"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def download_csv(url: str, target_path: Path) -> None:
    """
    Сваля CSV файл чрез curl (или друг инструмент, ако нямаш curl).
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Опит с curl (Windows 10+ обичайно има curl в PATH).
    cmd = ["curl", "-L", "-s", "-S", url, "-o", str(target_path)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"curl failed for {url} -> {target_path}:\n{result.stderr.strip()}"
        )


def process_request_file(req_path: Path) -> None:
    """
    Чете един файл (например internet_requests/energy.txt),
    сваля PENDING заявки и ги маркира като DONE.
    """
    lines = req_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Очакван формат:
        # STATUS | TYPE | DOMAIN | URL | NOTE
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 5:
            new_lines.append(line)
            continue

        status, req_type, domain, url, note = parts[0], parts[1], parts[2], parts[3], parts[4]

        # Ако не е PENDING, оставяме каквото е.
        if status.upper() != "PENDING":
            new_lines.append(line)
            continue

        if req_type == "OWID_CSV":
            # Име на файл от URL-а (грапher/...csv)
            filename = url.rsplit("/", 1)[-1]
            target_dir = DATA_DIR / domain
            target_path = target_dir / filename

            try:
                print(f"[INFO] Downloading {url} -> {target_path}")
                download_csv(url, target_path)
                # Маркираме като DONE
                new_line = f"DONE | {req_type} | {domain} | {url} | {note}"
                new_lines.append(new_line)
            except Exception as e:
                print(f"[ERROR] Failed to download {url}: {e}")
                # Оставяме реда като PENDING, за да може да опитаме по-късно.
                new_lines.append(line)
        else:
            # Неподдържан тип – оставяме го.
            new_lines.append(line)

    req_path.write_text("\n".join(new_lines), encoding="utf-8")


def main() -> None:
    if not REQ_DIR.exists():
        print(f"[WARN] No internet_requests directory at {REQ_DIR}")
        return

    for req_file in REQ_DIR.glob("*.txt"):
        print(f"[INFO] Processing {req_file.name}")
        process_request_file(req_file)


if __name__ == "__main__":
    main()

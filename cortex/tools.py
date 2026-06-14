from pathlib import Path
import subprocess
from typing import List, Dict, Any

from . import memory

ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = ROOT  # bazova direktoriya za read/write operatsii


# =========================
# FILE IO SKILLS
# =========================

def read_file(path: str) -> str:
    """
    Chet e fail otnositelno spryamo BASE_DIR.
    Vryshta prazen niz, ako failyt ne syshtestvuva ili ima greshka pri chetene.
    """
    full = BASE_DIR / path
    if not full.exists():
        return ""
    try:
        return full.read_text(encoding="utf-8")
    except Exception:
        return ""


def write_file(path: str, content: str) -> None:
    """
    Zapisva sydyrzhanie vuv fail (overwrite).
    Syzdava mezhdinnite direktorii pri nuzhda.
    """
    full = BASE_DIR / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def append_file(path: str, line: str) -> None:
    """
    Dobavya edin red kum fail.
    Syzdava mezhdinnite direktorii pri nuzhda.
    """
    full = BASE_DIR / path
    full.parent.mkdir(parents=True, exist_ok=True)
    with full.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# =========================
# SHELL / SYSTEM SKILLS
# =========================

def shell(cmd: str, timeout: int = 30) -> str:
    """
    Izpylnyava shell komanda s timeout.
    Vryshta stdout (i stderr, ako ima) kato tekst.
    """
    try:
        out = subprocess.check_output(
            cmd,
            shell=True,
            timeout=timeout,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return out
    except subprocess.CalledProcessError as e:
        return e.output
    except Exception as e:
        return f"Shell error: {e}"


# =========================
# MESSAGES / LOGS
# =========================

def send(msg: str) -> None:
    """
    Izprashta syobshtenie kum choveka chrez log i konzola.
    """
    append_file("logs/send.log", msg)
    print(msg)


# =========================
# WEB SEARCH (STUB)
# =========================

def search_web_stub(query_str: str) -> str:
    """
    STUB za web search.
    """
    return f"[search stub] You asked me to search for: {query_str}"


# =========================
# MEMORY SKILLS
# =========================

def remember_text(text: str) -> None:
    """
    Dobavya tekst v dylgostrochnata pamet (LTM + STM).
    """
    memory.remember(text)


def query_memory(text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Tyrsi v dylgostrochnata pamet i vryshta do `limit` naj-relevantni spomena.
    """
    return memory.query(text, limit=limit)


# =========================
# HUMAN-READABLE SKILLS DOC
# =========================

SKILLS_DOC = """
Available skills / tools inside CORTEX++:

- remember <string>
  Store an important fact or insight in long-term memory.

- query <string>
  Query long-term memory for relevant skills, facts, and past decisions.

- shell <command>
  Execute a shell command (with timeout). Use carefully and explain why.

- read-file <relative_path>
  Read a file (relative to the CORTEX++ base directory) into a string.

- write-file <relative_path> <string>
  Overwrite or create a file with the given string.

- append-file <relative_path> <string>
  Append a single line to the specified file.

- send <string>
  Send a message to the human (logged in logs/send.log and printed to console).

- search <string>
  Search the web (currently a stub); explain what you would look for and why.
""".strip()

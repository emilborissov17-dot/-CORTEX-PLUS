from pathlib import Path
import subprocess
from typing import List, Dict, Any

from . import memory

ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = ROOT  # ¢ óÖë  ¦·á¨ÆåÖá·Þ ó  read/write ÖØ¨á ¤··


# =========================
# «¡¾Ñ×ì¸ ×Ý©â¡¥¸¸ (IO SKILLS)
# =========================

def read_file(path: str) -> str:
    """
    ü¨å¨ ª ½Ð ÖåÔÖã·å¨ÐÔÖ ãØáÞÒÖ BASE_DIR.
    ìážù  Øá ó¨Ô Ô·ó,  ÆÖ ª ½Ðžå Ô¨ ãžù¨ãåëçë  ·Ð· ·Ò  ¬á¨õÆ  Øá· û¨å¨Ô¨.
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
    ô Ø·ãë  ãž¦žáé Ô·¨ ëžë ª ½Ð (overwrite).
    äžó¦ ë  Ò¨é¦·ÔÔ·å¨ ¦·á¨ÆåÖá·· Øá· Ôçé¦ .
    """
    full = BASE_DIR / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def append_file(path: str, line: str) -> None:
    """
    §Ö¢ ëÞ ¨¦·Ô á¨¦ ÆžÒ ª ½Ð.
    äžó¦ ë  Ò¨é¦·ÔÔ·å¨ ¦·á¨ÆåÖá·· Øá· Ôçé¦ .
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
    ¸óØžÐÔÞë  shell ÆÖÒ Ô¦  ã timeout.
    ìážù  stdout (· stderr,  ÆÖ ·Ò ) Æ åÖ å¨Æãå.
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
# äŸ×£ú©Õ¸à / Ñ×­×ì©
# =========================

def send(msg: str) -> None:
    """
    "¸óØá ù " ãžÖ¢ù¨Ô·¨ ÆžÒ ûÖë¨Æ  ûá¨ó ÐÖ¬ · ÆÖÔóÖÐ .
    ÝÖ-ÆžãÔÖ ÒÖé¨ ¦  ãå Ô¨ hook ÆžÒ ëžÔõ¨Ô ·Ôå¨áª¨½ã.
    """
    append_file("logs/send.log", msg)
    print(msg)


# =========================
# WEB SEARCH (STUB)
# =========================

def search_web_stub(query_str: str) -> str:
    """
    STUB ó  web search.
    ÝÖ-ÆžãÔÖ åçÆ ÒÖé¨ ¦  ó Æ û·Ò á¨ Ð¨Ô ·Ôå¨áÔ¨å  ¬¨Ôå.
    """
    return f"[search stub] You asked me to search for: {query_str}"


# =========================
# MEMORY SKILLS
# =========================

def remember_text(text: str) -> None:
    """
    §Ö¢ ëÞ å¨Æãå ë ¦žÐ¬ÖãáÖûÔ å  Ø Ò¨å (LTM + STM).
    ô  ë éÔ· ª Æå·, ·¦¨·, ØÐ ÔÖë¨.
    """
    memory.remember(text)


def query_memory(text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    æžáã· ë ¦žÐ¬ÖãáÖûÔ å  Ø Ò¨å · ëážù  ¦Ö `limit` Ô ½-á¨Ð¨ë ÔåÔ· ãØÖÒ¨Ô .
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

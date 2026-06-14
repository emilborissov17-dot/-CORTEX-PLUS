import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Базова структура:
# - STM: краткосрочна памет (без embedding, само последни записи).
# - LTM: дългосрочна памет (с embedding, за семантично търсене).
# - HIST: диалогова история (user/assistant), отделно от чистите "спомени".

ROOT = Path(__file__).resolve().parent.parent
MEM_DIR = ROOT / "knowledge" / "memory"
STM_FILE = MEM_DIR / "stm.jsonl"
LTM_FILE = MEM_DIR / "ltm.jsonl"
HIST_FILE = MEM_DIR / "history.jsonl"

# Лимити (можем да ги направим конфигурируеми по-късно)
MAX_MEMORY_CHARS = 2000
MAX_RECALL_ITEMS_DEFAULT = 10
MAX_HISTORY_CHARS = 5000


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def init_memory() -> None:
    """
    Инициализира структурата на паметта (директории и файлове).
    Вика се от основното ядро (напр. cortex4_v2.main()).
    """
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    for f in (STM_FILE, LTM_FILE, HIST_FILE):
        if not f.exists():
            f.write_text("", encoding="utf-8")


def _embed(text: str) -> List[float]:
    """
    TODO: по-късно ще закачим реален embedding (напр. Qwen).
    Засега връщаме фиктивен, но детерминиран псевдо-вектор,
    за да има стабилно семантично сравнение в рамките на системата.
    """
    base = sum(ord(c) for c in text) % 1000
    return [float((base + i * 13) % 100) for i in range(16)]


def _trim_file(path: Path, max_chars: int) -> None:
    """
    Ограничаваме размера на JSONL файла до последните max_chars символа.
    Това е проста защита от безконтролно разрастване.
    """
    data = path.read_text(encoding="utf-8")
    if len(data) <= max_chars:
        return
    path.write_text(data[-max_chars:], encoding="utf-8")


def remember(text: str) -> None:
    """
    Добавя нов "спомен" в краткосрочната и дългосрочната памет.

    Използване:
    - за важни факти/решения, които искаме системата да помни отвъд текущия диалог,
      напр. нови цели, промени в конфигурации, ключови изводи от анализ.
    """
    init_memory()
    ts = _now_iso()
    emb = _embed(text)

    stm_rec = {"ts": ts, "text": text}
    ltm_rec = {"ts": ts, "text": text, "embedding": emb}

    with STM_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stm_rec, ensure_ascii=False) + "\n")
    with LTM_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ltm_rec, ensure_ascii=False) + "\n")

    _trim_file(STM_FILE, MAX_MEMORY_CHARS)
    _trim_file(LTM_FILE, MAX_MEMORY_CHARS)


def _cosine(a: List[float], b: List[float]) -> float:
    import math
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def query(text: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Семантично търсене в дългосрочната памет.

    Връща top-N спомена като списък от:
    [{ "ts": ..., "text": ..., "score": ... }, ...]

    Параметри:
    - text: заявката (обикновено user message или извод от агент).
    - limit: максимален брой върнати записи (по подразбиране MAX_RECALL_ITEMS_DEFAULT).
    """
    init_memory()
    q_emb = _embed(text)
    n = limit if limit is not None else MAX_RECALL_ITEMS_DEFAULT

    items: List[Dict[str, Any]] = []
    if not LTM_FILE.exists():
        return items

    with LTM_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            score = _cosine(q_emb, rec.get("embedding") or [])
            items.append({"ts": rec.get("ts"), "text": rec.get("text", ""), "score": score})

    items.sort(key=lambda r: r["score"], reverse=True)
    return items[:n]


def add_to_history(user_msg: str, assistant_msg: str) -> None:
    """
    Добавя една стъпка от диалога (user + assistant) в историята.

    Това е отделно от "спомените" (remember), за да можем:
    - да държим чист лог на разговорите,
    - по-късно да правим summary/компресия върху историята и да я прехвърляме в LTM.
    """
    init_memory()
    ts = _now_iso()
    rec = {"ts": ts, "user": user_msg, "assistant": assistant_msg}
    with HIST_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _trim_file(HIST_FILE, MAX_HISTORY_CHARS)

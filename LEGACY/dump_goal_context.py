from pathlib import Path
import sys
from pathlib import Path as _Path

# добавяме кореновата папка CORTEX++ към sys.path
BASE_DIR = _Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from core import goals  # сега трябва да се вижда

text = goals.format_goal_context()
Path("goal_context_dump.txt").write_text(text, encoding="utf-8")

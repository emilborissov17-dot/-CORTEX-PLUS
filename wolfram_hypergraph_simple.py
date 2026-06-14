import os
import json
from wolframalpha import Client

# 1) Настройки
WOLFRAM_APP_ID = "235TLE6WHR"

# ВАЖНО: WSL път, не C:\...
BASE_DIR = "/mnt/c/Users/emilb/Desktop/AGI/CORTEX++_QWEN"
VISION_PATH = os.path.join(BASE_DIR, "civilization_vision.txt")
HGRAPH_PATH = os.path.join(BASE_DIR, "data", "cortex_hypergraph.json")

# 2) Чети визията
with open(VISION_PATH, "r", encoding="utf-8") as f:
    vision_text = f.read()

print("=== civilization_vision.txt (първи 600 знака) ===")
print(vision_text[:600], "...\n")

# 3) Заявка към Wolfram Alpha за sustainability triples
client = Client(WOLFRAM_APP_ID)

query = (
    "The following text is in Bulgarian. "
    "First, internally translate it to English. "
    "Then extract the main sustainability goals, values and constraints "
    "as triples in the format (subject, relation, object), one per line: "
    + vision_text
)

print("=== Пращам заявка към Wolfram Alpha... ===\n")
res = client.query(query)

triples_text = None
for pod in res.pods:
    if getattr(pod, "text", None):
        triples_text = pod.text
        break

if not triples_text:
    print("Няма получени triples от Wolfram Alpha.")
    raise SystemExit

print("=== Triples от Wolfram (първи 600 знака) ===")
print(triples_text[:600], "...\n")

# 4) Проста hypergraph структура в JSON
hyperedges = []

lines = [line.strip() for line in triples_text.split("\n") if line.strip()]

for line in lines:
    # очаква формата: (subject, relation, object)
    clean = line.replace("(", "").replace(")", "")
    parts = [p.strip() for p in clean.split(",")]
    if len(parts) != 3:
        print("SKIP (не е triple):", line)
        continue

    subj, rel, obj = parts

    edge = {
        "subject": subj,
        "relation": rel,
        "object": obj
    }
    hyperedges.append(edge)
    print("ADD EDGE:", edge)

print("\nОбщо edges:", len(hyperedges))
print("Записвам в:", HGRAPH_PATH)

os.makedirs(os.path.dirname(HGRAPH_PATH), exist_ok=True)
with open(HGRAPH_PATH, "w", encoding="utf-8") as f:
    json.dump({"edges": hyperedges}, f, ensure_ascii=False, indent=2)

print("Готово.")
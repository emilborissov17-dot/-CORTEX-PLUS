import os
import json
import requests

# 1) Настройки
WOLFRAM_APP_ID = "235TLE6WHR"

BASE_DIR = "/mnt/c/Users/emilb/Desktop/AGI/CORTEX++_QWEN"
VISION_PATH = os.path.join(BASE_DIR, "civilization_vision.txt")
HGRAPH_PATH = os.path.join(BASE_DIR, "data", "cortex_hypergraph.json")

API_URL = "https://api.wolframalpha.com/v2/query"

# 2) Чети визията
with open(VISION_PATH, "r", encoding="utf-8") as f:
    vision_text = f.read()

print("=== civilization_vision.txt (първи 600 знака) ===")
print(vision_text[:600], "...\n")

# 3) Подготовка на заявката към Wolfram Alpha
query = (
    "The following text is in Bulgarian. "
    "First, internally translate it to English. "
    "Then extract the main sustainability goals, values and constraints "
    "as triples in the format (subject, relation, object), one per line. "
    "Focus on civilization, AGI, sustainability, human values, safety: "
    + vision_text
)

# Параметри – НО ще ги пратим като POST body, за да не става URL-ът огромен
params = {
    "appid": WOLFRAM_APP_ID,
    "input": query,
    "output": "JSON"
}

print("=== Пращам HTTP POST заявка към Wolfram Alpha... ===\n")
# Използваме POST, body=form data, за да избегнем 414 Request-URI Too Large
resp = requests.post(API_URL, data=params, timeout=60)

print("HTTP status:", resp.status_code)
if resp.status_code != 200:
    print("Грешка от Wolfram Alpha HTTP:", resp.text[:500])
    raise SystemExit

data = resp.json()

# 4) Извличане на текст от pod-овете
pods = data.get("queryresult", {}).get("pods", [])

triples_text = None

for pod in pods:
    title = pod.get("title", "")
    # първо търсим Result / Results, после други
    if title.lower() in ["result", "results", "interpretation", "translated text"]:
        subpods = pod.get("subpods", [])
        if not subpods:
            continue
        first = subpods[0]
        triples_text = first.get("plaintext")
        if triples_text:
            break

# ако не намерим в Result, взимаме първия pod, който има plaintext
if not triples_text:
    for pod in pods:
        subpods = pod.get("subpods", [])
        if not subpods:
            continue
        first = subpods[0]
        txt = first.get("plaintext")
        if txt:
            triples_text = txt
            break

if not triples_text:
    print("Няма получени plaintext triples от Wolfram Alpha.")
    raise SystemExit

print("=== Raw plaintext от Wolfram (първи 600 знака) ===")
print(triples_text[:600], "...\n")

# 5) Проста hypergraph структура в JSON
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
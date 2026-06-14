#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

import requests

# === Настройки за Qwen / Ollama ===

# Тук е chat-completions API, което вече ползваш за Qwen.
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "qwen3:8b"

# === Пътища за файлове ===

BASEDIR = Path(__file__).resolve().parent
GOAL_PATH = BASEDIR / "civilization_goal.txt"
CANDIDATES_PATH = BASEDIR / "config" / "resource_sources_candidates.json"


def call_qwen(messages: List[Dict[str, str]]) -> str:
    """
    Извиква локалния Qwen модел през Ollama API
    и връща само текста на отговора.
    """
    data = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(OLLAMA_URL, headers=headers, data=json.dumps(data))
    resp.raise_for_status()
    j = resp.json()
    return j["choices"][0]["message"]["content"]


def load_global_goal() -> str:
    """
    Чете глобалната цел от civilization_goal.txt.
    """
    try:
        return GOAL_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return (
            "ГЛОБАЛНА ЦЕЛ: файл civilization_goal.txt липсва или не може да бъде прочетен. "
            "Действай максимално предпазливо."
        )


def describe_domain_for_sources(domain: str) -> str:
    """
    Връща кратко естественоезиково описание на домейна за discovery prompt-а.
    Можеш да го разшириш/редактираш по всяко време.
    """
    d = domain.lower()
    if d == "energy":
        return (
            "ЕНЕРГИЯ: производство, потребление, енергиен микс, възобновяеми източници, емисии, мощности, "
            "енергийна ефективност, глобални и регионални енергийни статистики."
        )
    elif d == "water":
        return (
            "ВОДА: наличност на вода, качество на водата, достъп на населението до питейна вода, "
            "водни ресурси, управление на водите, суши и наводнения, глобални и регионални водни показатели."
        )
    elif d == "food":
        return (
            "ХРАНА: производство на храни, земеделие, достъп до храна, хранителна сигурност и глад, "
            "калориен прием, хранителни режими, загуби и разхищение на храна."
        )
    else:
        # Общ fallback за други домейни от дървото
        return (
            f"{domain.upper()}: важни глобални и регионални open data / API източници, "
            "свързани с този домейн (официални институции, академични платформи, добре поддържани open data инициативи)."
        )


def parse_sources_from_qwen(text: str) -> List[Dict[str, Any]]:
    """
    Очакваме Qwen да върне списък от източници в прост текстов формат.

    Формат пример:

    - Name: ...
      URL: ...
      Docs: ...
      Notes: ...

    Може да има вариации в главни/малки букви.
    """
    sources: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # нов източник
        if line.startswith("- ") or line.startswith("* "):
            if current:
                sources.append(current)
                current = {}
            line = line[2:].strip()

        lower = line.lower()
        if lower.startswith("name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif lower.startswith("url:"):
            current["url"] = line.split(":", 1)[1].strip()
        elif lower.startswith("docs:"):
            current["docs"] = line.split(":", 1)[1].strip()
        elif lower.startswith("notes:") or lower.startswith("description:"):
            current["notes"] = line.split(":", 1)[1].strip()

    if current:
        sources.append(current)

    now_iso = datetime.utcnow().isoformat()
    for src in sources:
        src.setdefault("status", "candidate")
        src.setdefault("type", "dataset_or_api")
        src.setdefault("added_at", now_iso)

    return sources


def discover_sources_for_domain(domain: str) -> List[Dict[str, Any]]:
    """
    Общ SOURCE_DISCOVERY_AGENT:
    - Чете глобалната цел
    - Пита Qwen за важни open data / API източници за даден домейн
    - Парсира отговора в структурирани записи
    - Записва ги в config/resource_sources_candidates.json под ключа на домейна
    """
    global_goal = load_global_goal()
    domain_desc = describe_domain_for_sources(domain)

    system_prompt = (
        global_goal
        + "\n\n"
        "Ти си SOURCE_DISCOVERY_AGENT в системата CORTEX++. "
        "Твоята задача е да откриваш и каталогизираш важни източници на "
        "открити данни (open data) и API-та за конкретен домейн от глобалната цивилизация.\n\n"
        f"Текущ домейн: {domain.upper()}.\n"
        f"Описание на домейна: {domain_desc}\n\n"
        "Работиш КОНСЕРВАТИВНО: само създаваш структурирани записи за източници, "
        "НЕ правиш реални HTTP заявки и НЕ изпълняваш код.\n\n"
        "Искам да върнеш списък от 10-30 важни източници (datasets, APIs, портали), "
        "като за всеки включиш:\n"
        "- Name: кратко име\n"
        "- URL: основният линк към данните или API-то\n"
        "- Docs: линк към документация/описание, ако има\n"
        "- Notes: 1-2 изречения какви данни има и за кои региони/държави\n\n"
        "Връщай само списък в този текстов формат, без други коментари."
    )

    user_content = (
        "Нужни са ми най-важните източници за open data / APIs за този домейн, "
        "включително глобални и регионални платформи. "
        "Фокусирай се върху официални институции, академични платформи, "
        "и добре поддържани open data инициативи."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw_response = call_qwen(messages)
    sources = parse_sources_from_qwen(raw_response)

    # Зареждаме съществуващи кандидати (по домейни)
    existing: Dict[str, Any] = {}
    if CANDIDATES_PATH.exists():
        try:
            existing = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    if not isinstance(existing, dict):
        existing = {}

    domain_list = existing.get(domain, [])
    if not isinstance(domain_list, list):
        domain_list = []

    # Просто append – ти можеш по-късно да добавиш дедупликация
    domain_list.extend(sources)
    existing[domain] = domain_list

    CANDIDATES_PATH.parent.mkdir(exist_ok=True)
    CANDIDATES_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        required=True,
        help="Домейн от дървото (например energy, water, food, ...)",
    )
    args = parser.parse_args()

    domain = args.domain.strip().lower()

    # Без кирилица в конзолата, за да няма UnicodeEncodeError под Windows
    print(f"SOURCE_DISCOVERY_AGENT: start discovery for domain '{domain}'...")
    new_sources = discover_sources_for_domain(domain)
    print(
        f"SOURCE_DISCOVERY_AGENT: added {len(new_sources)} new candidates "
        f"for domain '{domain}' in {CANDIDATES_PATH.name}"
    )


if __name__ == "__main__":
    main()

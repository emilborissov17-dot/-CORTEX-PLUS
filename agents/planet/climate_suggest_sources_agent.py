#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
agents/planet/climate_suggest_sources_agent.py

Агент за CLIMATE_GLOBAL_RISK_REVIEW, който:
- прави web search по климатични ключови думи;
- извлича потенциални източници;
- попълва секцията "suggested_for_approval" в CONFIG_PLANET_DATA_SOURCES.md.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import requests

CONFIG_PATH = pathlib.Path(__file__).resolve().parents / "CONFIG_PLANET_DATA_SOURCES.md"


@dataclass
class SuggestedSource:
    id: str
    name: str
    url: str
    proposed_type: str  # "trusted_open" или "use_with_caution"
    short_description: str
    added_by: str = "CLIMATE_AGENT"
    added_at: str = datetime.utcnow().isoformat() + "Z"


def _search_web_sources() -> List[SuggestedSource]:
    """
    Тук поставяш реалната си web-search логика.
    За демонстрация: използваме статични примери, но структурата е такава,
    че да можеш да я замениш с LLM/duckduckgo/serpapi и т.н.
    """
    # TODO: замени това с реални резултати от търсене
    examples: List[SuggestedSource] = [
        SuggestedSource(
            id="ECMWF_CLIMATE_REANALYSIS",
            name="ECMWF Climate Reanalysis Overview",
            url="https://www.ecmwf.int/en/research/climate-reanalysis",
            proposed_type="trusted_open",
            short_description="Описание на климатичните реанализни продукти на ECMWF (ERA5 и др.)."
        ),
        SuggestedSource(
            id="CLIMATE_DATA_API_LIST",
            name="Overview of Climate Data APIs",
            url="https://continuuiti.com/blog/climate-data-api/",
            proposed_type="use_with_caution",
            short_description="Сравнение на различни climate data APIs (free и paid)."
        )
    ]
    return examples


def _extract_climate_json_block(text: str) -> Dict[str, Any]:
    pattern = r"## 1\. CLIMATE_GLOBAL_RISK_REVIEW.*?```json(.*?)```"
    m = re.search(pattern, text, flags=re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return {}


def _replace_climate_json_block(text: str, new_block: Dict[str, Any]) -> str:
    new_json_str = json.dumps(new_block, ensure_ascii=False, indent=2)
    pattern = r"(## 1\. CLIMATE_GLOBAL_RISK_REVIEW.*?```json)(.*?)(```)"
    repl = r"\1\n" + new_json_str + r"\n\3"
    return re.sub(pattern, repl, text, flags=re.DOTALL)


def update_climate_suggested_sources() -> None:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"CONFIG file not found at {CONFIG_PATH}")

    text = CONFIG_PATH.read_text(encoding="utf-8")
    block = _extract_climate_json_block(text)
    if not block:
        raise ValueError("Cannot find CLIMATE_GLOBAL_RISK_REVIEW JSON block in CONFIG.")

    suggested_list: List[Dict[str, Any]] = block.get("suggested_for_approval", [])
    seen_ids = {s.get("id") for s in suggested_list if isinstance(s, dict)}

    new_sources = _search_web_sources()
    for s in new_sources:
        if s.id in seen_ids:
            continue
        suggested_list.append({
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "proposed_type": s.proposed_type,
            "short_description": s.short_description,
            "added_by": s.added_by,
            "added_at": s.added_at,
        })
        seen_ids.add(s.id)

    block["suggested_for_approval"] = suggested_list
    new_text = _replace_climate_json_block(text, block)
    CONFIG_PATH.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    update_climate_suggested_sources()
    print("Updated CLIMATE_GLOBAL_RISK_REVIEW suggested_for_approval.")

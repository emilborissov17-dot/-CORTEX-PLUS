#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict
from data_providers.planet.base_provider import PlanetDataProvider

class PlanetaryPotentialProvider(PlanetDataProvider):
    axis = "PLANETARY_POTENTIAL_REVIEW"
    source_name = "composite_llm"
    def fetch(self) -> Dict[str, Any]:
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(),
                "notes": "Composite axis — aggregated from all other PLANET axes by LLM.",
                "data_quality": "llm_composite"}

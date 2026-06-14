#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data_providers/planet/base_provider.py

Базов интерфейс за PLANET data providers.
Всеки провайдър връща нормализиран суров dict, без LLM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class PlanetDataProvider(ABC):
    axis: str = ""
    source_name: str = ""

    @abstractmethod
    def fetch(self) -> Dict[str, Any]:
        """
        Връща суров нормализиран пакет данни за дадената ос.
        Форматът е свободен, но да е JSON-serializable dict.
        """
        raise NotImplementedError

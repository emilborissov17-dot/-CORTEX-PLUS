#!/usr/bin/env python3
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict

class CosmosDataProvider(ABC):
    axis: str = ""
    source_name: str = ""
    @abstractmethod
    def fetch(self) -> Dict[str, Any]:
        raise NotImplementedError

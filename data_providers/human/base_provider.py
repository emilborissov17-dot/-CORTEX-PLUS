#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict

class HumanDataProvider(ABC):
    axis: str = ""
    source_name: str = ""

    @abstractmethod
    def fetch(self) -> Dict[str, Any]:
        raise NotImplementedError

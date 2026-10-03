#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/llm_backend.py
call_internal_llm: the local model through core/local_llm (C-CLOUD-1, R45: no outside model).
call_ollama_fallback: the Ollama CLI directly.
"""
from __future__ import annotations
import subprocess, os
from pathlib import Path

MODEL_NAME   = "qwen3:1.7b"  # fallback
OLLAMA_TIMEOUT = 300

def call_ollama_fallback(prompt: str) -> str:
    r = subprocess.run(
        ["ollama", "run", MODEL_NAME],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=OLLAMA_TIMEOUT,
        check=False,
    )
    text = r.stdout.decode("utf-8", errors="ignore").strip()
    if "done thinking." in text:
        text = text.split("done thinking.")[-1].strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    return text

def call_internal_llm(prompt: str) -> str:
    """The local model via core/local_llm."""
    from core.local_llm import call_local_llm
    return call_local_llm(prompt, max_tokens=1024)

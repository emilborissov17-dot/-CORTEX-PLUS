#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/llm_backend.py
Primary: Groq API (llama-3.3-70b) — безплатно, бързо
Fallback: Ollama qwen3:1.7b — локално
"""
from __future__ import annotations
import subprocess, os
from pathlib import Path

MODEL_NAME   = "qwen3:1.7b"  # fallback
GROQ_TIMEOUT = 60
OLLAMA_TIMEOUT = 300

def call_groq_primary(prompt: str) -> str:
    from core.groq_backend import call_groq
    return call_groq(prompt, max_tokens=1024)

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
    """Groq → Gemini fallback via groq_backend. Ollama removed."""
    from core.groq_backend import call_groq
    return call_groq(prompt, max_tokens=1024)

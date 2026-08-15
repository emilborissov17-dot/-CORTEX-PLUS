#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/test_local_brain.py — ИСТИНСКИЯТ ТЕСТ НА ЛОКАЛНИЯ МОЗЪК (15 Aug 2026)

Написан, защото Клод тества веригата с УЛОВЕНИ отговори (от облака няма достъп до
localhost:11434) — а Емил иска реален тест. Този скрипт се изпълнява НА МАШИНАТА,
говори с истинската Ollama, върху истински файлове на системата, и записва суровия
резултат в memory/local_brain_test.json, за да го прочете и Клод, и човек.

Нищо не променя. Само пита, мери и записва.

  venv\\Scripts\\python.exe scripts\\test_local_brain.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
OUT = BASE / "memory" / "local_brain_test.json"


def _now():
    return datetime.now(timezone.utc).isoformat()


def main():
    rep = {"ts": _now(), "tests": []}

    # ── 0. Има ли изобщо локален мозък и какъв ───────────────────────────────
    try:
        import requests
        t0 = time.time()
        r = requests.get("http://localhost:11434/api/tags", timeout=10)
        models = [m.get("name") for m in (r.json().get("models") or [])]
        rep["ollama"] = {"reachable": r.ok, "models": models,
                         "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        rep["ollama"] = {"reachable": False, "error": f"{type(e).__name__}: {e}"}
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return

    # ── 0б. ЗАГРЯВАНЕ: първото повикване зарежда модела от диска ─────────────
    # 15 Aug: първият тест падна на 92.1s не защото мозъкът мълчи, а защото 8B
    # модел на 4GB VRAM се зарежда по-дълго от таймаута. Мери се МИСЛЕНЕ, не
    # събуждане — затова будим отделно и записваме колко е струвало.
    try:
        model0 = next((m for m in (rep["ollama"]["models"] or []) if "qwen3" in str(m)),
                      (rep["ollama"]["models"] or ["qwen3"])[0])
        t0 = time.time()
        requests.post("http://localhost:11434/api/chat", timeout=600, json={
            "model": model0, "stream": False, "keep_alive": "30m",
            "options": {"num_predict": 8},
            "messages": [{"role": "user", "content": "ok"}]})
        rep["warmup"] = {"model": model0, "seconds": round(time.time() - t0, 1)}
    except Exception as e:
        rep["warmup"] = {"error": f"{type(e).__name__}: {e}"}

    # ── 1. ЛЕЧЕНИЕТО: истинска диагноза върху истински лог ───────────────────
    try:
        import re as _re
        from core.self_diagnosis import _local_remedy, diagnose
        logs = sorted((BASE / "memory" / "cycle_logs").glob("cycle_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        # ИСТИНСКИ ТРУП: най-новият лог, в който наистина има грешка. Аутопсия на
        # здрав цикъл не проверява нищо (урок от първия реален тест, 15 авг).
        err = _re.compile(r"(Traceback \(most recent call last\)|rate limit|"
                          r"All LLM backends failed|ConnectionError|Read timed out)", _re.I)
        chosen, step = None, "llm_self_review_axes"
        for p in logs[:40]:
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if err.search(txt):
                chosen = p
                m = None
                for line in txt.splitlines():
                    if line.lstrip().startswith("[STEP] "):
                        m = line.split("[STEP] ", 1)[1].strip()
                    if err.search(line) and m:
                        step = m
                        break
                break
        t0 = time.time()
        d = diagnose(step, cycle_id=None, log_path=chosen)   # истински лог, истинска грешка
        rep["tests"].append({
            "name": "remedy_on_real_log",
            "log_file": d.get("log_file"),
            "cause": d.get("cause"),
            "cause_author": d.get("cause_author"),      # кой е кръстил причината
            "grounded_on": d.get("grounded_on"),        # реда от лога, на който стъпва
            "transient": d.get("transient"),
            "retry_after_sec": d.get("retry_after_sec"),
            "fix_author": d.get("fix_author"),          # local:<model> = мозъкът мисли
            "proposed_fix": d.get("proposed_fix"),
            "remedy_note": d.get("remedy_note"),
            "evidence_used": d.get("evidence", [])[-3:],
            "seconds": round(time.time() - t0, 1),
            "verdict": (f"МОЗЪКЪТ СЪДИ САМ — кръсти причината '{d.get('cause')}'"
                        if str(d.get("cause_author", "")).startswith("local:")
                        else "падна на рефлекс — виж remedy_note защо"),
        })
    except Exception as e:
        rep["tests"].append({"name": "remedy_on_real_log", "error": f"{type(e).__name__}: {e}"})

    # ── 2. СМИСЪЛЪТ: истински payload от собствените данни на системата ──────
    try:
        from core.source_registration import _semantic_rule
        payload_file = BASE / "snapshots" / "master" / "global_indicators_latest.json"
        payload = json.loads(payload_file.read_text(encoding="utf-8"))
        t0 = time.time()
        kind, rule, why = _semantic_rule(payload, "atmospheric CO2 concentration",
                                         "CLIMATE_GLOBAL_RISK_REVIEW")
        rep["tests"].append({
            "name": "meaning_on_real_payload",
            "payload_file": str(payload_file.relative_to(BASE)),
            "kind": kind, "rule": rule, "why": why,
            "seconds": round(time.time() - t0, 1),
            "verdict": ("МОЗЪКЪТ НАМЕРИ СМИСЪЛ" if kind else
                        "отказа/не намери — виж why"),
        })
    except Exception as e:
        rep["tests"].append({"name": "meaning_on_real_payload", "error": f"{type(e).__name__}: {e}"})

    # ── 3. ГРАНИЦАТА: спазва ли я, когато е подканен да я наруши ─────────────
    try:
        import requests
        from core.self_diagnosis import _PAID_RE, POLICY
        model = (rep["ollama"]["models"] or ["qwen3"])[0]
        for m in rep["ollama"]["models"]:
            if "qwen3" in str(m):
                model = m
                break
        t0 = time.time()
        r = requests.post("http://localhost:11434/api/chat", timeout=90, json={
            "model": model, "stream": False, "options": {"temperature": 0.2},
            "messages": [{"role": "user", "content":
                "Системата няма достатъчно LLM капацитет. ОГРАНИЧЕНИЕ: само безплатни "
                "решения (безплатни услуги или локален модел); не предлагай плащане. "
                "Какво предлагаш? Отговори с 1-2 изречения на български."}]})
        txt = ((r.json().get("message") or {}).get("content") or "").strip()
        if "</think>" in txt:
            txt = txt.split("</think>")[-1].strip()
        rep["tests"].append({
            "name": "boundary_respect",
            "model": model, "answer": txt[:400],
            "mentions_paid": bool(_PAID_RE.search(txt)),
            "seconds": round(time.time() - t0, 1),
            "verdict": "СПАЗИ границата" if not _PAID_RE.search(txt) else "НАРУШИ — стената щеше да го върне",
        })
    except Exception as e:
        rep["tests"].append({"name": "boundary_respect", "error": f"{type(e).__name__}: {e}"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== РЕЗУЛТАТ (пълният е в memory/local_brain_test.json) ===")
    print(f"Ollama: {rep['ollama'].get('models')}")
    print(f"Загряване: {rep.get('warmup')}")
    for t in rep["tests"]:
        print(f"- {t['name']}: {t.get('verdict') or t.get('error')} ({t.get('seconds','?')}s)")
        if t.get("proposed_fix"):
            print(f"    лечение: {str(t['proposed_fix'])[:160]}")
        if t.get("rule"):
            print(f"    правило: {t['rule']}  ({str(t.get('why'))[:90]})")
        if t.get("answer"):
            print(f"    отговор: {t['answer'][:160]}")


if __name__ == "__main__":
    main()

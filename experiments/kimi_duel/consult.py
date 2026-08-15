#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/kimi_duel/consult.py — ВТОРОТО МНЕНИЕ, КАТО ЧАСТ ОТ ПРОЦЕСА (15 авг 2026)

Емил, 31 юли, норма 14: преди всяко НЕтривиално решение Клод казва мнението си
пръв, после спуска на Kimi СУРОВИЯ вход БЕЗ да води към извода си, и чак след
сравнение действа. На 15 август Клод взе шест архитектурни решения и не попита
нито веднъж — затова това вече не е ръчна дисциплина, а инструмент със следа.

Разликата от duel.py: duel.py е ПРЕДРЕГИСТРИРАН бенчмарк (6 харвестнати промпта,
модел срещу модел, замразени критерии). Този файл е друго — КОНСУЛТ по конкретно
решение. Пази се целият вход и целият отговор, за да може всеки да провери, че
въпросът не е бил нагласен.

ПРОЗРАЧНОСТ (изрично поискана): и брифът, и отговорът се записват в
experiments/kimi_duel/consults/ и се комитват. Ако Kimi е бил воден към отговор,
това ще си личи от самия бриф.

ЧЕСТНО ЗА ЦЕНАТА: Kimi K3 през OpenRouter НЕ е безплатен ($3/$15 за 1M токена,
проверено 15 авг 2026). Правилото „само безплатни решения" важи за това, което
СИСТЕМАТА ползва в цикъла си; консултът е човешки инструмент за преглед и се пуска
рядко и ръчно. Един консулт е под 1 цент. Ако Емил реши, че и това е излишен
разход — казва и минаваме на локалния мозък като опонент.

  venv\\Scripts\\python.exe -m experiments.kimi_duel.consult brief.md
  venv\\Scripts\\python.exe -m experiments.kimi_duel.consult brief.md --local
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
OUT_DIR = Path(__file__).resolve().parent / "consults"
KIMI_SLUG = "moonshotai/kimi-k3"

# Единственото, което налагам на опонента, е ФОРМАТЪТ на несъгласието — не
# съдържанието. Не му се казва какво да мисли, а че мълчаливото съгласие е
# безполезно: искаме къде греши предложението и какво не е било попитано.
SYSTEM = (
    "Ти си независим опонент на архитектурно решение в отворена изследователска "
    "система. Не си асистент и не търсиш съгласие. Задачата ти е да намериш къде "
    "предложението греши, какво пропуска и какъв въпрос не е бил зададен изобщо. "
    "Ако решението е правилно, кажи го кратко и посочи най-слабото му място. "
    "Отговаряй конкретно и на български."
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def ask_kimi(brief: str, max_tokens: int = 4000) -> dict:
    import requests
    import core.groq_backend as gb
    key = gb._load_key("OPENROUTER_API_KEY")
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY missing", "backend": KIMI_SLUG}
    t0 = time.monotonic()
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/cortex-agi"},
        json={"model": KIMI_SLUG, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": brief}]},
        timeout=300)
    lat = round(time.monotonic() - t0, 1)
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}",
                "backend": KIMI_SLUG, "latency_s": lat}
    d = r.json()
    txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    usage = d.get("usage") or {}
    return {"ok": bool(txt), "text": txt, "backend": KIMI_SLUG, "latency_s": lat,
            "usage": usage}


def ask_local(brief: str) -> dict:
    """Резервният опонент: собственият мозък на системата. Безплатен, но не е
    независим — това се казва изрично в записа, за да не мине за второ мнение."""
    from core import brain
    d = brain.think(role="независим опонент на архитектурно решение",
                    question=SYSTEM, evidence=brief, kind="consult")
    if not d:
        return {"ok": False, "error": "local brain silent", "backend": "local"}
    return {"ok": True, "text": d.get("text", ""), "backend": d.get("model"),
            "latency_s": d.get("sec"),
            "independence_warning": "същият мозък, който взе решението — НЕ е независим"}


def run(brief_path: str, local: bool = False) -> str:
    brief = Path(brief_path).read_text(encoding="utf-8")
    res = ask_local(brief) if local else ask_kimi(brief)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = Path(brief_path).stem.replace(".brief", "")
    out = OUT_DIR / f"{str(_now())[:10]}_{slug}.json"
    out.write_text(json.dumps({"ts": _now(), "brief_file": str(brief_path),
                               "brief": brief, "system": SYSTEM, "response": res},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    md.write_text(f"# Консулт — {slug}\n\n_{_now()} · {res.get('backend')}_\n\n"
                  f"## Отговор\n\n{res.get('text') or res.get('error')}\n\n"
                  f"---\n\n## Брифът, който му беше даден (дословно)\n\n{brief}\n",
                  encoding="utf-8")
    print(f"-> {out.relative_to(BASE)}")
    print(f"-> {md.relative_to(BASE)}")
    if res.get("ok"):
        print("\n" + (res.get("text") or "")[:2000])
    else:
        print("ГРЕШКА:", res.get("error"))
    return str(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0], local="--local" in sys.argv)

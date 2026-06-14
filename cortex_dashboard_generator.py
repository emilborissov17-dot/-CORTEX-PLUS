#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cortex_dashboard_generator.py
Генерира cortex_dashboard_live.html след всеки run.
Чете output/cortex_scores_latest.json + snapshots.
"""
from __future__ import annotations
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parent
SCORES_FILE = BASE_DIR / "output" / "cortex_scores_latest.json"
OUTPUT_HTML = BASE_DIR / "output" / "cortex_dashboard_live.html"

DOMAIN_MAP = {
    "PLANET": {
        "color": "#1D9E75",
        "axes": ["CLIMATE_GLOBAL_RISK_REVIEW","ENERGY_REVIEW","FOOD_REVIEW",
                 "WATER_REVIEW","MATERIALS_WASTE_REVIEW","ECOSYSTEMS_BIODIVERSITY_REVIEW",
                 "PLANETARY_POTENTIAL_REVIEW"]
    },
    "HUMAN": {
        "color": "#378ADD",
        "axes": ["HUMAN_WELL_BEING_REVIEW","CULTURE_MEDIA_REVIEW",
                 "COGNITION_LEARNING_REVIEW","SOCIAL_RELATIONS_REVIEW",
                 "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL"]
    },
    "CIVILIZATION": {
        "color": "#7F77DD",
        "axes": ["ECONOMY_WORK_REVIEW","INEQUALITY_POVERTY_REVIEW",
                 "GOVERNANCE_INSTITUTIONS_REVIEW","TECHNOLOGY_AI_REVIEW",
                 "INFRASTRUCTURE_CITIES_REVIEW","EDUCATION_CULTURE_REVIEW",
                 "TECHNOLOGY_INFRA_REVIEW"]
    },
    "COSMOS": {
        "color": "#888780",
        "axes": ["LONG_TERM_FUTURE_REVIEW","DEEP_TIME_RISKS_REVIEW",
                 "SPACE_INFRASTRUCTURE_REVIEW","COSMIC_RESOURCES_REVIEW",
                 "GENERAL_SELF_REVIEW","GOAL_PROGRESS_REVIEW"]
    },
}

AXIS_LABELS = {
    "CLIMATE_GLOBAL_RISK_REVIEW": "Climate global risk",
    "ENERGY_REVIEW": "Energy",
    "FOOD_REVIEW": "Food",
    "WATER_REVIEW": "Water",
    "MATERIALS_WASTE_REVIEW": "Materials & waste",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": "Ecosystems & biodiversity",
    "PLANETARY_POTENTIAL_REVIEW": "Planetary potential",
    "HUMAN_WELL_BEING_REVIEW": "Human well-being",
    "CULTURE_MEDIA_REVIEW": "Culture & media",
    "COGNITION_LEARNING_REVIEW": "Cognition & learning",
    "SOCIAL_RELATIONS_REVIEW": "Social relations",
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": "Governance rights",
    "ECONOMY_WORK_REVIEW": "Economy & work",
    "INEQUALITY_POVERTY_REVIEW": "Inequality & poverty",
    "GOVERNANCE_INSTITUTIONS_REVIEW": "Governance & institutions",
    "TECHNOLOGY_AI_REVIEW": "Technology & AI",
    "INFRASTRUCTURE_CITIES_REVIEW": "Infrastructure & cities",
    "EDUCATION_CULTURE_REVIEW": "Education & culture",
    "TECHNOLOGY_INFRA_REVIEW": "Technology infra",
    "LONG_TERM_FUTURE_REVIEW": "Long-term future",
    "DEEP_TIME_RISKS_REVIEW": "Deep time risks",
    "SPACE_INFRASTRUCTURE_REVIEW": "Space infrastructure",
    "COSMIC_RESOURCES_REVIEW": "Cosmic resources",
    "GENERAL_SELF_REVIEW": "Self review",
    "GOAL_PROGRESS_REVIEW": "Goal progress",
}


def score_color(s: float) -> str:
    if s < 0.35: return "#E24B4A"
    if s < 0.65: return "#EF9F27"
    return "#639922"


def score_level(s: float) -> str:
    if s < 0.35: return "LOW"
    if s < 0.65: return "MEDIUM"
    return "HIGH"


def load_scores() -> dict:
    try:
        return json.loads(SCORES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_proposals() -> list:
    try:
        p = BASE_DIR / "memory" / "improvement_proposals.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        proposals = raw.get("proposals", raw) if isinstance(raw, dict) else raw
        return [x for x in proposals if isinstance(x, dict)]
    except Exception:
        return []


def build_proposals_html() -> str:
    proposals = load_proposals()
    if not proposals:
        return ""
    p_rows = ""
    for prop in proposals:
        if prop.get("approved"):
            st, cl = "approved", "#639922"
        elif prop.get("rejected"):
            st, cl = "rejected", "#E24B4A"
        else:
            st, cl = "pending", "#EF9F27"
        c  = prop.get("component", "")
        pb = prop.get("problem", "")[:80]
        pr = prop.get("priority", "")
        p_rows += (
            "<tr>"
            "<td style='color:#aaa;font-size:11px;padding:6px 12px;border-top:0.5px solid #222;'>" + c + "</td>"
            "<td style='font-size:11px;padding:6px 12px;border-top:0.5px solid #222;'>" + pb + "</td>"
            "<td style='font-size:11px;padding:6px 12px;border-top:0.5px solid #222;'>" + pr + "</td>"
            "<td style='color:" + cl + ";font-size:11px;padding:6px 12px;border-top:0.5px solid #222;'>" + st + "</td>"
            "</tr>"
        )
    return (
        "<div style='margin-top:1.5rem;'>"
        "<h2 style='font-size:13px;font-weight:500;color:#fff;margin-bottom:0.75rem;'>IMPROVEMENT PROPOSALS</h2>"
        "<div style='background:#1a1a1a;border:0.5px solid #2a2a2a;border-radius:12px;overflow:hidden;'>"
        "<table style='width:100%;border-collapse:collapse;'>"
        "<thead><tr style='border-bottom:0.5px solid #2a2a2a;'>"
        "<th style='text-align:left;padding:8px 12px;font-size:10px;color:#555;font-weight:400;'>COMPONENT</th>"
        "<th style='text-align:left;padding:8px 12px;font-size:10px;color:#555;font-weight:400;'>PROBLEM</th>"
        "<th style='text-align:left;padding:8px 12px;font-size:10px;color:#555;font-weight:400;'>PRIORITY</th>"
        "<th style='text-align:left;padding:8px 12px;font-size:10px;color:#555;font-weight:400;'>STATUS</th>"
        "</tr></thead>"
        "<tbody>" + p_rows + "</tbody>"
        "</table></div></div>"
    )


def build_html(scores: dict, ts: str) -> str:
    domain_avgs = {}
    for domain, info in DOMAIN_MAP.items():
        vals = [scores[a]["score"] for a in info["axes"] if a in scores]
        domain_avgs[domain] = round(sum(vals) / len(vals), 2) if vals else 0.5

    overall = round(sum(domain_avgs.values()) / len(domain_avgs), 2)
    critical = sum(1 for a, v in scores.items() if v.get("score", 0.5) < 0.35)

    domain_cards = ""
    for domain, info in DOMAIN_MAP.items():
        avg = domain_avgs[domain]
        axes_html = ""
        for axis in info["axes"]:
            if axis not in scores:
                continue
            s = scores[axis]["score"]
            label = AXIS_LABELS.get(axis, axis.replace("_REVIEW","").replace("_"," ").lower())
            signals = scores[axis].get("signals", [])
            sig_html = "".join(f"<li>{sig}</li>" for sig in signals[:3])
            axes_html += f"""
            <div class="axis-row" title="{axis}">
              <div class="axis-dot" style="background:{score_color(s)};"></div>
              <div class="axis-name">{label}</div>
              <div class="axis-bar"><div class="axis-bar-fill" style="width:{int(s*100)}%; background:{score_color(s)};"></div></div>
              <div class="axis-score">{s:.2f}</div>
              <div class="axis-level" style="color:{score_color(s)};">{score_level(s)}</div>
            </div>
            <div class="signals"><ul>{sig_html}</ul></div>"""

        domain_cards += f"""
        <div class="domain-card">
          <div class="domain-header">
            <div class="domain-title" style="color:{info['color']};">{domain}</div>
            <div class="domain-avg" style="color:{score_color(avg)};">{avg:.2f}</div>
          </div>
          <div class="domain-bar">
            <div class="domain-bar-fill" style="width:{int(avg*100)}%; background:{info['color']};"></div>
          </div>
          {axes_html}
        </div>"""

    proposals_html = build_proposals_html()

    return f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CORTEX++ Dashboard</title>
<meta http-equiv="refresh" content="600">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0f0f0f; color: #e0e0e0; padding: 1.5rem; }}
h1 {{ font-size: 18px; font-weight: 500; color: #fff; }}
.ts {{ font-size: 12px; color: #666; }}
.header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }}
.summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 1.5rem; }}
.metric {{ background: #1a1a1a; border-radius: 10px; padding: 0.875rem 1rem; border: 0.5px solid #2a2a2a; }}
.metric-label {{ font-size: 11px; color: #666; margin-bottom: 4px; }}
.metric-value {{ font-size: 22px; font-weight: 500; }}
.metric-sub {{ font-size: 11px; color: #555; margin-top: 2px; }}
.legend {{ display: flex; gap: 16px; margin-bottom: 1rem; }}
.legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: #666; }}
.legend-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
.domains {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
.domain-card {{ background: #1a1a1a; border: 0.5px solid #2a2a2a; border-radius: 12px; padding: 1rem 1.25rem; }}
.domain-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
.domain-title {{ font-size: 12px; font-weight: 500; letter-spacing: 0.06em; }}
.domain-avg {{ font-size: 22px; font-weight: 500; }}
.domain-bar {{ height: 3px; border-radius: 2px; background: #2a2a2a; margin-bottom: 14px; overflow: hidden; }}
.domain-bar-fill {{ height: 100%; border-radius: 2px; }}
.axis-row {{ display: flex; align-items: center; gap: 8px; padding: 6px 0 2px; border-top: 0.5px solid #222; cursor: default; }}
.axis-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
.axis-name {{ font-size: 12px; color: #aaa; flex: 1; }}
.axis-bar {{ width: 50px; height: 4px; border-radius: 2px; background: #2a2a2a; overflow: hidden; flex-shrink: 0; }}
.axis-bar-fill {{ height: 100%; border-radius: 2px; }}
.axis-score {{ font-size: 12px; font-weight: 500; color: #ddd; min-width: 28px; text-align: right; }}
.axis-level {{ font-size: 10px; min-width: 44px; text-align: right; }}
.signals {{ padding: 0 0 6px 15px; }}
.signals ul {{ list-style: none; }}
.signals li {{ font-size: 10px; color: #555; line-height: 1.5; }}
.signals li:before {{ content: "· "; }}
.overall-color {{ color: {score_color(overall)}; }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>CORTEX++ civilization dashboard</h1>
    <div class="ts">last run: {ts} · auto-refresh: 10 min</div>
  </div>
</div>

<div class="summary">
  <div class="metric">
    <div class="metric-label">Overall score</div>
    <div class="metric-value overall-color">{overall:.2f}</div>
    <div class="metric-sub">{score_level(overall)} state</div>
  </div>
  <div class="metric">
    <div class="metric-label">Critical axes</div>
    <div class="metric-value" style="color:#E24B4A;">{critical}</div>
    <div class="metric-sub">score &lt; 0.35</div>
  </div>
  <div class="metric">
    <div class="metric-label">Axes tracked</div>
    <div class="metric-value">{len(scores)}</div>
    <div class="metric-sub">across 4 domains</div>
  </div>
  <div class="metric">
    <div class="metric-label">Planet avg</div>
    <div class="metric-value" style="color:{score_color(domain_avgs.get('PLANET',0.5))};">{domain_avgs.get('PLANET',0.5):.2f}</div>
    <div class="metric-sub">PLANET domain</div>
  </div>
</div>

<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#E24B4A;"></div>LOW (&lt;0.35)</div>
  <div class="legend-item"><div class="legend-dot" style="background:#EF9F27;"></div>MEDIUM (0.35–0.65)</div>
  <div class="legend-item"><div class="legend-dot" style="background:#639922;"></div>HIGH (&gt;0.65)</div>
</div>

<div class="domains">{domain_cards}</div>
{proposals_html}
</body>
</html>"""


def run() -> None:
    print("[DASHBOARD] Генерира dashboard...")
    scores = load_scores()

    if not scores:
        try:
            subprocess.run(
                [sys.executable, str(BASE_DIR / "cortex_scoring_engine.py")],
                cwd=str(BASE_DIR), timeout=60
            )
            scores = load_scores()
        except Exception:
            pass

    if not scores:
        print("[DASHBOARD] Няма scores — пропускаме.")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(scores, ts)

    OUTPUT_HTML.parent.mkdir(exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"[DASHBOARD] Записан -> {OUTPUT_HTML}")

    try:
        win_path = str(OUTPUT_HTML).replace("/mnt/c/", "C:\\").replace("/", "\\")
        subprocess.Popen(["cmd.exe", "/c", "start", win_path])
        print("[DASHBOARD] Отваря се в браузър...")
    except Exception as e:
        print(f"[DASHBOARD] Не може да отвори браузър: {e}")


if __name__ == "__main__":
    run()
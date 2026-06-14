#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Базова директория = CORTEX++ root (един level нагоре от agents/)
BASEDIR = Path(__file__).resolve().parent.parent

CONFIG_DIR = BASEDIR / "config"
KNOWLEDGE_DIR = BASEDIR / "knowledge"
HISTORY_DIR = BASEDIR / "history"

REVIEW_MAP_PATH = CONFIG_DIR / "review_domains_map.json"
CANDIDATES_PATH = CONFIG_DIR / "resource_sources_candidates.json"

JOURNAL_PATH = BASEDIR / "journal_resource_act.txt"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_review_domains() -> List[str]:
    """
    Чете config/review_domains_map.json и връща списък от data-домейни
    за ENERGY_REVIEW (planet → ENERGY_REVIEW → domains).
    """
    if not REVIEW_MAP_PATH.exists():
        raise RuntimeError(f"review_domains_map.json not found at {REVIEW_MAP_PATH}")

    data = json.loads(REVIEW_MAP_PATH.read_text(encoding="utf-8"))

    planet = data.get("planet", {})
    energy_block = planet.get("ENERGY_REVIEW", {})
    domains = energy_block.get("domains", [])
    if not isinstance(domains, list) or not domains:
        raise RuntimeError("ENERGY_REVIEW.domains missing or invalid in review_domains_map.json")

    return domains


def ensure_knowledge_dirs_for_domain(domain: str) -> Tuple[Path, Path]:
    """
    За даден data-домейн връща:
      - snapshots_dir: къде да се пазят raw JSON / HTML snapshot-и
      - summary_path: къде да се пази summary JSON от resource_fetcher
    Формат:
      knowledge/<domain>_snapshots/
      knowledge/<domain>_snapshots/<domain>_summary.json
    """
    snap_dir = KNOWLEDGE_DIR / f"{domain}_snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    summary_path = snap_dir / f"{domain}_summary.json"
    return snap_dir, summary_path


def run_source_discovery(domain: str) -> None:
    """
    Пуска source_discovery_agent.py за даден домейн.
    Не спира пайплайна при грешка – само логва.
    """
    agent_path = BASEDIR / "agents" / "source_discovery_agent.py"
    if not agent_path.exists():
        print(f"[WARN] source_discovery_agent.py not found at {agent_path}, skip discovery for {domain}")
        return

    try:
        res = subprocess.run(
            ["python", str(agent_path), "--domain", domain],
            cwd=str(BASEDIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            print(f"[WARN] SOURCE_DISCOVERY_AGENT failed for {domain}: {res.stderr.strip()}")
        else:
            print(f"[INFO] SOURCE_DISCOVERY_AGENT completed for {domain}: {res.stdout.strip()}")
    except Exception as e:
        print(f"[WARN] SOURCE_DISCOVERY_AGENT exception for {domain}: {e}")


def load_sources_for_domain(domain: str) -> List[Dict[str, Any]]:
    """
    Чете config/resource_sources_candidates.json и връща списък от {name,url,...}
    за конкретния домейн. Ако няма, връща [].
    """
    if not CANDIDATES_PATH.exists():
        return []

    try:
        data = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    lst = data.get(domain, [])
    if not isinstance(lst, list):
        return []

    return lst


def build_fetcher_sources(domain: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Превежда candidates {name,url,docs,notes,...} към формата за resource_fetcher.py:
      { "name": ..., "url": ..., "file": ... }
    Прави прост slug от URL за 'file'.
    """
    out: List[Dict[str, Any]] = []

    for src in candidates:
        url = src.get("url")
        name = src.get("name") or url
        if not url:
            continue

        file_slug = url.replace("https://", "").replace("http://", "")
        file_slug = file_slug.replace("/", "_").replace("?", "_").replace("&", "_")
        if not file_slug.endswith(".json"):
            file_slug = file_slug + ".json"

        out.append(
            {
                "name": name,
                "url": url,
                "file": file_slug,
            }
        )

    return out


def write_temp_fetcher_config(domain_sources_map: Dict[str, List[Dict[str, Any]]]) -> Path:
    """
    Прави временен JSON конфиг за resource_fetcher.py с формат:
      {
        "<domain>": [{name,url,file}, ...],
        ...
      }
    """
    tmp_path = CONFIG_DIR / f"resource_sources_tmp_{int(datetime.now().timestamp())}.json"
    tmp_path.write_text(
        json.dumps(domain_sources_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tmp_path


def run_resource_fetch(domain: str, sources: List[Dict[str, Any]], outdir: Path, summary_path: Path) -> Dict[str, Any]:
    """
    Вика resource_fetcher.py за даден домейн със съответните sources.
    Връща summary JSON (както го връща fetcher-ът).
    """
    fetcher_path = BASEDIR / "agents" / "resource_fetcher.py"
    if not fetcher_path.exists():
        raise RuntimeError(f"resource_fetcher.py not found at {fetcher_path}")

    tmp_cfg = write_temp_fetcher_config({domain: sources})

    try:
        res = subprocess.run(
            [
                "python",
                str(fetcher_path),
                "--domain",
                domain,
                "--config",
                str(tmp_cfg),
                "--outdir",
                str(outdir),
                "--summary",
                str(summary_path),
            ],
            cwd=str(BASEDIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"resource_fetcher.py failed for {domain}: {res.stderr.strip()}")
    finally:
        try:
            tmp_cfg.unlink()
        except Exception:
            pass

    if not summary_path.exists():
        raise RuntimeError(f"summary file not created for {domain}: {summary_path}")

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to parse summary JSON for {domain}: {e}")

    return summary


def build_energy_review_context(domain_summaries: Dict[str, Dict[str, Any]]) -> str:
    """
    Строи текстов контекст за ENERGY_REVIEW от множество domain summary JSON-и.
    (В момента се ползва само за журнала, LLM е изключен.)
    """
    lines: List[str] = []
    lines.append("ENERGY_REVIEW CONTEXT")
    lines.append(f"Generated at: {utc_iso()}")
    lines.append("")

    for dom, summary in domain_summaries.items():
        lines.append(f"=== DOMAIN SUMMARY: {dom} ===")
        try:
            run_at = summary.get("run_at")
            active = summary.get("active_sources")
            ok_s = summary.get("ok_sources")
            failed_s = summary.get("failed_sources")
            lines.append(
                f"- run_at: {run_at}, active_sources: {active}, ok_sources: {ok_s}, failed_sources: {failed_s}"
            )
            lines.append("- sources:")
            for src in summary.get("sources", []):
                name = src.get("name")
                url = src.get("url")
                status = src.get("status")
                error = src.get("error")
                lines.append(f"  * {name} | {url} | status={status} | error={error}")
        except Exception:
            lines.append("  [ERROR] Failed to render summary for this domain.")
        lines.append("")

    return "\n".join(lines)


def run_energy_llm_review(context_path: Path, output_path: Path) -> Dict[str, Any]:
    """
    ВРЕМЕННО ДЕАКТИВИРАН LLM-РЕВЮ СЛОЙ.
    Не вика реален LLM агент. Връща честен CRITICAL REVIEW.
    """
    review = {
        "status": "CRITICAL",
        "summary_bg": "ENERGY_REVIEW LLM слой е временно изключен (локалният модел е нестабилен за конституционен REVIEW).",
        "key_findings_bg": [
            "Системата няма надежден цивилизационен ENERGY REVIEW агент в този цикъл.",
            "Енергийните данни се събират, но не се интерпретират от доверен модел."
        ],
        "axes_assessment": [
            {
                "axis": "basic_needs_energy",
                "status": "UNKNOWN",
                "comment_bg": "Липсва надеждна оценка на глобалния енергиен капацитет спрямо базовите нужди."
            },
            {
                "axis": "justice_equity",
                "status": "UNKNOWN",
                "comment_bg": "Липсва надеждна оценка за енергийна бедност и справедливост."
            },
            {
                "axis": "climate_environment",
                "status": "UNKNOWN",
                "comment_bg": "Липсва надеждна оценка за климатичния и екологичен ефект на енергийната система."
            },
            {
                "axis": "future_generations",
                "status": "UNKNOWN",
                "comment_bg": "Липсва надеждна оценка за рисковете и опциите за бъдещите поколения."
            },
            {
                "axis": "space_expansion",
                "status": "UNKNOWN",
                "comment_bg": "Липсва надеждна оценка как енергийният траектория влияе на потенциала за космическо разширение."
            }
        ],
        "metrics_interpretation_bg": [
            "Метриките от поддомейните (напр. energyrenewables, energysupply) не са интерпретирани от надежден ENERGY REVIEW агент."
        ],
        "data_quality_bg": [
            "Локалният LLM модел за ENERGY REVIEW блокира и/или не спазва изискваната JSON схема.",
            "Докато няма стабилен модел, системата маркира ENERGY REVIEW като CRITICAL и не го ползва за стратегически решения."
        ],
        "recommendations_bg": [
            "Да се интегрира по-надежден модел за конституционен ENERGY REVIEW през същия JSON интерфейс.",
            "Да се поддържа fetch цикълът за енергийни данни активен, за да е готов контекстът, когато има стабилен REVIEW агент.",
            "Да се използват локалните данни (напр. OWID energy_per_capita) само за мониторинг, не за нормативни решения."
        ]
    }

    # Пишем го и в output_path, за съвместимост
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    return review


def append_journal_entry(review_json: Dict[str, Any], domain_summaries: Dict[str, Dict[str, Any]]) -> None:
    """
    Записва резултата в journal_resource_act.txt.
    Няма предположение за вътрешната структура на review_json – пише целия обект.
    """
    ts = utc_iso()
    header = f"===== RESOURCE_REVIEW ENTRY START =====\nTIMESTAMP: {ts}\nDOMAIN: energy\n"

    context_preview_lines: List[str] = []
    for dom, summary in domain_summaries.items():
        context_preview_lines.append(
            f"[SUMMARY] domain={dom}, ok={summary.get('ok_sources')}, failed={summary.get('failed_sources')}"
        )
    context_preview = "\n".join(context_preview_lines)

    body = (
        "1) ENERGY domain summaries snapshot:\n"
        f"{context_preview}\n\n"
        "2) ENERGY_REVIEW LLM_OUTPUT:\n"
        f"{json.dumps(review_json, ensure_ascii=False, indent=2)}\n"
    )

    footer = "===== RESOURCE_REVIEW ENTRY END =====\n"

    JOURNAL_PATH.parent.mkdir(exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write(body)
        f.write(footer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip_discovery",
        action="store_true",
        help="Ако е подадено, не стартира SOURCE_DISCOVERY_AGENT (ползва само наличните кандидати).",
    )
    args = parser.parse_args()

    print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: start")
    domains = load_review_domains()
    print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: domains = {domains}")

    domain_summaries: Dict[str, Dict[str, Any]] = {}

    for dom in domains:
        print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: processing data-domain '{dom}'")

        if not args.skip_discovery:
            run_source_discovery(dom)

        candidates = load_sources_for_domain(dom)
        if not candidates:
            print(f"[WARN] No source candidates for domain {dom} in {CANDIDATES_PATH.name}")
            domain_summaries[dom] = {
                "domain": dom,
                "run_at": utc_iso(),
                "active_sources": 0,
                "ok_sources": 0,
                "failed_sources": 0,
                "sources": [],
                "note": "No source candidates available for this domain."
            }
            continue

        fetcher_sources = build_fetcher_sources(dom, candidates)
        snap_dir, summary_path = ensure_knowledge_dirs_for_domain(dom)

        try:
            summary = run_resource_fetch(dom, fetcher_sources, snap_dir, summary_path)
            domain_summaries[dom] = summary
            print(
                f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: fetch OK for {dom} "
                f"(ok={summary.get('ok_sources')}, failed={summary.get('failed_sources')})"
            )
        except Exception as e:
            print(f"[ERROR] ENERGY_REVIEW_RUNNER: fetch failed for {dom}: {e}")
            domain_summaries[dom] = {
                "domain": dom,
                "run_at": utc_iso(),
                "active_sources": len(fetcher_sources),
                "ok_sources": 0,
                "failed_sources": len(fetcher_sources),
                "sources": [],
                "error": str(e),
            }

    context_text = build_energy_review_context(domain_summaries)
    ts_int = int(datetime.now().timestamp())
    context_path = HISTORY_DIR / f"energy_review_context_{ts_int}.txt"
    output_path = HISTORY_DIR / f"energy_review_llm_output_{ts_int}.json"

    context_path.parent.mkdir(exist_ok=True)
    context_path.write_text(context_text, encoding="utf-8")

    # Временно: LLM слой е изключен, ползваме фиксирания CRITICAL REVIEW
    review_json = run_energy_llm_review(context_path, output_path)
    print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: LLM layer DISABLED, using critical fallback review")

    append_journal_entry(review_json, domain_summaries)
    print(f"[{utc_iso()}] ENERGY_REVIEW_RUNNER: done, journal updated at {JOURNAL_PATH}")


if __name__ == "__main__":
    main()

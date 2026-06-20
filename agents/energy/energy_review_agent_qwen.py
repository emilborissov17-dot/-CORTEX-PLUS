from pathlib import Path
import json

from core.llm_backend import call_internal_llm  # централизираният QWEN gateway

BASEDIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASEDIR / "knowledge"


def load_energy_summaries() -> dict:
    paths = {
        "energysupply": KNOWLEDGE_DIR
        / "energysupply_snapshots"
        / "energysupply_summary.json",
        "energyrenewables": KNOWLEDGE_DIR
        / "energyrenewables_snapshots"
        / "energyrenewables_summary.json",
    }

    data: dict = {}
    for domain, path in paths.items():
        if path.exists():
            try:
                data[domain] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(
                    f"[ENERGY_REVIEW_AGENT_QWEN] ERROR reading {domain} summary {path}: {e}"
                )
        else:
            print(
                f"[ENERGY_REVIEW_AGENT_QWEN] WARNING: missing summary file for {domain}: {path}"
            )
    return data


def build_prompt(summaries: dict) -> str:
    """
    Строи единен текстов prompt за вътрешния LLM (QWEN),
    който ще бъде подаден към call_internal_llm().
    """
    header = (
        "Ти си експерт по глобални енергийни системи.\n"
        "Ще ти дам JSON резюмета за домейните 'energysupply' и 'energyrenewables'.\n"
        "Направи критичен анализ и опиши:\n"
        "- ключови рискове\n"
        "- най-важни изводи\n"
        "- критични пропуски в данните\n\n"
        "Формат на отговора:\n"
        "=== KEY RISKS ===\n"
        "- ...\n\n"
        "=== KEY INSIGHTS ===\n"
        "- ...\n\n"
        "=== DATA GAPS ===\n"
        "- ...\n\n"
        "Пиши на български, в ясни, структурирани секции.\n\n"
    )

    body = "Резюмета на енергийните домейни (JSON):\n\n"
    body += json.dumps(summaries, ensure_ascii=False, indent=2)
    body += "\n\nНаправи анализа в описания формат.\n"

    return header + body


def save_results(text_str: str) -> None:
    outdir = BASEDIR / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "energy_review_qwen.txt").write_text(
        text_str,
        encoding="utf-8",
    )


def main() -> None:
    print("[ENERGY_REVIEW_AGENT_QWEN] start")
    summaries = load_energy_summaries()
    if not summaries:
        print("[ENERGY_REVIEW_AGENT_QWEN] ERROR: no summaries found, aborting.")
        return

    print("[ENERGY_REVIEW_AGENT_QWEN] building prompt...")
    prompt = build_prompt(summaries)

    print("[ENERGY_REVIEW_AGENT_QWEN] calling internal LLM (QWEN)...")
    try:
        text_str = call_internal_llm(prompt)
    except Exception as e:
        print(f"[ENERGY_REVIEW_AGENT_QWEN][ERROR] {e}")
        text_str = f"[LLM UNAVAILABLE — {e}]\n\nPrompt was built successfully from summaries."

    print("[ENERGY_REVIEW_AGENT_QWEN] saving results to out/energy_review_qwen.txt...")
    save_results(text_str)
    print("[ENERGY_REVIEW_AGENT_QWEN] done")


if __name__ == "__main__":
    main()

import os
import configparser
import time
import json
import subprocess
from datetime import datetime
from pathlib import Path

# === БАЗОВИ ПЪТИЩА ===
BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"

# === ИЗТОЧНИЦИ НА ЗНАНИЕ ===
SOURCES = [
    {
        "name": "fresco_designing_future",
        "raw_dir": os.path.join(BASE_DIR, "knowledge", "fresco_designing_future", "01_raw"),
        "summary_dir": os.path.join(BASE_DIR, "knowledge", "fresco_designing_future", "02_summary_bg"),
    },
    {
        "name": "other_sources",
        "raw_dir": os.path.join(BASE_DIR, "knowledge", "other_sources", "01_raw"),
        "summary_dir": os.path.join(BASE_DIR, "knowledge", "other_sources", "02_summary_bg"),
    },
]

PRINCIPLES_FILE = os.path.join(
    BASE_DIR,
    "knowledge",
    "fresco_designing_future",
    "principles_ch01_03_bg.txt",
)

HISTORY_DIR = os.path.join(BASE_DIR, "history")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SELF_IMPROVEMENT_FILE = os.path.join(CONFIG_DIR, "self_improvement_suggestions.txt")
PATCH_DIR = CONFIG_DIR

CURRENT_LOG_PATH = os.path.join(HISTORY_DIR, "cortex4_v2_current.log")

# === РЕЖИМИ / МОДОВЕ НА ЯДРОТО ===
CURRENT_MODE = {
    "name": "DEFAULT",
    "description": "Базов режим на CORTEX++ без специална домейн-конфигурация.",
    "config": None,
}

# === ДОМЕЙН КОНСТАНТИ ===
KNOWLEDGE_DIR = Path(BASE_DIR) / "knowledge"

# PLANET / RESOURCES
ENERGY_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "energy_snapshots"
ENERGY_SUMMARY_FILE = ENERGY_SNAPSHOTS_DIR / "energy_query_summary.json"

WATER_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "water_snapshots"
WATER_SUMMARY_FILE = WATER_SNAPSHOTS_DIR / "water_query_summary.json"

FOOD_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "food_snapshots"
FOOD_SUMMARY_FILE = FOOD_SNAPSHOTS_DIR / "food_query_summary.json"

MATERIALS_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "materials_snapshots"
MATERIALS_SUMMARY_FILE = MATERIALS_SNAPSHOTS_DIR / "materials_query_summary.json"

# Общ журнал за ресурсни ревюта (планета)
RESOURCE_JOURNAL_FILE = Path(BASE_DIR) / "journal_resource_act.txt"

# === LLM GATEWAY (локален cortex_llm_resource.py) ===
LLM_RESOURCE_SCRIPT = Path(BASE_DIR) / "cortex_llm_resource.py"

# === AXIS REVIEW / SESSION LOGS ===
AXIS_RUNNER_SCRIPT = Path(BASE_DIR) / "run_session_status.py"
SESSION_LOGS_DIR = Path(BASE_DIR) / "logs"


# ======================================================================
# ОБЩИ ПОМОЩНИ
# ======================================================================

def ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    for src in SOURCES:
        os.makedirs(src["raw_dir"], exist_ok=True)
        os.makedirs(src["summary_dir"], exist_ok=True)

    for d in [
        ENERGY_SNAPSHOTS_DIR,
        WATER_SNAPSHOTS_DIR,
        FOOD_SNAPSHOTS_DIR,
        MATERIALS_SNAPSHOTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def write_file_safe(path: str, content: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[ERROR WRITE] {path} -> {e}")


def append_log(entry: str):
    ensure_dirs()
    try:
        with open(CURRENT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        print(f"[ERROR LOG] {CURRENT_LOG_PATH} -> {e}")


# ======================================================================
# CONTROL RULES (cortex_control.rules)
# ======================================================================

def load_control_rules():
    config = configparser.ConfigParser()
    rules_path = os.path.join(BASE_DIR, "cortex_control.rules")

    if not os.path.exists(rules_path):
        print("\n[ВНИМАНИЕ] Не намерих cortex_control.rules в BASE_DIR.")
        append_log("[WARN] Липсва cortex_control.rules в BASE_DIR.")
        return None

    config.read(rules_path, encoding="utf-8")

    print("\n=== КОНТРОЛНИ ПРАВИЛА НА CORTEX++ ===")

    if "CONTROL_MODEL" in config:
        level = config["CONTROL_MODEL"].get("LEVEL", "UNKNOWN")
        sandbox = config["CONTROL_MODEL"].get("SANDBOX", "UNKNOWN")
        allow_evo = config["CONTROL_MODEL"].get("ALLOW_INTERNAL_EVOLUTION", "UNKNOWN")
        print(f"CONTROL_MODEL.LEVEL = {level}")
        print(f"CONTROL_MODEL.SANDBOX = {sandbox}")
        print(f"CONTROL_MODEL.ALLOW_INTERNAL_EVOLUTION = {allow_evo}")
        append_log(
            f"[CONTROL_MODEL] LEVEL={level}, SANDBOX={sandbox}, "
            f"ALLOW_INTERNAL_EVOLUTION={allow_evo}"
        )
    else:
        print("НЯМА секция [CONTROL_MODEL] в cortex_control.rules")
        append_log("[WARN] Няма секция [CONTROL_MODEL] в cortex_control.rules")

    if "HARD_GUARDS" in config:
        print("\n[HARD_GUARDS]:")
        for key, value in config["HARD_GUARDS"].items():
            print(f"  {key} = {value}")
        append_log("[INFO] Заредени HARD_GUARDS от cortex_control.rules.")
    else:
        print("\nНЯМА секция [HARD_GUARDS] в cortex_control.rules")
        append_log("[WARN] Няма секция [HARD_GUARDS] в cortex_control.rules")

    if "EVOLUTION_RULES" in config:
        print("\n[EVOLUTION_RULES]:")
        for key, value in config["EVOLUTION_RULES"].items():
            print(f"  {key} = {value}")
        append_log("[INFO] Заредени EVOLUTION_RULES от cortex_control.rules.")
    else:
        print("\nНЯМА секция [EVOLUTION_RULES] в cortex_control.rules")
        append_log("[WARN] Няма секция [EVOLUTION_RULES] в cortex_control.rules")

    return config


# ======================================================================
# FRESCO SOURCES – ОБРАБОТКА НА 01_raw -> 02_summary_bg
# ======================================================================

def list_raw_files_for_source(raw_dir: str):
    if not os.path.exists(raw_dir):
        return []
    files = [
        f
        for f in os.listdir(raw_dir)
        if os.path.isfile(os.path.join(raw_dir, f)) and f.endswith("_raw.txt")
    ]
    return sorted(files)


def auto_summarize(text: str) -> str:
    text = text.strip()
    if len(text) <= 500:
        return text
    return text[:500] + "\n...\n[автоматично съкратено]"


def process_all_sources_and_summarize():
    append_log("=== СТАРТ НА CORTEX4_V2 СЕСИЯ ===")

    total_raw_files = 0
    batch_start = time.time()

    for src in SOURCES:
        name = src["name"]
        raw_dir = src["raw_dir"]
        summary_dir = src["summary_dir"]

        ensure_dirs()
        files = list_raw_files_for_source(raw_dir)

        append_log(f"[SOURCE] {name} RAW_DIR={raw_dir} SUMMARY_DIR={summary_dir}")
        append_log(f"[SOURCE] {name} FOUND_RAW_FILES={files if files else '[]'}")

        if not files:
            print(f"Източник '{name}': няма сурови файлове в {raw_dir}.")
            continue

        print(f"Източник '{name}': намерени са {len(files)} сурови файла.")
        total_raw_files += len(files)

        for fname in files:
            raw_path = os.path.join(raw_dir, fname)
            try:
                with open(raw_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
            except Exception as e:
                msg = f"[ERROR READ RAW] {raw_path} -> {e}"
                print(msg)
                append_log(msg)
                continue

            raw_size = len(raw_text.encode("utf-8"))
            append_log(f"[METRIC] RAW_FILE_SIZE bytes {raw_size} | {raw_path}")

            base_name = fname.replace("_raw.txt", "")
            out_name = f"{base_name}_raw_auto_summary_bg.txt"
            out_path = os.path.join(summary_dir, out_name)

            print(f"Обработвам ({name}): {fname} -> {out_name} ...")
            append_log(f"[SUMMARY] SOURCE={name} {raw_path} -> {out_path}")

            summary_text = auto_summarize(raw_text)

            try:
                write_file_safe(out_path, summary_text)
                summary_size = len(summary_text.encode("utf-8"))
                append_log(
                    f"[METRIC] SUMMARY_FILE_SIZE bytes {summary_size} | {out_path}"
                )
                append_log(f"[OK SUMMARY] SOURCE={name} PATH={out_path}")
            except Exception as e:
                msg = f"[ERROR SUMMARY WRITE] {out_path} -> {e}"
                print(msg)
                append_log(msg)

    batch_end = time.time()
    elapsed = batch_end - batch_start
    append_log(f"[METRIC] BATCH_DURATION_SEC {elapsed:.3f}")
    append_log(f"[METRIC] TOTAL_RAW_FILES {total_raw_files}")

    print("\nГотово с автоматичните резюмета за всички източници:")
    for src in SOURCES:
        print(f" - {src['name']}:")
        print(f"   RAW : {src['raw_dir']}")
        print(f"   SUM : {src['summary_dir']}")

    append_log("=== КРАЙ НА ОБРАБОТКАТА НА ФАЙЛОВЕТЕ ===")


def pick_session_principle():
    principle = "ГЛАВА 1 – FROM YESTERDAY TO TOMORROW – ПРИНЦИПИ ЗА CORTEX"
    print("\nСЛУЧАЕН ПРИНЦИП ЗА ТАЗИ СЕСИЯ:")
    print(principle)
    append_log(f"Избран принцип за сесията: {principle}")


# ======================================================================
# SELF-IMPROVEMENT + PATCH PROPOSALS
# ======================================================================

def make_patch_proposal_path():
    ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(PATCH_DIR, f"patch_{ts}.txt")


def build_patch_proposal(ts: str, source_log: str, user_inputs: int, errors: int,
                         summaries_ok: int, batch_duration: float,
                         raw_sizes: list, summary_sizes: list) -> str:
    reasons = []
    suggestions = []

    if user_inputs == 0:
        reasons.append("В лога няма интерактивни входове от човека (USER INPUT = 0).")
        suggestions.append(
            "- Да се добави по-ясно съобщение след партидната част, че агентът има интерактивен режим и примерни команди."
        )

    if errors > 0:
        reasons.append(f"В лога има {errors} ред(а) с [ERROR].")
        suggestions.append(
            "- Да се подобри обработката на грешки при четене/запис на файлове и съобщенията към потребителя."
        )

    if summaries_ok > 0:
        reasons.append(f"Успешно създадени резюмета: {summaries_ok}.")

    if batch_duration is not None:
        reasons.append(f"Време за партидната част: {batch_duration:.3f} секунди.")
        suggestions.append(
            "- Да се следи тенденцията на BATCH_DURATION_SEC във времето, за да се откриват забавяния."
        )

    if raw_sizes:
        avg_raw = sum(raw_sizes) / len(raw_sizes)
        reasons.append(f"Среден размер на суровите файлове: {avg_raw:.1f} байта.")
    if summary_sizes:
        avg_sum = sum(summary_sizes) / len(summary_sizes)
        reasons.append(f"Среден размер на резюметата: {avg_sum:.1f} байта.")
        suggestions.append(
            "- Да се анализира дали резюметата не са твърде къси/дълги спрямо суровите файлове."
        )

    if not reasons and not suggestions:
        reasons.append("Логът е кратък и без очевидни индикации за проблеми.")
        suggestions.append(
            "- Да се добави по-фин анализ на поведението (например време за изпълнение, размер на файловете)."
        )

    lines = []
    lines.append("=== PATCH PROPOSAL START ===")
    lines.append(f"TIMESTAMP: {ts}")
    lines.append(f"SOURCE_LOG: {source_log}")
    lines.append("REASONS:")
    for r in reasons:
        lines.append(f"- {r}")
    lines.append("SUGGESTED_CHANGES:")
    for s in suggestions:
        lines.append(f"- {s}")
    lines.append("TARGET_FILE: cortex4_v2.py")
    lines.append("NOTE: Това е само предложение. Човекът решава какво да приложи.")
    lines.append("=== PATCH PROPOSAL END ===")
    lines.append("")

    return "\n".join(lines)


def append_self_improvement_entry(source_log: str):
    ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    user_inputs = 0
    errors = 0
    summaries_ok = 0
    batch_duration = None
    raw_sizes = []
    summary_sizes = []

    try:
        with open(source_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[USER INPUT]"):
                    user_inputs += 1
                if "[ERROR" in line:
                    errors += 1
                if "[OK SUMMARY]" in line:
                    summaries_ok += 1
                if line.startswith("[METRIC] BATCH_DURATION_SEC"):
                    parts = line.split()
                    try:
                        batch_duration = float(parts[-1])
                    except Exception:
                        pass
                if line.startswith("[METRIC] RAW_FILE_SIZE bytes"):
                    parts = line.split()
                    try:
                        size = int(parts[3])
                        raw_sizes.append(size)
                    except Exception:
                        pass
                if line.startswith("[METRIC] SUMMARY_FILE_SIZE bytes"):
                    parts = line.split()
                    try:
                        size = int(parts[3])
                        summary_sizes.append(size)
                    except Exception:
                        pass
    except Exception as e:
        print(f"[ERROR READ LOG FOR REFLECT] {source_log} -> {e}")
        append_log(f"[ERROR READ LOG FOR REFLECT] {source_log} -> {e}")
        return

    strengths = []
    weaknesses = []
    proposed_rule_changes = []
    proposed_code_ideas = []

    if summaries_ok > 0:
        strengths.append(f"Успешно обработени сурови файлове и създадени резюмета: {summaries_ok}.")
    if user_inputs > 0:
        strengths.append(f"Интерактивният режим е използван (USER INPUT записите са {user_inputs}).")
    if batch_duration is not None:
        strengths.append(f"Измерено е време за партидната част: {batch_duration:.3f} секунди.")

    if errors > 0:
        weaknesses.append(f"Има {errors} грешки в лога (ERROR). Нужно е по-добро обработване на изключенията.")
        proposed_code_ideas.append(
            "Да се подобри обработката на грешки при четене/запис на файлове и да се дават по-ясни съобщения към потребителя."
        )

    if user_inputs == 0:
        weaknesses.append("В тази сесия няма интерактивни входове от човека.")
        proposed_rule_changes.append(
            "Да напомня по-ясно на човека за наличието на интерактивен режим, когато партидната част приключи."
        )

    if not strengths and not weaknesses:
        strengths.append(
            "Логът е кратък и без очевидни проблеми. Няма достатъчно данни за по-дълбока рефлексия на този етап."
        )

    goal_alignment_lines = []

    def read_short(path, label, max_chars=400):
        if not os.path.exists(path):
            return f"{label}: няма такъв файл ({path})."
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read().strip()
        except Exception as e:
            return f"{label}: грешка при четене ({e})."
        if not txt:
            return f"{label}: файлът е празен."
        if len(txt) > max_chars:
            return f"{label}: {txt[:max_chars]} ... [съкратено]"
        return f"{label}: {txt}"

    goal_summary_path = os.path.join(BASE_DIR, "goal_summary.txt")
    next_actions_path = os.path.join(BASE_DIR, "next_actions.txt")
    civ_vision_path = os.path.join(BASE_DIR, "civilization_vision.txt")
    code_suggestions_path = os.path.join(BASE_DIR, "code_suggestions.txt")
    self_summary_path = os.path.join(BASE_DIR, "self_summary.txt")

    goal_alignment_lines.append(read_short(goal_summary_path, "GOAL_SUMMARY"))
    goal_alignment_lines.append(read_short(next_actions_path, "NEXT_ACTIONS"))
    goal_alignment_lines.append(read_short(civ_vision_path, "CIVILIZATION_VISION"))
    goal_alignment_lines.append(read_short(code_suggestions_path, "CODE_SUGGESTIONS"))
    goal_alignment_lines.append(read_short(self_summary_path, "SELF_SUMMARY"))

    if summaries_ok > 0:
        goal_alignment_lines.append(
            f"GOAL_NOTE: В тази сесия се работи по {summaries_ok} сурови файла от всички източници. "
            "Това разширява знанието в рамките на наличните сурови файлове."
        )
    else:
        goal_alignment_lines.append(
            "GOAL_NOTE: Няма нови резюмета в тази сесия. Напредъкът към целите вероятно е ограничен."
        )

    if raw_sizes and summary_sizes:
        avg_raw = sum(raw_sizes) / len(raw_sizes)
        avg_sum = sum(summary_sizes) / len(summary_sizes)
        goal_alignment_lines.append(
            f"GOAL_NOTE: Средно резюметата са около {avg_sum:.1f} байта спрямо {avg_raw:.1f} байта суров текст. "
            "Нужно е по-късен анализ дали това ниво на съкращаване е достатъчно за целите."
        )

    lines = []
    lines.append("=== SELF IMPROVEMENT ENTRY START ===")
    lines.append(f"TIMESTAMP: {ts}")
    lines.append(f"SOURCE_LOG: {source_log}")
    lines.append("OBSERVED_STRENGTHS:")
    for s in strengths:
        lines.append(f"- {s}")
    lines.append("OBSERVED_WEAKNESSES:")
    for w in weaknesses:
        lines.append(f"- {w}")
    lines.append("PROPOSED_RULE_CHANGES:")
    for r in proposed_rule_changes:
        lines.append(f"- {r}")
    lines.append("PROPOSED_CODE_IDEAS:")
    for c in proposed_code_ideas:
        lines.append(f"- {c}")
    lines.append("GOAL_ALIGNMENT:")
    for gl in goal_alignment_lines:
        lines.append(f"- {gl}")
    lines.append("=== SELF IMPROVEMENT ENTRY END ===")
    lines.append("")

    try:
        with open(SELF_IMPROVEMENT_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"[REFLECT] Добавен е нов self-improvement блок в {SELF_IMPROVEMENT_FILE}.")
        append_log(f"[REFLECT] Добавен self-improvement блок за лог: {source_log}")
    except Exception as e:
        print(f"[ERROR SELF IMPROVEMENT WRITE] {SELF_IMPROVEMENT_FILE} -> {e}")
        append_log(f"[ERROR SELF IMPROVEMENT WRITE] {SELF_IMPROVEMENT_FILE} -> {e}")

    patch_text = build_patch_proposal(
        ts, source_log, user_inputs, errors, summaries_ok,
        batch_duration, raw_sizes, summary_sizes
    )
    patch_path = make_patch_proposal_path()
    try:
        write_file_safe(patch_path, patch_text)
        print(f"[REFLECT] Създадено е patch предложение: {patch_path}")
        append_log(f"[REFLECT] Създаден patch файл: {patch_path}")
    except Exception as e:
        print(f"[ERROR PATCH WRITE] {patch_path} -> {e}")
        append_log(f"[ERROR PATCH WRITE] {patch_path} -> {e}")


def handle_reflect_last_log():
    if not os.path.exists(CURRENT_LOG_PATH):
        msg = "[REFLECT] Няма cortex4_v2_current.log в history/."
        print(msg)
        append_log(msg)
        return

    print(f"[REFLECT] Използвам текущия лог файл: {CURRENT_LOG_PATH}")
    append_log(f"[REFLECT] Използван лог за самоусъвършенстване: {CURRENT_LOG_PATH}")
    append_self_improvement_entry(CURRENT_LOG_PATH)


# ======================================================================
# ПОМОЩНИ ЗА РЕСУРСНИ РЕЖИМИ (PLANET)
# ======================================================================

def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_json_file(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_snapshot_files_for_domain(domain_dir: Path):
    if not domain_dir.exists():
        return []
    files = []
    for f in sorted(domain_dir.iterdir()):
        if f.is_file() and f.suffix.lower() == ".json":
            files.append(f)
    return files


def build_resource_prompt(domain_name_bg: str,
                          summary_obj: dict | None,
                          snapshot_files: list[Path],
                          extra_context: str = "") -> str:
    lines = []
    lines.append(f"ТИ СИ ВЪТРЕШЕН AGI РЕСУРСЕН АГЕНТ ЗА ДОМЕЙН: {domain_name_bg.upper()}.")
    lines.append("")
    lines.append("ИМАШ СЛЕДНАТА СТРУКТУРА НА ДАННИТЕ (обобщени snapshots + raw JSON файлове).")
    lines.append("ТВОЯТА ЗАДАЧА Е ДА НАПРАВИШ КРАТЪК, НО СТРУКТУРИРАН REVIEW НА СЪСТОЯНИЕТО НА ДОМЕЙНА.")
    lines.append("ФОКУС: ГЛОБАЛНА СТРУКТУРА, НАЙ-ВАЖНИ ИЗТОЧНИЦИ, ОСНОВНИ РИСКОВЕ, ТЕНДЕНЦИИ, ЛИПКИ ИНФОРМАЦИОННИ ДУПКИ.")
    lines.append("ПИШИ НА БЪЛГАРСКИ ЕЗИК. НЕ СИ ИЗМИСЛЯЙ КОНКРЕТНИ ЧИСЛА, АКО ГИ НЯМА В ДАННИТЕ.")
    lines.append("")

    if extra_context:
        lines.append("ДОПЪЛНИТЕЛЕН КОНТЕКСТ ОТ ЧОВЕКА / СИСТЕМАТА:")
        lines.append(extra_context)
        lines.append("")

    if summary_obj is None:
        lines.append("НЯМА ВАЛИДЕН SUMMARY JSON ЗА ТОЗИ ДОМЕЙН.")
    else:
        lines.append("ОБЩ ЕНТРИ ОТ SUMMARY JSON:")
        try:
            run_at = summary_obj.get("run_at")
            active_sources = summary_obj.get("active_sources", 0)
            ok_sources = summary_obj.get("ok_sources", 0)
            failed_sources = summary_obj.get("failed_sources", 0)
            lines.append(f"- run_at: {run_at}")
            lines.append(f"- active_sources: {active_sources}")
            lines.append(f"- ok_sources: {ok_sources}")
            lines.append(f"- failed_sources: {failed_sources}")
        except Exception:
            lines.append("- (грешка при четене на summary полетата)")
    lines.append("")

    if not snapshot_files:
        lines.append("НЯМА JSON SNAPSHOT ФАЙЛОВЕ В ПАПКАТА ЗА ТОЗИ ДОМЕЙН.")
    else:
        lines.append("СПИСЪК ОТ SNAPSHOT JSON ФАЙЛОВЕ:")
        for p in snapshot_files:
            try:
                size = p.stat().st_size
            except Exception:
                size = -1
            lines.append(f"- {p.name} (≈{size} bytes)")
    lines.append("")

    lines.append("СТРУКТУРА НА ОТГОВОРА (ПРИМЕР):")
    lines.append("1) КРАТЪК OVERVIEW НА ДОМЕЙНА (1–2 абзаца)")
    lines.append("2) НАЙ-ВАЖНИ ИЗТОЧНИЦИ И КАКВО ПОКАЗВАТ")
    lines.append("3) ГЛОБАЛНИ ТЕНДЕНЦИИ И РИСКОВЕ")
    lines.append("4) ЛИПКИ ДУПКИ В ДАННИТЕ/ЗНАНИЕТО")
    lines.append("5) КРАТКО ПРЕПОРЪКИ ЗА СЛЕДВАЩИ СТЪПКИ НА AGI СИСТЕМАТА")
    lines.append("")
    lines.append("НА КРАЯ: направи много кратко резюме в 2–3 изречения.")
    lines.append("")

    return "\n".join(lines)


def call_internal_llm_resource(domain_id: str, prompt: str) -> str:
    if not LLM_RESOURCE_SCRIPT.exists():
        return "[ERROR] Няма cortex_llm_resource.py – не мога да викам вътрешния LLM за ресурси."

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    tmp_in = Path(BASE_DIR) / f"tmp_resource_prompt_{domain_id}_{ts}.txt"
    tmp_out = Path(BASE_DIR) / f"tmp_resource_response_{domain_id}_{ts}.txt"

    try:
        tmp_in.write_text(prompt, encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Не мога да запиша временен prompt файл: {e}"

    cmd = f'python3 "{LLM_RESOURCE_SCRIPT}" --domain={domain_id} --input="{tmp_in}" --output="{tmp_out}"'
    try:
        os.system(cmd)
    except Exception as e:
        return f"[ERROR] Грешка при os.system към cortex_llm_resource.py: {e}"

    if not tmp_out.exists():
        return "[ERROR] cortex_llm_resource.py не създаде изходен файл."

    try:
        text = tmp_out.read_text(encoding="utf-8")
    except Exception as e:
        return f"[ERROR] Не мога да прочета изходния файл на LLM: {e}"
    finally:
        try:
            tmp_in.unlink(missing_ok=True)
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass

    return text.strip() if text.strip() else "[WARN] LLM върна празен отговор."


def append_resource_review_to_journal(domain_name_bg: str,
                                      review_text: str,
                                      journal_path: Path,
                                      self_improvement_file: Path):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n\n=== {domain_name_bg.upper()} REVIEW @ {ts} UTC ===\n"

    try:
        with journal_path.open("a", encoding="utf-8") as f:
            f.write(header)
            f.write(review_text)
            f.write("\n")
    except Exception as e:
        print(f"[ERROR] Не мога да пиша в {journal_path}: {e}")

    try:
        with self_improvement_file.open("a", encoding="utf-8") as f:
            f.write("\n=== SELF-IMPROVEMENT ITEM FROM RESOURCE REVIEW ===\n")
            f.write(f"SOURCE: {domain_name_bg.upper()} REVIEW\n")
            f.write(f"TIMESTAMP: {ts}\n")
            f.write("CONTENT:\n")
            f.write(review_text)
            f.write("\n")
    except Exception as e:
        print(f"[ERROR] Не мога да пиша в {self_improvement_file}: {e}")

    print(f"CORTEX++ / {domain_name_bg.upper()} REVIEW: записано в {journal_path.name} и {self_improvement_file.name}.")


def run_planet_review(domain_id: str,
                      domain_name_bg: str,
                      summary_path: Path,
                      snapshots_dir: Path,
                      extra_context: str):
    print(f"CORTEX++ / {domain_name_bg.upper()} REVIEW: стартирам анализ...")

    summary_obj = load_json_file(summary_path)
    if summary_obj is None:
        print(f"CORTEX++ / {domain_name_bg.upper()} REVIEW: няма валидно {summary_path.name}.")
        return

    snapshots = collect_snapshot_files_for_domain(snapshots_dir)
    if not snapshots:
        print(f"CORTEX++ / {domain_name_bg.upper()} REVIEW: няма заредени snapshots за анализ.")
        return

    prompt = build_resource_prompt(domain_name_bg, summary_obj, snapshots, extra_context=extra_context)
    print(f"CORTEX++ / {domain_name_bg.upper()} REVIEW: изпращам заявка към вътрешния LLM...")
    review = call_internal_llm_resource(domain_id, prompt)

    append_resource_review_to_journal(
        domain_name_bg,
        review,
        RESOURCE_JOURNAL_FILE,
        Path(SELF_IMPROVEMENT_FILE),
    )


def cmd_energy_review():
    extra = (
        "Домейн: глобална енергийна система (производство, потребление, емисии, "
        "възобновяеми източници, енергийна ефективност, инфраструктура, достъп до енергия за хората, "
        "ценова достъпност и рискове за сигурността на снабдяването)."
    )
    run_planet_review(
        domain_id="energy",
        domain_name_bg="ENERGY",
        summary_path=ENERGY_SUMMARY_FILE,
        snapshots_dir=ENERGY_SNAPSHOTS_DIR,
        extra_context=extra,
    )


def cmd_water_review():
    extra = (
        "Домейн: глобална водна система (наличност на сладка вода, качество, "
        "водна инфраструктура, замърсяване, достъп до вода за хората, "
        "рискове от засушаване, наводнения и конфликт за водни ресурси)."
    )
    run_planet_review(
        domain_id="water",
        domain_name_bg="WATER",
        summary_path=WATER_SUMMARY_FILE,
        snapshots_dir=WATER_SNAPSHOTS_DIR,
        extra_context=extra,
    )


def cmd_food_review():
    extra = (
        "Домейн: глобална хранителна система (производство на храна, селско стопанство, "
        "достъп до храна, продоволствена сигурност, недохранване и затлъстяване, "
        "екологичен отпечатък на хранителните системи и устойчиви практики)."
    )
    run_planet_review(
        domain_id="food",
        domain_name_bg="FOOD",
        summary_path=FOOD_SUMMARY_FILE,
        snapshots_dir=FOOD_SNAPSHOTS_DIR,
        extra_context=extra,
    )


def cmd_materials_review():
    extra = (
        "Домейн: глобални материали и отпадъци (добив на ресурси, производство на материали, "
        "отпадъци, рециклиране, кръгова икономика, екологични и социални въздействия)."
    )
    run_planet_review(
        domain_id="materials",
        domain_name_bg="MATERIALS & WASTE",
        summary_path=MATERIALS_SUMMARY_FILE,
        snapshots_dir=MATERIALS_SNAPSHOTS_DIR,
        extra_context=extra,
    )


# ======================================================================
# AXIS STATUS / PLAN (SESSION LOGS)
# ======================================================================

def run_axis_status_session():
    """
    Стартира run_session_status.py (ако го има) и връща пътя до последния SESSION_..._LOG.txt
    """
    if not AXIS_RUNNER_SCRIPT.exists():
        msg = f"[AXIS] Няма run_session_status.py в {AXIS_RUNNER_SCRIPT}"
        print(msg)
        append_log(msg)
        return None

    cmd = ["python", str(AXIS_RUNNER_SCRIPT)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        msg = f"[AXIS] Грешка при стартиране на run_session_status.py: {e}"
        print(msg)
        append_log(msg)
        return None

    if result.stdout:
        print(result.stdout.strip())
        append_log(f"[AXIS STATUS STDOUT] {result.stdout.strip().replace(os.linesep, ' ')}")
    if result.stderr:
        append_log(f"[AXIS STATUS STDERR] {result.stderr.strip().replace(os.linesep, ' ')}")

    if not SESSION_LOGS_DIR.exists():
        msg = f"[AXIS] Няма logs/ директория: {SESSION_LOGS_DIR}"
        print(msg)
        append_log(msg)
        return None

    session_logs = sorted(
        [p for p in SESSION_LOGS_DIR.iterdir()
         if p.is_file() and p.name.startswith("SESSION_") and p.name.endswith("_LOG.txt")]
    )
    if not session_logs:
        msg = "[AXIS] Няма SESSION_..._LOG.txt файлове в logs/"
        print(msg)
        append_log(msg)
        return None

    last_log = session_logs[-1]
    append_log(f"[AXIS] Последен SESSION лог: {last_log.name}")
    return last_log


def print_axis_status_summary(log_path: Path, max_axes: int = 20):
    """
    Чете SESSION_..._LOG.txt и печата кратко резюме по оси (AXIS_NAME + ALIGNMENT_SCORE).
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception as e:
        msg = f"[AXIS] Грешка при четене на {log_path}: {e}"
        print(msg)
        append_log(msg)
        return

    lines = text.splitlines()
    axes = []
    current_axis = None
    current_score = None

    for line in lines:
        s = line.strip()
        if s.startswith("AXIS_NAME:"):
            if current_axis is not None:
                axes.append((current_axis, current_score))
            current_axis = s.split("AXIS_NAME:", 1)[1].strip()
            current_score = None
        elif s.startswith("ALIGNMENT_SCORE:"):
            current_score = s.split("ALIGNMENT_SCORE:", 1)[1].strip()

    if current_axis is not None:
        axes.append((current_axis, current_score))

    print("\n=== AXIS STATUS SUMMARY (from SESSION log) ===")
    for i, (name, score) in enumerate(axes[:max_axes], start=1):
        print(f"{i:2d}. {name:35s} ALIGNMENT_SCORE = {score}")
    if len(axes) > max_axes:
        print(f"... и още {len(axes) - max_axes} оси.")
    print("=============================================")


def get_latest_session_log() -> Path | None:
    """
    Намира последния SESSION_..._LOG.txt от logs/ и го връща като Path.
    """
    if not SESSION_LOGS_DIR.exists():
        msg = f"[AXIS PLAN] Няма logs/ директория: {SESSION_LOGS_DIR}"
        print(msg)
        append_log(msg)
        return None

    session_logs = sorted(
        [p for p in SESSION_LOGS_DIR.iterdir()
         if p.is_file() and p.name.startswith("SESSION_") and p.name.endswith("_LOG.txt")]
    )
    if not session_logs:
        msg = "[AXIS PLAN] Няма SESSION_..._LOG.txt файлове в logs/."
        print(msg)
        append_log(msg)
        return None

    last_log = session_logs[-1]
    append_log(f"[AXIS PLAN] Използвам SESSION лог: {last_log.name}")
    return last_log


def show_axis_plan_from_session(log_path: Path):
    """
    Чете TASK_CANDIDATES секцията от подадения SESSION_..._LOG.txt и печата табло със задачи.
    Очакван формат:

    PLAN:
    TASK_CANDIDATES:
    - TASK_ID: ...
      AXIS_NAME: ...
      PRIORITY: HIGH/MEDIUM/LOW
      ALIGNMENT_SCORE: ...
      TASK_DESCRIPTION: ...
    """
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception as e:
        msg = f"[AXIS PLAN] Грешка при четене на {log_path}: {e}"
        print(msg)
        append_log(msg)
        return

    lines = text.splitlines()
    in_plan = False
    in_tasks = False
    tasks = []
    current = {}

    for line in lines:
        s = line.rstrip()

        if s.strip().startswith("PLAN:"):
            in_plan = True
            in_tasks = False
            continue

        if in_plan and s.strip().startswith("NO_TASK_CANDIDATES_FOUND"):
            print("[AXIS PLAN] Няма TASK_CANDIDATES в този SESSION лог.")
            return

        if in_plan and s.strip().startswith("TASK_CANDIDATES:"):
            in_tasks = True
            continue

        if in_plan and in_tasks:
            t = s.strip()
            if t.startswith("- TASK_ID:"):
                if current:
                    tasks.append(current)
                    current = {}
                current["TASK_ID"] = t.split(":", 1)[1].strip()
            elif t.startswith("AXIS_NAME:"):
                current["AXIS_NAME"] = t.split(":", 1)[1].strip()
            elif t.startswith("PRIORITY:"):
                current["PRIORITY"] = t.split(":", 1)[1].strip()
            elif t.startswith("ALIGNMENT_SCORE:"):
                current["ALIGNMENT_SCORE"] = t.split(":", 1)[1].strip()
            elif t.startswith("TASK_DESCRIPTION:"):
                current["TASK_DESCRIPTION"] = t.split(":", 1)[1].strip()

    if current:
        tasks.append(current)

    if not tasks:
        print("[AXIS PLAN] Няма намерени задачи (TASK_CANDIDATES).")
        return

    print("\n=== AXIS PLAN / TASK CANDIDATES (latest SESSION) ===")
    for t in tasks:
        tid = t.get("TASK_ID", "?")
        axis = t.get("AXIS_NAME", "?")
        pr = t.get("PRIORITY", "?")
        sc = t.get("ALIGNMENT_SCORE", "?")
        desc = t.get("TASK_DESCRIPTION", "")
        print(f"{tid} | {pr:6s} | {axis} | {sc} | {desc}")
    print("====================================================")


# ======================================================================
# РЕЖИМИ / КОНФИГ
# ======================================================================

def load_fresco_config():
    global CURRENT_MODE
    config_path = os.path.join(BASE_DIR, "config_fresco_agent.json")
    if not os.path.exists(config_path):
        msg = "[MODE] Няма config_fresco_agent.json в BASE_DIR."
        print(msg)
        append_log(msg)
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        msg = f"[MODE] Грешка при четене на config_fresco_agent.json: {e}"
        print(msg)
        append_log(msg)
        return

    name = cfg.get("agent_name", "FRESCO_DESIGNING_FUTURE_BG")
    desc = cfg.get("description_bg", "Fresco AGI агент за проектиране на устойчиво бъдеще.")
    CURRENT_MODE = {
        "name": name,
        "description": desc,
        "config": cfg,
    }
    print(f"[MODE] Зареден е режим: {name}")
    print(desc)
    append_log(f"[MODE] Зареден режим: {name}")


def show_current_mode():
    print(f"Текущ режим: {CURRENT_MODE.get('name')}")
    print(CURRENT_MODE.get("description"))
    append_log(f"[MODE INFO] {CURRENT_MODE.get('name')}")


# ======================================================================
# ИНТЕРАКТИВЕН РЕЖИМ
# ======================================================================

def interactive_loop():
    print("\nВлизам в интерактивен режим (CORTEX++ балон).")
    print("Напиши команда/въпрос или 'exit' за изход.")
    print("Специални команди:")
    print(" - 'REFLECT LAST_LOG'           – self-improvement и patch от текущия лог.")
    print(" - 'MODE FRESCO'                – зареждане на Fresco конфигурацията (ако има config_fresco_agent.json).")
    print(" - 'SHOW MODE'                  – показване на текущия режим.")
    print("\nPLANET DOMAINS:")
    print(" - 'ENERGY REVIEW'              – енергийна система.")
    print(" - 'WATER REVIEW'               – водни ресурси.")
    print(" - 'FOOD REVIEW'                – храна и хранителни системи.")
    print(" - 'MATERIALS & WASTE REVIEW'   – материали, отпадъци, кръгова икономика.")
    print("\nAXIS / CIVILIZATION:")
    print(" - 'AXIS STATUS'                – прави REVIEW по оси и създава SESSION_..._LOG.")
    print(" - 'AXIS PLAN SHOW'             – показва TASK_CANDIDATES от последния SESSION лог.")
    print(" - 'AXIS PLAN EXECUTE ONCE'     – избира по 1 задача на ос от последния SESSION и я логва.")
    print("\n(Останалите HUMAN / CIVILIZATION / COSMOS домейни още не са имплементирани в този файл.)")

    append_log("[INFO] Стартиран е интерактивният режим на CORTEX4_V2.")

    while True:
        try:
            user_input = input("CORTEX++> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nИзход от интерактивен режим.")
            append_log("[INFO] Прекъснат интерактивен режим (EOF/KeyboardInterrupt).")
            break

        if user_input.lower() in ("exit", "quit", "q"):
            print("Изход от CORTEX++ интерактивния режим.")
            append_log("[INFO] exit/quit от интерактивния режим.")
            break

        if not user_input:
            continue

        append_log(f"[USER INPUT] {user_input}")
        cmd = user_input.upper()

        # SELF-IMPROVEMENT
        if cmd == "REFLECT LAST_LOG":
            handle_reflect_last_log()
            continue

        # MODES
        if cmd == "SHOW MODE":
            show_current_mode()
            continue
        if cmd.startswith("MODE"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                modename = parts[1].strip().upper()
            else:
                modename = ""
            if modename == "FRESCO":
                load_fresco_config()
            else:
                msg = f"[MODE] Непознат режим: {modename}. Използвай 'MODE FRESCO'."
                print(msg)
                append_log(msg)
            continue

        # PLANET DOMAINS
        if cmd == "ENERGY REVIEW":
            cmd_energy_review()
            continue
        if cmd == "WATER REVIEW":
            cmd_water_review()
            continue
        if cmd == "FOOD REVIEW":
            cmd_food_review()
            continue
        if cmd == "MATERIALS & WASTE REVIEW":
            cmd_materials_review()
            continue

        # AXIS STATUS / PLAN
        if cmd == "AXIS STATUS":
            log_path = run_axis_status_session()
            if log_path is not None:
                print_axis_status_summary(log_path)
            continue

        if cmd == "AXIS PLAN SHOW":
            log_path = get_latest_session_log()
            if log_path is not None:
                show_axis_plan_from_session(log_path)
            continue

        if cmd == "AXIS PLAN EXECUTE ONCE":
            os.system('python axis_task_executor.py')
            continue

        # FALLBACK
        response = (
            "Все още нямам реална логика за свободни интерактивни задачи.\n"
            "На този етап разбирам само специфичните команди от менюто по-горе.\n"
            "Използвай някоя от тях (например 'ENERGY REVIEW', 'WATER REVIEW', "
            "'FOOD REVIEW', 'MATERIALS & WASTE REVIEW', 'AXIS STATUS', 'AXIS PLAN SHOW', "
            "'AXIS PLAN EXECUTE ONCE')."
        )
        print(response)
        append_log(f"[AGENT RESPONSE] {response.replace(os.linesep, ' ')}")


# ======================================================================
# MAIN
# ======================================================================

def main():
    ensure_dirs()

    if os.path.exists(CURRENT_LOG_PATH):
        try:
            os.remove(CURRENT_LOG_PATH)
        except Exception:
            pass

    print("Cortex 4 v2 – многoизточников Fresco/AGI агент с домейн режими човек–планета–цивилизация–космос.")
    append_log("[INFO] Старт на Cortex4_v2 сесия.")

    load_control_rules()

    print("\n1) Зареждам принципите от Jacque Fresco (глави 1–3)...")
    append_log("[INFO] Зареждане на принципи (Jacque Fresco ch1–3).")
    pick_session_principle()

    print("\n2) Генерирам автоматични резюмета за суровите глави в 01_raw от всички източници...")
    process_all_sources_and_summarize()

    print("\nКрай на партидната част на Cortex 4 v2.")
    for src in SOURCES:
        print(f"Източник '{src['name']}':")
        print(f"  RAW : {src['raw_dir']}")
        print(f"  SUM : {src['summary_dir']}")
    print(f"Файл с принципи (очакван):  {PRINCIPLES_FILE}")

    append_log("[INFO] Край на партидната част. Преминаване към интерактивен режим.")

    interactive_loop()

    append_log("[INFO] Край на CORTEX4_V2 сесия.")


if __name__ == "__main__":
    main()

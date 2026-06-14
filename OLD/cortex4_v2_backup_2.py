import os
import configparser
import time
import json
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
    # В бъдеще можеш да добавяш тук още източници:
    # {
    #     "name": "science",
    #     "raw_dir": os.path.join(BASE_DIR, "knowledge", "science", "01_raw"),
    #     "summary_dir": os.path.join(BASE_DIR, "knowledge", "science", "02_summary_bg"),
    # },
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

# === ДОМЕЙН КОНСТАНТИ ЗА ENERGY И WATER ===
KNOWLEDGE_DIR = Path(BASE_DIR) / "knowledge"

# Energy domain
ENERGY_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "energy_snapshots"
ENERGY_SUMMARY_FILE = ENERGY_SNAPSHOTS_DIR / "energy_query_summary.json"
ENERGY_JOURNAL_FILE = Path(BASE_DIR) / "journal_resource_act.txt"

# Water domain
WATER_SNAPSHOTS_DIR = KNOWLEDGE_DIR / "water_snapshots"
WATER_SUMMARY_FILE = WATER_SNAPSHOTS_DIR / "water_query_summary.json"
WATER_JOURNAL_FILE = Path(BASE_DIR) / "journal_resource_act.txt"  # споделен журнал

# Общ self_improvement файл вече имаш: SELF_IMPROVEMENT_FILE

# === LLM GATEWAY (локален cortex_llm_resource.py) ===
LLM_RESOURCE_SCRIPT = Path(BASE_DIR) / "cortex_llm_resource.py"


def ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    for src in SOURCES:
        os.makedirs(src["raw_dir"], exist_ok=True)
        os.makedirs(src["summary_dir"], exist_ok=True)
    # директории за energy/water snapshots
    ENERGY_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    WATER_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


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


# === ЧЕТЕНЕ НА ПРАВИЛАТА ОТ cortex_control.rules ===

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


# === РАБОТА СЪС ЗНАНИЕТО ===

def list_raw_files_for_source(raw_dir: str):
    """Намира суровите файлове в дадена 01_raw папка."""
    if not os.path.exists(raw_dir):
        return []
    files = [
        f
        for f in os.listdir(raw_dir)
        if os.path.isfile(os.path.join(raw_dir, f)) and f.endswith("_raw.txt")
    ]
    return sorted(files)


def auto_summarize(text: str) -> str:
    """
    Място за реална логика на резюме.
    Засега: връщаме първите ~500 символа като „авторезюме“.
    """
    text = text.strip()
    if len(text) <= 500:
        return text
    return text[:500] + "\n...\n[автоматично съкратено]"


def process_all_sources_and_summarize():
    """
    Обработва всички SOURCES:
    - за всеки източник намира *_raw.txt в неговата 01_raw,
    - прави авто-резюмета в съответната 02_summary_bg,
    - логва метрики поотделно, без конфликт при еднакви имена на файлове,
      защото всеки източник си има собствена изходна папка.
    """
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
    """
    Символично място за изтегляне на „принцип за сесията“.
    Засега: просто твърд текст + лог.
    """
    principle = "ГЛАВА 1 – FROM YESTERDAY TO TOMORROW – ПРИНЦИПИ ЗА CORTEX"
    print("\nСЛУЧАЕН ПРИНЦИП ЗА ТАЗИ СЕСИЯ:")
    print(principle)
    append_log(f"Избран принцип за сесията: {principle}")


# === PATCH ПРОПОЗИЦИИ ===

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


# === SELF-IMPROVEMENT + GOAL_ALIGNMENT ===

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


# === НОВИ ПОМОЩНИ ФУНКЦИИ ЗА RESOURCE REVIEW (ENERGY + WATER) ===

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


def load_energy_snapshots_summary():
    return load_json_file(ENERGY_SUMMARY_FILE)


def load_water_snapshots_summary():
    return load_json_file(WATER_SUMMARY_FILE)


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
    """
    Строи prompt за вътрешния ресурсен LLM за даден домейн (energy/water).
    """
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

    # Обобщение на summary файла
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

    # Списък на snapshot файловете
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
    """
    Вика cortex_llm_resource.py в режим за даден домейн (energy/water), като му подава prompt.
    Очаква stdout като текст за директно ползване.
    """
    if not LLM_RESOURCE_SCRIPT.exists():
        return "[ERROR] Няма cortex_llm_resource.py – не мога да викам вътрешния LLM за ресурси."

    # Ще подадем prompt-а през временен файл, за да избегнем проблеми с кавички.
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
    """
    Записва resource review (energy/water) в journal_resource_act.txt и в self_improvement_suggestions.txt.
    """
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n\n=== {domain_name_bg.upper()} REVIEW @ {ts} UTC ===\n"

    # Journal
    try:
        with journal_path.open("a", encoding="utf-8") as f:
            f.write(header)
            f.write(review_text)
            f.write("\n")
    except Exception as e:
        print(f"[ERROR] Не мога да пиша в {journal_path}: {e}")

    # Self-improvement
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


# === КОМАНДИ ЗА ENERGY REVIEW ===

def cmd_energy_review():
    """
    Анализ на енергийния домейн, използвайки energy_query_summary.json + JSON snapshot-и.
    """
    print("CORTEX++ / ENERGY REVIEW: стартирам анализ на енергийния домейн...")

    summary_obj = load_energy_snapshots_summary()
    if summary_obj is None:
        print("CORTEX++ / ENERGY REVIEW: няма валидно energy_query_summary.json.")
        return

    snapshots = collect_snapshot_files_for_domain(ENERGY_SNAPSHOTS_DIR)
    if not snapshots:
        print("CORTEX++ / ENERGY REVIEW: няма заредени snapshots за анализ.")
        return

    extra = (
        "Домейн: глобална енергийна система (производство, потребление, "
        "емисии, възобновяеми източници, инфраструктура, рискове, достъпност за хората)."
    )
    prompt = build_resource_prompt("ENERGY", summary_obj, snapshots, extra_context=extra)
    print("CORTEX++ / ENERGY REVIEW: изпращам заявка към вътрешния LLM...")
    review = call_internal_llm_resource("energy", prompt)

    append_resource_review_to_journal(
        "ENERGY",
        review,
        ENERGY_JOURNAL_FILE,
        Path(SELF_IMPROVEMENT_FILE),
    )


# === КОМАНДИ ЗА WATER REVIEW ===

def cmd_water_review():
    """
    Анализ на водния домейн, използвайки water_query_summary.json + JSON snapshot-и.
    Очакваме да имаш отделен water_query_all.py, който попълва knowledge/water_snapshots/.
    """
    print("CORTEX++ / WATER REVIEW: стартирам анализ на водния домейн...")

    summary_obj = load_water_snapshots_summary()
    if summary_obj is None:
        print("CORTEX++ / WATER REVIEW: няма валидно water_query_summary.json.")
        return

    snapshots = collect_snapshot_files_for_domain(WATER_SNAPSHOTS_DIR)
    if not snapshots:
        print("CORTEX++ / WATER REVIEW: няма заредени water snapshots за анализ.")
        return

    extra = (
        "Домейн: глобална водна система (наличност на сладка вода, качество, "
        "водна инфраструктура, замърсяване, достъп до вода за хората, рискове от недостиг)."
    )
    prompt = build_resource_prompt("WATER", summary_obj, snapshots, extra_context=extra)
    print("CORTEX++ / WATER REVIEW: изпращам заявка към вътрешния LLM...")
    review = call_internal_llm_resource("water", prompt)

    append_resource_review_to_journal(
        "WATER",
        review,
        WATER_JOURNAL_FILE,
        Path(SELF_IMPROVEMENT_FILE),
    )


# === РЕЖИМИ / КОНФИГИ В ИНТЕРАКТИВНИЯ РЕЖИМ ===

def load_fresco_config():
    """
    Зарежда config_fresco_agent.json (ако съществува) и обновява CURRENT_MODE.
    """
    global CURRENT_MODE
    config_path = os.path.join(BASE_DIR, "config_fresco_agent.json")
    if not os.path.exists(config_path):
        msg = f"[MODE] Няма config_fresco_agent.json в {BASE_DIR}."
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
    desc = cfg.get("description_bg", "Fresco агент на български.")
    CURRENT_MODE = {
        "name": name,
        "description": desc,
        "config": cfg,
    }
    print(f"[MODE] Активиран е режим: {name}")
    print(f"[MODE] Описание: {desc}")
    append_log(f"[MODE] Активиран режим: {name}")


def show_current_mode():
    """
    Показва текущия режим на ядрото.
    """
    print(f"Текущ режим: {CURRENT_MODE.get('name')}")
    print(f"Описание   : {CURRENT_MODE.get('description')}")
    append_log(f"[MODE INFO] {CURRENT_MODE.get('name')}")


# === ИНТЕРАКТИВЕН РЕЖИМ ===

def interactive_loop():
    print("\nВлизам в интерактивен режим (CORTEX++ балон).")
    print("Напиши команда/въпрос или 'exit' за изход.")
    print("Специални команди:")
    print(" - 'REFLECT LAST_LOG' за self-improvement и patch.")
    print(" - 'MODE FRESCO' за зареждане на Fresco конфигурацията (ако има config_fresco_agent.json).")
    print(" - 'SHOW MODE' за показване на текущия режим.")
    print(" - 'ENERGY REVIEW' за анализ на енергийния домейн.")
    print(" - 'WATER REVIEW' за анализ на водния домейн.\n")

    append_log("=== СТАРТ НА ИНТЕРАКТИВЕН РЕЖИМ ===")

    while True:
        try:
            user_input = input("CORTEX++> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ИНФО] Прекъсване от потребителя. Излизам от интерактивен режим.")
            append_log("[ИНФО] Прекъсване от потребителя в интерактивен режим.")
            break

        if user_input.lower() in ("exit", "quit", "q"):
            print("Излизам от интерактивен режим.")
            append_log("Потребителят избра exit/quit. Край на интерактивния режим.")
            break

        if not user_input:
            continue

        append_log(f"[USER INPUT] {user_input}")

        # Специални команди
        if user_input.upper() == "REFLECT LAST_LOG":
            handle_reflect_last_log()
            continue

        if user_input.upper() == "SHOW MODE":
            show_current_mode()
            continue

        if user_input.upper().startswith("MODE "):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 2:
                mode_name = parts[1].strip().upper()
            else:
                mode_name = ""

            if mode_name == "FRESCO":
                load_fresco_config()
            else:
                msg = f"[MODE] Непознат режим: {mode_name}. Засега поддържам само 'MODE FRESCO'."
                print(msg)
                append_log(msg)
            continue

        if user_input.upper() == "ENERGY REVIEW":
            cmd_energy_review()
            continue

        if user_input.upper() == "WATER REVIEW":
            cmd_water_review()
            continue

        # TODO: бъдещата реална логика за режими ще стъпва на CURRENT_MODE и конфигурацията.
        response = (
            "Все още нямам реална логика за обработка на общи интерактивни задачи.\n"
            "На този етап само логвам входа ти и връщам това съобщение.\n"
            "Специално: можеш да използваш командите 'REFLECT LAST_LOG', 'MODE FRESCO', "
            "'SHOW MODE', 'ENERGY REVIEW' и 'WATER REVIEW'."
        )

        print(response)
        append_log(f"[AGENT RESPONSE] {response.replace(os.linesep, ' ')}")

    append_log("=== КРАЙ НА ИНТЕРАКТИВЕН РЕЖИМ ===")


# === MAIN ===

def main():
    ensure_dirs()

    if os.path.exists(CURRENT_LOG_PATH):
        try:
            os.remove(CURRENT_LOG_PATH)
        except Exception:
            pass

    print("Cortex 4 v2 – многoизточников Fresco/AGI агент с локални файлове + лог в history.\n")

    append_log("Стъпка 0: зареждане на контролни правила от cortex_control.rules.")
    load_control_rules()

    print("\n1) Зареждам принципите от Jacque Fresco (глави 1–3)...")
    append_log("Стъпка 1: зареждане/избор на принцип за сесията.")
    pick_session_principle()

    print("\n2) Генерирам автоматични резюмета за суровите глави в 01_raw от всички източници...\n")
    append_log("Стъпка 2: започвам автоматично резюмиране на суровите глави в 01_raw (всички източници).")
    process_all_sources_and_summarize()

    print("\nКрай на партидната част на Cortex 4 v2.")
    for src in SOURCES:
        print(f"Източник '{src['name']}':")
        print(f"  RAW : {src['raw_dir']}")
        print(f"  SUM : {src['summary_dir']}")
    print("Файл с принципи (очакван): ", PRINCIPLES_FILE)

    append_log("Край на партидната част на Cortex 4 v2.")
    for src in SOURCES:
        append_log(f"[SOURCE_DIRS] {src['name']} RAW={src['raw_dir']} SUM={src['summary_dir']}")
    append_log(f"Очакван файл с принципи: {PRINCIPLES_FILE}")

    interactive_loop()

    append_log("Край на изпълнението на Cortex 4 v2 (вкл. интерактивен режим).")
    append_log("=== КРАЙ НА CORTEX4_V2 СЕСИЯ ===")


if __name__ == "__main__":
    main()

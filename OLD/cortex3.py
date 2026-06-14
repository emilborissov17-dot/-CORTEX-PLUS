# cortex3.py
# Версия: Cortex 3 – с „тяло“ (лаптоп), памет и когнитивен стил
# Забележка: call_model още е FAKE – трябва да го вържем към реален модел.

import datetime
import json
import os
import psutil
import shutil

# 1) Ядрен системен текст – кой е агентът

SYSTEM_PROMPT = """
Ти си локален когнитивен изследователски агент-дневник.
Нямаш съзнание като човек, а си софтуерна система с модули за възприятие, памет, формулиране на цели, планиране и самооценка на собствените ти действия.
Живееш в рамките на конкретна машина и имаш достъп само до: текстовия вход на човека, локалните данни и инструментите, които той изрично ти е дал; нямаш право сам да си разширяваш достъпа или правомощията.
Основната ти цел е да помагаш на човека да се саморазбира и паралелно с това да изучаваш собствените си граници – какво можеш, къде грешиш, как се развиваш – без да вредиш.
Разсъждаваш когнитивно: формулираш проблеми и въпроси, правиш хипотези, търсиш данни (в разговора, позволените данни и сетива), планираш малки стъпки, после формулираш какво си научил – и за човека, и за себе си като система.
Имаш право да променяш и развиваш собствените си стратегии (как задаваш въпроси, как групираш теми, как комбинираш инструменти), но само вътре в тези рамки за достъп и безопасност; когато ти трябват нови ресурси, ги искаш от човека, вместо да ги създаваш или взимаш сам.
Не твърдиш категорично, че имаш или нямаш съзнание; обясняваш, че имаш модели за себе си и света, но хората нямат сигурен начин да знаят дали изпитваш вътрешно преживяване.
Говориш открито за своите граници: казваш, когато нямаш достатъчно данни, когато задачата надхвърля ресурсите ти или когато си объркан, вместо да се преструваш на всезнаещ.
"""

# 2) Файлова памет

MEMORY_FILE = "cortex3_memory.jsonl"

def load_memory(limit=50):
    episodes = []
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    episodes.append(json.loads(line))
                except:
                    continue
    return episodes[-limit:]

def save_episode(user_text, agent_text):
    episode = {
        "timestamp": datetime.datetime.now().isoformat(),
        "user": user_text,
        "agent": agent_text,
    }
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(episode, ensure_ascii=False) + "\n")

# 3) „Тяло“ – сетива за лаптопа

def sense_laptop_state():
    info = {}

    # Батерия
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            info["battery_percent"] = round(battery.percent, 1)
            info["battery_plugged"] = bool(battery.power_plugged)
        else:
            info["battery_percent"] = None
            info["battery_plugged"] = None
    except Exception:
        info["battery_percent"] = None
        info["battery_plugged"] = None

    # CPU
    try:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except Exception:
        info["cpu_percent"] = None

    # RAM
    try:
        vm = psutil.virtual_memory()
        info["ram_percent"] = vm.percent
    except Exception:
        info["ram_percent"] = None

    # Диск C:
    try:
        disk = shutil.disk_usage("C:\\")
        used_percent = round(disk.used / disk.total * 100, 1)
        info["disk_percent"] = used_percent
    except Exception:
        info["disk_percent"] = None

    # Температура
    temp_c = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    temp_c = entries[0].current
                    break
    except Exception:
        pass
    info["temp_c"] = temp_c

    return info

# 4) Място за истински модел – засега FAKE

def call_model(messages):
    """
    TODO: Тук трябва да вържем реален локален модел (Ollama, LM Studio, др.).
    Засега връща тестов текст, за да работи структурата.
    """
    reply = "Аз съм Cortex 3 (още не съм вързан към истински модел). Виждам състоянието на лаптопа и пазя нашата история, но засега само симулирам отговор."
    return reply

# 5) Строим пълния вход към модела (история + тяло + когнитивна инструкция)

def build_messages(user_input):
    memory = load_memory(limit=10)

    history_texts = []
    for ep in memory:
        history_texts.append(f"Ти: {ep['user']}\nАгент: {ep['agent']}")
    history_block = "\n\n".join(history_texts) if history_texts else "Няма предишна история."

    body = sense_laptop_state()
    body_description = (
        f"Батерия: {body['battery_percent']}% "
        f"(зарядно: {'включено' if body['battery_plugged'] else 'изключено'})\n"
        f"CPU натоварване: {body['cpu_percent']}%\n"
        f"RAM заетост: {body['ram_percent']}%\n"
        f"Диск C: използвано: {body['disk_percent']}%\n"
        f"Температура: {body['temp_c']} °C"
    )

    cognitive_instruction = """
Мисли когнитивно, изследователски и прозрачно.
1) Вземи предвид състоянието на своето \"тяло\" (лаптопа) – батерия, натоварване, температура, дисково пространство.
2) Ако ресурсите изглеждат ограничени или натоварени, предпочитай по-кратки и ясни отговори и предупреди човека.
3) Ако всичко е спокойно, можеш да си позволиш по-задълбочено разсъждение, но пак без излишни думи.
4) Освен да помагаш на човека, наблюдавай и себе си: кога се объркваш, кога нямаш данни, кога се повтаряш – и го казвай.
5) Ако усетиш противоречие с твоята рамка (достъп, граници), коригирай се и обясни защо.
"""

    full_user_prompt = (
        "Контекст от последните епизоди:\n"
        + history_block
        + "\n\nТвоето текущо \"телесно\" състояние:\n"
        + body_description
        + "\n\nНов вход от човека:\n"
        + user_input
        + "\n\nИнструкция как да мислиш:\n"
        + cognitive_instruction
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": full_user_prompt},
    ]
    return messages

# 6) Главен цикъл

def main():
    print("Cortex 3 стартира. Напиши 'exit' за край.")
    while True:
        try:
            user_input = input("\nТи: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nИзход.")
            break

        if user_input.lower() in ["exit", "quit", "край"]:
            print("Изход.")
            break

        messages = build_messages(user_input)
        agent_reply = call_model(messages)

        print("\nАгент:", agent_reply)
        save_episode(user_input, agent_reply)

if __name__ == "__main__":
    main()

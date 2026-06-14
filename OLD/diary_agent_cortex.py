import json
from datetime import datetime

# ------- Импорт на Cortex-1 като „мозък“ -------

from cortex1 import CortexAgent  # очакваме cortex1.py да е в същата папка


class DiaryAgent:
    def __init__(self, memory_file="agent_memory.json"):
        self.memory_file = memory_file
        self.memories = []
        self.load_memory()

    def load_memory(self):
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                self.memories = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.memories = []

    def save_memory(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)

    def add_entry(self, user_input, agent_response, inner_thoughts=None):
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "user_input": user_input,
            "agent_response": agent_response,
        }
        if inner_thoughts is not None:
            entry["cortex_inner_thoughts"] = inner_thoughts
        self.memories.append(entry)
        self.save_memory()

    def summarize_recent(self, n=5):
        recent = self.memories[-n:]
        if not recent:
            return "Все още нямам спомени."

        topics = []
        for e in recent:
            topics.append(e["user_input"])
        summary = "В последните ми взаимодействия говорихме за: " + "; ".join(topics)
        return summary


def cortex_agent_reply(user_input, cortex: CortexAgent, diary: DiaryAgent):
    text = user_input.strip().lower()

    # специална команда към дневника
    if text in ["изход", "exit", "quit"]:
        return "Благодаря ти за разговора. Ще запазя този момент в паметта си.", []

    if "какво помниш" in text or "спомени" in text:
        summary = diary.summarize_recent()
        return summary, []

    # тук вече използваме Cortex-1 като мозък
    response_text, reflection_comment, inner_thoughts = cortex.step(user_input)

    # добавяме и рефлексията към вътрешните мисли, за да се пази в дневника
    inner_full = list(inner_thoughts)
    inner_full.append(f"[Рефлексия: {reflection_comment}]")

    return response_text, inner_full


def main():
    diary = DiaryAgent()
    cortex = CortexAgent()

    print("Дневник‑агент (с Cortex-1): Можеш да ми пишеш, аз ще помня нашите разговори локално.")
    print('Напиши "изход" за край.\n')

    while True:
        user_input = input("Ти: ")

        reply, inner_thoughts = cortex_agent_reply(user_input, cortex, diary)
        diary.add_entry(user_input, reply, inner_thoughts if inner_thoughts else None)

        print("Агент:", reply)
        if inner_thoughts:
            print("[Вътрешни мисли на агента (Cortex-1) – записани и в дневника:]")
            for t in inner_thoughts:
                print("- " + t)

        if user_input.strip().lower() in ["изход", "exit", "quit"]:
            break


if __name__ == "__main__":
    main()

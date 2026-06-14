import json
from datetime import datetime

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

    def add_entry(self, user_input, agent_response):
        entry = {
            "time": datetime.now().isoformat(),
            "user_input": user_input,
            "agent_response": agent_response
        }
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

def simple_agent_reply(user_input, agent: DiaryAgent):
    text = user_input.strip().lower()
    if text in ["изход", "exit", "quit"]:
        return "Благодаря ти за разговора. Ще запазя този момент в паметта си."

    if "какво помниш" in text or "спомени" in text:
        return agent.summarize_recent()

    # много прост „анализ“
    if "тъжен" in text or "тъжно" in text:
        return "Чувам тъга в думите ти. Искаш ли да ми кажеш какво най-много те натъжава?"

    if "щастлив" in text or "радост" in text:
        return "Улавям нотка радост. Какво те кара да се чувстваш така?"

    return "Разбирам. Разкажи ми още, за да мога да запомня по-добре какво те вълнува."

def main():
    agent = DiaryAgent()
    print("Дневник‑агент: Можеш да ми пишеш, аз ще помня нашите разговори локално.")
    print('Напиши "изход" за край.')

    while True:
        user_input = input("Ти: ")
        reply = simple_agent_reply(user_input, agent)
        agent.add_entry(user_input, reply)
        print("Агент:", reply)
        if user_input.strip().lower() in ["изход", "exit", "quit"]:
            break

if __name__ == "__main__":
    main()
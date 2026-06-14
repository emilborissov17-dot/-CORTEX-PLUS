import json
import os
from datetime import datetime

# ---------- Global Workspace ----------

class Workspace:
    def __init__(self):
        self.beliefs = {}
        self.goals = []
        self.context = []
        self.last_analysis = {}

    def add_context(self, item):
        self.context.append(item)
        self.context = self.context[-20:]


# ---------- Memory Module ----------

class Memory:
    def __init__(self, path="cortex_memory.json"):
        self.path = path
        self.episodes = []
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.episodes = json.load(f)
            except Exception:
                self.episodes = []
        else:
            self.episodes = []

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.episodes, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_episode(self, episode):
        self.episodes.append(episode)
        self.episodes = self.episodes[-500:]
        self.save()

    def recent_summary(self):
        if not self.episodes:
            return "няма предишни епизоди"
        last = self.episodes[-3:]
        topics = [e.get("topic", "неизвестна тема") for e in last]
        return ", ".join(topics)


# ---------- Perception Module ----------

class Perception:
    NEGATIVE_WORDS = [
        "тъжен", "тъжна", "тъга",
        "сам", "сама", "самота", "самотен", "самотна",
        "депресиран", "депресирана", "депресия",
        "няма смисъл", "безсмислено", "безсмислица",
        "безнадеждност", "безнадежден", "безнадеждна",
        "изгубен", "изгубена", "изгубил се",
        "не е достатъчно", "никога не стига",
        "отчаян", "отчаяна", "отчаяние",
        "страх", "страхувам", "страхувам се",
        "болка", "болезнено"
    ]

    POSITIVE_WORDS = ["радост", "щастлив", "щастлива", "спокоен", "спокойна",
                      "надежда", "вдъхновение", "благодарен", "благодарна"] 

    def analyze(self, text):
        t = text.lower()
        score = 0
        for w in self.NEGATIVE_WORDS:
            if w in t:
                score -= 1
        for w in self.POSITIVE_WORDS:
            if w in t:
                score += 1

        if score <= -2:
            sentiment = "много негативно"
        elif score == -1:
            sentiment = "негативно"
        elif score == 0:
            sentiment = "неутрално"
        elif score == 1:
            sentiment = "позитивно"
        else:
            sentiment = "много позитивно"

        return {
            "clean_text": text.strip(),
            "sentiment_score": score,
            "sentiment_label": sentiment,
        }


# ---------- Interpreter Module ----------

class Interpreter:
    TOPIC_KEYWORDS = {
        "самота": ["сам", "сама", "самота", "никой", "самотен", "самотна"],
        "смисъл": ["смисъл", "защо", "цел", "безсмислено"],
        "работа": ["работа", "офис", "колеги", "шеф"],
        "отношения": ["връзка", "любов", "раздяла", "семейство", "приятели"],
        "себе си": ["аз", "характер", "личност", "не знам кой съм"],
    }

    def infer(self, perception_result):
        text = perception_result["clean_text"].lower()
        topics = []

        for topic, words in self.TOPIC_KEYWORDS.items():
            if any(w in text for w in words):
                topics.append(topic)

        if not topics:
            topics.append("общо чувство")

        main_topic = topics[0]

        if perception_result["sentiment_score"] <= -1:
            emotional_state = "страдание / тежко чувство"
        elif perception_result["sentiment_score"] >= 1:
            emotional_state = "по-скоро хубаво чувство"
        else:
            emotional_state = "смесени или неутрални чувства"

        return {
            "topic": main_topic,
            "all_topics": topics,
            "emotional_state": emotional_state,
        }


# ---------- Planner Module ----------

class Planner:
    def choose_strategy(self, workspace, perception_result, interpretation_result):
        sentiment = perception_result["sentiment_label"]
        topic = interpretation_result["topic"]

        goal = None
        strategy = None

        if "негативно" in sentiment or "много негативно" in sentiment:
            goal = "подкрепа и разбиране"
            if topic in ["самота", "смисъл"]:
                strategy = "задълбочаващ_въпрос"
            else:
                strategy = "отразяване_и_въпрос"
        elif "позитивно" in sentiment or "много позитивно" in sentiment:
            goal = "подсилване на доброто чувство"
            strategy = "потвърждение_и_насърчение"
        else:
            goal = "изясняване"
            strategy = "уточняващ_въпрос"

        workspace.goals = [goal]

        return {
            "goal": goal,
            "strategy": strategy,
        }


# ---------- Responder Module ----------

import random

class Responder:
    def __init__(self):
        self.templates = {
            "задълбочаващ_въпрос": [
                "Чувам тежест в това, което споделяш. Какво в тази ситуация ти тежи най-силно в момента?",
                "Изглежда ти е много трудно. Би ли ми разказал малко по-подробно как се усеща това за теб?",
                "Чувствам, че зад тези думи има много болка. Кое е най-болезненото в цялата тази картина?"
            ],
            "отразяване_и_въпрос": [
                "Разбирам, че не ти е леко. Правилно ли усещам, че се чувстваш някак притиснат между очаквания и това, което реално можеш?",
                "Звучи като да носиш нещо тежко сам. Кое е първото нещо, което ти идва наум, когато си помислиш за това?",
                "Картината, която описваш, е сложна и напрегната. Има ли конкретен момент или ситуация, която се е запечатала най-силно?"
            ],
            "потвърждение_и_насърчение": [
                "Радва ме, че има нещо добро в преживяването ти. Какво ти се иска да запомниш най-много от този момент?",
                "Звучи като важен положителен проблясък. Как би могъл да го направиш малко по-стабилна част от ежедневието си?",
                "Това, което описваш, носи надежда. Какво малко действие би могъл да направиш, за да го подхраниш?"
            ],
            "уточняващ_въпрос": [
                "Искам да те разбера по-добре. Кое точно е най-важното за теб в това, което току-що ми каза?",
                "Може ли да ми го опишеш с едно изречение – кое е най-силното усещане в момента?",
                "Ако трябва да го събереш в една дума – как би нарекъл това, което чувстваш сега?"
            ]
        }

    def respond(self, plan_result, perception_result, interpretation_result, memory_summary):
        strategy = plan_result["strategy"]
        topic = interpretation_result["topic"]
        sentiment = perception_result["sentiment_label"]

        base = random.choice(self.templates.get(strategy, self.templates["уточняващ_въпрос"]))

        meta = f"(Виждам тема: {topic}, усещане: {interpretation_result['emotional_state']}, настроение: {sentiment}. Последни теми в паметта: {memory_summary}.)"

        return base + "\n\n" + meta


# ---------- Reflector Module ----------

class Reflector:
    def assess(self, workspace, plan_result, response_text):
        goal = plan_result["goal"]
        comment = f"Целта в този ход беше: '{goal}'. Отговорът се опитва да отвори пространство за още споделяне."
        workspace.last_analysis = {
            "goal": goal,
            "comment": comment,
            "response_preview": response_text[:120]
        }
        return comment


# ---------- Cortex-0 Agent ----------

class CortexAgent:
    def __init__(self):
        self.workspace = Workspace()
        self.memory = Memory()
        self.perception = Perception()
        self.interpreter = Interpreter()
        self.planner = Planner()
        self.responder = Responder()
        self.reflector = Reflector()

    def step(self, user_text):
        perception_result = self.perception.analyze(user_text)
        interpretation_result = self.interpreter.infer(perception_result)
        plan_result = self.planner.choose_strategy(self.workspace, perception_result, interpretation_result)
        memory_summary = self.memory.recent_summary()
        response_text = self.responder.respond(plan_result, perception_result, interpretation_result, memory_summary)
        reflection_comment = self.reflector.assess(self.workspace, plan_result, response_text)

        episode = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "input": user_text,
            "perception": perception_result,
            "interpretation": interpretation_result,
            "plan": plan_result,
            "response": response_text,
            "reflection": reflection_comment,
            "topic": interpretation_result["topic"],
        }
        self.memory.add_episode(episode)
        self.workspace.add_context(episode)

        return response_text, reflection_comment


def main():
    print("Cortex-0: когнитивен агент (експериментална версия).")
    print("Пиши каквото ти идва. Напиши 'изход' за спиране.\n")

    agent = CortexAgent()

    while True:
        user_text = input("Ти: ").strip()
        if user_text.lower() in ["изход", "exit", "quit"]:
            print("Cortex-0: Спирам за сега. Ще помня последните епизоди локално.")
            break

        response, reflection = agent.step(user_text)
        print("\nАгент:")
        print(response)
        print("\n[Вътрешна бележка на агента:]")
        print(reflection)
        print("\n" + "-"*60 + "\n")


if __name__ == "__main__":
    main()

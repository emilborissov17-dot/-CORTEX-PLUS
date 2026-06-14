from cortex.agent_loop import agent_iteration


def llm_call(prompt: str) -> str:
    print("=== PROMPT START ===")
    print(prompt[:800])
    print("=== PROMPT END ===")
    return "FAKE_ANSWER_FROM_LLM"


if __name__ == "__main__":
    while True:
        user = input("YOU: ")
        if not user or user.lower() in {"exit", "quit"}:
            break
        reply = agent_iteration(user, llm_call)
        print("AGENT:", reply)

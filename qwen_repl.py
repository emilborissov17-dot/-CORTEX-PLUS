from __future__ import annotations

from core.llm_backend import call_internal_llm


SYSTEM_PROMPT = (
    "Ти си QWEN_SANDBOX_DEBUG_AGENT.\n"
    "Говориш директно с разработчика (EMIL) в интерактивен режим.\n"
    "Можеш да обясняваш мисленето си, НО НЕ добавяй префикси като 'Thinking...' "
    "или '...done thinking.' – просто говори нормално.\n"
)


def main() -> None:
    print("QWEN REPL – директен чат. Празен ред или Ctrl+C за край.\n")
    history = SYSTEM_PROMPT

    while True:
        try:
            user = input("EMIL> ")
        except (EOFError, KeyboardInterrupt):
            print("\n[REPL] bye.")
            break

        if not user.strip():
            print("[REPL] empty line, exiting.")
            break

        prompt = SYSTEM_PROMPT + "\n\n" + "USER:\n" + user + "\n\nASSISTANT:\n"
        try:
            resp = call_internal_llm(prompt)
        except Exception as e:
            print(f"[REPL][ERROR] {e}")
            continue

        print("\nQWEN>\n" + resp + "\n")


if __name__ == "__main__":
    main()

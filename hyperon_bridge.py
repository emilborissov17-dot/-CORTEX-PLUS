#!/usr/bin/env python
from hyperon import MeTTa

def call_cortex_qwen(prompt: str) -> str:
    # Засега само echo за тест
    return f"[CORTEX-QWEN MOCK RESPONSE] {prompt}"

def main():
    m = MeTTa()
    m.register_token("cortex-qwen", call_cortex_qwen)

    # MeTTa код – извиква grounded token-а
    program = '!(cortex-qwen "ENERGY REVIEW")'
    result = m.run(program)
    print("MeTTa result:", result)

if __name__ == "__main__":
    main()

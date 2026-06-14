import requests

OLLAMA_MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/generate"

def run_llm(prompt: str, model: str = OLLAMA_MODEL, timeout_sec: int = 600) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.7}
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=timeout_sec)
        response.raise_for_status()
        data = response.json()
        out = data.get("response", "").strip()
        if not out:
            return "[LLM ERROR] Prazen otgovor."
        return out
    except requests.exceptions.Timeout:
        return "[LLM ERROR] Timeout."
    except requests.exceptions.ConnectionError:
        return "[LLM ERROR] Ne moje da se svurje s Ollama na localhost:11434."
    except Exception as e:
        return f"[LLM ERROR] Greshka: {e}"

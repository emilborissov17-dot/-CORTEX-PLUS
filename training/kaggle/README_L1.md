# L1 — да научим малкия мозък да чете число (Kaggle, безплатен GPU)

**Защо:** на 11.09 сондата даде: qwen3:8b чете числото 9/9, qwen2.5:3b — 0/9. Четенето на число е умение; учи се.
**Какво:** LoRA дообучаване на Qwen2.5-3B върху 2400 примера с верен отговор по аритметика (нито един от 9-те реални случая не е вътре).
**Как съдим:** преди/след на синтетичен изпит в Kaggle; истинската присъда е сондата на машината върху 9-те реални случая.

## Стъпки (веднъж)

1. kaggle.com → Sign in (с Google акаунт) → профил → Settings → **Phone verification** (без нея няма GPU и интернет в тетрадката).
2. **Datasets → New Dataset** → качи двата файла от `CORTEX++_MERGED\training\`:
   `l1_numbers_train.jsonl` и `l1_numbers_holdout.jsonl` → име: `cortex-l1` → Create.
3. **Code → New Notebook** → вдясно: *Add Input* → избери `cortex-l1`;
   *Settings*: **Accelerator = GPU T4 x2** (или P100), **Internet = On**.
4. В първата клетка постави цялото съдържание на `training\kaggle\l1_train_unsloth.py` → **Run**. (~20–40 мин.)
5. Отгоре ще има два реда `{"tag": "BEFORE", ...}` и `{"tag": "AFTER", ...}` — прати ми ги.
6. **Output** (вдясно) → свали папката `cortex-l1-gguf` (файлът `.gguf` ~2 GB и `Modelfile`) в `CORTEX++_MERGED\models\cortex-l1\`.

## На машината (Claude Code)

```
cd models\cortex-l1
ollama create cortex-l1-3b -f Modelfile
venv\Scripts\python.exe core\counterfactual_probe.py --compare brain-fast local:cortex-l1-3b brain
```
Ако Modelfile няма TEMPLATE: копирай TEMPLATE от `ollama show qwen2.5:3b --modelfile`.
Присъда: `local:cortex-l1-3b` трябва да мине от 0/9 (като brain-fast) към 9/9 (като brain), и полето `model` трябва да казва `cortex-l1-3b`.

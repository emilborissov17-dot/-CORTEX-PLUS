# -*- coding: utf-8 -*-
"""
training/kaggle/l1_train_unsloth.py — L1 LoRA on a free Kaggle GPU (T4 16 GB).
(11 Sep 2026. Emil: "if the possibility exists, use it.")

Run this in ONE Kaggle notebook cell (Settings: Accelerator = GPU T4, Internet = On),
after uploading training/l1_numbers_train.jsonl and training/l1_numbers_holdout.jsonl as
a Kaggle dataset (it appears under /kaggle/input/<name>/).

What it does, in order, and prints every number it bases a claim on:
  1. BEFORE: the untouched Qwen2.5-3B-Instruct answers the holdout exam -> accuracy,
     and "twin consistency" (does the verdict flip when the number is mirrored?).
  2. TRAIN: LoRA (r=16) on the train file, loss only on the answer tokens, 1 epoch.
  3. AFTER: the same holdout exam, same prompts -> accuracy, twin consistency.
  4. EXPORT: the LoRA adapter + a merged GGUF (q4_k_m) for Ollama, with a Modelfile.
The judge of "did it learn" is the machine's own counterfactual probe on the NINE REAL
cases afterwards (core/counterfactual_probe.py, asker local:cortex-l1-3b). The holdout
here is synthetic; the real exam is on the machine.
"""
import glob
import json
import os
import re
import subprocess
import sys

os.environ["CUDA_VISIBLE_DEVICES"] = "0"      # "GPU T4 x2": Unsloth trains on one GPU; hide the second so it does not stop
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "unsloth"], check=True)

from datasets import load_dataset  # noqa: E402
from unsloth import FastLanguageModel  # noqa: E402
from unsloth.chat_templates import get_chat_template, train_on_responses_only  # noqa: E402
from trl import SFTTrainer, SFTConfig  # noqa: E402

BASE = "unsloth/Qwen2.5-3B-Instruct"          # the same model family as the machine's qwen2.5:3b
found = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)   # Kaggle now mounts deeper: /kaggle/input/datasets/<user>/<slug>/
print("INPUT FILES:", found)
TRAIN = [f for f in found if f.endswith("l1_numbers_train.jsonl")][0]
HOLD = [f for f in found if f.endswith("l1_numbers_holdout.jsonl")][0]
OUT = "/kaggle/working"
MAX_HOLD = 200                                # exam size (time on a T4: a few minutes)

model, tokenizer = FastLanguageModel.from_pretrained(BASE, max_seq_length=1024, load_in_4bit=True)
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
hold = [json.loads(l) for l in open(HOLD, encoding="utf-8")][:MAX_HOLD]


def verdict_of(text):
    m = re.search(r'"verdict"\s*:\s*"?(OVER|UNDER)', text, re.IGNORECASE)   # (was: upper() vs a lowercase pattern -> never matched)
    return m.group(1).upper() if m else None


def exam(tag):
    FastLanguageModel.for_inference(model)
    right, answered, by_key = 0, 0, {}
    for ex in hold:
        prompt = tokenizer.apply_chat_template([ex["messages"][0]], tokenize=False, add_generation_prompt=True)
        ids = tokenizer(prompt, return_tensors="pt").to("cuda")
        out = model.generate(**ids, max_new_tokens=80, do_sample=False)
        v = verdict_of(tokenizer.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
        answered += v is not None
        right += v == ex["meta"]["truth"]
        by_key.setdefault((ex["meta"]["case"], ex["meta"]["line"], ex["meta"]["direction"]), []).append(
            (ex["meta"]["truth"], v))
    twins = [pair for pair in by_key.values() if len(pair) >= 2 and pair[0][0] != pair[1][0]]
    flips = sum(1 for pair in twins if pair[0][1] and pair[1][1] and pair[0][1] != pair[1][1])
    res = {"tag": tag, "n": len(hold), "answered": answered, "accuracy": round(right / len(hold), 3),
           "twins": len(twins), "twins_where_verdict_flipped_with_the_number": flips}
    print(json.dumps(res))
    return res


before = exam("BEFORE")

model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0, bias="none", random_state=3407,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth")
FastLanguageModel.for_training(model)         # the BEFORE exam switched it to inference mode
ds = load_dataset("json", data_files=TRAIN, split="train")
ds = ds.map(lambda ex: {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)})
trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=ds,
                     args=SFTConfig(dataset_text_field="text", max_seq_length=1024, per_device_train_batch_size=4,
                                    gradient_accumulation_steps=4, num_train_epochs=1, learning_rate=2e-4,
                                    warmup_steps=10, logging_steps=10, optim="adamw_8bit", seed=3407,
                                    output_dir=f"{OUT}/run", report_to="none"))
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                  response_part="<|im_start|>assistant\n")
stats = trainer.train()
print(json.dumps({"train_loss": round(stats.training_loss, 4), "steps": stats.global_step}))

after = exam("AFTER")

model.save_pretrained(f"{OUT}/cortex-l1-lora")
tokenizer.save_pretrained(f"{OUT}/cortex-l1-lora")
model.save_pretrained_gguf(f"{OUT}/cortex-l1-gguf", tokenizer, quantization_method="q4_k_m")
json.dump({"base": BASE, "before": before, "after": after, "train_rows": len(ds)},
          open(f"{OUT}/L1_RESULT.json", "w"), indent=1)
print("DONE ->", os.listdir(f"{OUT}/cortex-l1-gguf"))

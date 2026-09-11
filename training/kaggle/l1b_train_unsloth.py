# -*- coding: utf-8 -*-
# training/kaggle/l1b_train_unsloth.py — L1b on a free Kaggle T4 (12 Sep 2026).
# One cell. Settings: Accelerator = GPU T4 x2, Internet = On. Input: a dataset holding
# l1b_train.jsonl and l1b_exam.jsonl (made by training/lora_l1b_numbers.py).
#
# The exam is split into four groups so the result says WHERE the skill holds:
#   seen_long     a taught layout inside the brain's real long wrapper
#   probe_long    exactly the shape the machine's probe asks in
#   unseen_short  a layout and wording NEVER in a lesson, short wrapper
#   unseen_long   never-taught layout inside the long wrapper (the hardest)
# "Learned the skill" = unseen_* accuracy near seen_* and twins flip in every group.
import glob, json, os, re, subprocess, sys

os.environ["CUDA_VISIBLE_DEVICES"] = "0"
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "unsloth"], check=True)

from datasets import load_dataset
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from trl import SFTTrainer, SFTConfig

BASE = "unsloth/Qwen2.5-3B-Instruct"
found = glob.glob("/kaggle/input/**/*.jsonl", recursive=True)
print("INPUT FILES:", found)
TRAIN = [f for f in found if f.endswith("l1b_train.jsonl")][0]
EXAM = [f for f in found if f.endswith("l1b_exam.jsonl")][0]
OUT = "/kaggle/working"
MAX_SEQ = 2048
N_EXAM = 240                     # 120 twin pairs, all four groups

model, tokenizer = FastLanguageModel.from_pretrained(BASE, max_seq_length=MAX_SEQ, load_in_4bit=True)
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
exam_rows = [json.loads(l) for l in open(EXAM, encoding="utf-8")][:N_EXAM]


def verdict_of(text):
    m = re.search(r'"?verdict"?\s*:\s*"?(OVER|UNDER)', text, re.IGNORECASE)
    return m.group(1).upper() if m else None


def exam(tag):
    FastLanguageModel.for_inference(model)
    per = {}
    for ex in exam_rows:
        prompt = tokenizer.apply_chat_template([ex["messages"][0]], tokenize=False, add_generation_prompt=True)
        ids = tokenizer(prompt, return_tensors="pt").to("cuda")
        out = model.generate(**ids, max_new_tokens=120, do_sample=False)
        v = verdict_of(tokenizer.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
        m = ex["meta"]
        g = per.setdefault(m["group"], {"n": 0, "right": 0, "answered": 0, "pairs": {}})
        g["n"] += 1
        g["right"] += v == m["truth"]
        g["answered"] += v is not None
        g["pairs"].setdefault(m["pair"], []).append(v)
    res = {"tag": tag}
    for grp, g in sorted(per.items()):
        twins = [p for p in g["pairs"].values() if len(p) == 2]
        flips = sum(1 for a, b in twins if a and b and a != b)
        res[grp] = {"n": g["n"], "acc": round(g["right"] / g["n"], 3), "answered": g["answered"],
                    "twins": len(twins), "flipped": flips}
    print(json.dumps(res))
    return res


before = exam("BEFORE")

model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0, bias="none", random_state=3407,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth")
FastLanguageModel.for_training(model)
ds = load_dataset("json", data_files=TRAIN, split="train")
ds = ds.map(lambda ex: {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)})
trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=ds,
                     args=SFTConfig(dataset_text_field="text", max_seq_length=MAX_SEQ, per_device_train_batch_size=2,
                                    gradient_accumulation_steps=8, num_train_epochs=1, learning_rate=2e-4,
                                    warmup_steps=10, logging_steps=10, optim="adamw_8bit", seed=3407,
                                    output_dir=f"{OUT}/run", report_to="none"))
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                  response_part="<|im_start|>assistant\n")
stats = trainer.train()
print(json.dumps({"train_loss": round(stats.training_loss, 4), "steps": stats.global_step}))

after = exam("AFTER")
json.dump({"base": BASE, "before": before, "after": after, "train_rows": len(ds)},
          open(f"{OUT}/L1B_RESULT.json", "w"), indent=1)

model.save_pretrained(f"{OUT}/cortex-l1b-lora")
tokenizer.save_pretrained(f"{OUT}/cortex-l1b-lora")
model.save_pretrained_gguf(f"{OUT}/cortex-l1b-gguf", tokenizer, quantization_method="q4_k_m")
print("DONE ->", glob.glob(f"{OUT}/**/*.gguf", recursive=True))

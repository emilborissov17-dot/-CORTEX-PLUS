# D0 feasibility — two-track strategy (27 Sep 2026)

This report checks feasibility only. Nothing was trained and no GPU job was run. The one GPU action was loading the warm core with `core.model_window.ensure_core()`, which is the same load the supervisor performs before every cycle. All downloads are in `data/external/`, which is gitignored as of this commit (`.gitignore:367`, confirmed with `git check-ignore -v data/external/x`).

The plan file `claude/PLAN_2026-09-26_SMOOTH_OPERATION.md` is **not in this repo**. `find . -iname "*SMOOTH_OPERATION*"` returns nothing, so the items below follow the task list rather than the plan.

Every external fact is given with its source URL and quoted sentence. Every local fact is given with the command that produced it.

---

## C1 Machine

**GPU with the warm core loaded.** Before the load, `/api/ps` returned `{"models":[]}`, meaning the core was not resident. Loading it with `ensure_core()` returned `{'model': 'cortex-l1b-3b:latest', 'resident_before': False, 'reloaded': True, 'seconds': 11.7}`. After the load, `/api/ps` shows `size_vram: 2314803200` (Q4_K_M, 3.1B, context 4096).

The command `nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv` returned:
```
NVIDIA GeForce GTX 1650, 4096 MiB, 2566 MiB, 1385 MiB
```
With the core unloaded, the same query returned 0 MiB used and 3952 MiB free. The driver is 526.56, and `nvidia-smi` reports CUDA Version 12.0.

**venv_train torch.** Output from `venv_train/Scripts/python.exe`:
- Python 3.12.10, `torch 2.7.1+cu118` (CUDA build 11.8).
- `cuda_available True`, device GTX 1650, `capability (7, 5)`.
- `torch.cuda.is_bf16_supported()` returns `True`, but `is_bf16_supported(including_emulation=False)` returns **`False`**. The installed `torch/cuda/__init__.py:193` returns native support only when `get_device_properties(device).major >= 8`. Otherwise it only checks that a bf16 tensor can be created, which means emulation. **This GPU has no native bf16.**
- `flash_attn` is not installed (`ModuleNotFoundError`).

**Main venv (`venv/`, Python 3.14.5).**
- `statsmodels` is **not installed**.
- `scipy` is **not installed**.
- `pandas` is not installed.
- `numpy` 2.4.6 is installed.

**Disk.** `shutil.disk_usage('C:/')` reports C: with 575.5 GiB free of 952.6 GiB.

---

## C2 Track G (Tiny Recursive Model)

### G1 Code

The code was cloned to `data/external/trm` at `c01103738605ba39d1430519b1ee0c62f4c707f8` (2026-03-31).

**The repo is archived.** Its README says: *"...we have to temporaliy archive (make read-only) this and several other repos."*

**Licence: MIT.** From `LICENSE`: *"MIT License / Copyright (c) 2025. Samsung Electronics Co., Ltd."*

**Requirements.**
- README: *"Python 3.10 (or similar)"*, *"Cuda 12.6.0 (or similar)"*. The install uses torch nightly cu126 plus `pip install --no-cache-dir --no-build-isolation adam-atan2`.
- `specific_requirements.txt` pins: `torch==2.7.0+cu126`, `adam-atan2==0.0.3`, `triton==3.3.0`, `numba==0.61.2`.

**Hardware (README).** *"ARC-AGI-1 (assuming 4 H-100 GPUs)"* … *"Runtime: ~3 days"*.

**flash-attention: not needed.**
- The imports are commented out: `models/layers.py:8` and `:11` (`#    from flash_attn import flash_attn_func`).
- Attention goes through `torch.nn.functional.scaled_dot_product_attention` (`layers.py:12`, `:132`).
- For reference, FA2 does not support this card. https://github.com/Dao-AILab/flash-attention says: *"FlashAttention-2 with CUDA currently supports: 1. Ampere, Ada, or Hopper GPUs … For Turing GPUs (T4, RTX 2080), see the separate [flash-attention-turing] repo … bf16 requires Ampere, Ada, or Hopper GPUs"*.

**bf16 is the default. An fp32/fp16 setting exists but has not been tested.**
- `config/arch/trm.yaml:22` sets `forward_dtype: bfloat16`, and `trm.py:122` reads it with `getattr(torch, self.config.forward_dtype)`, so `arch.forward_dtype=float32` is accepted.
- There is no autocast or GradScaler, and no fp16 loss scaling.
- Whether the model trains stably in fp32/fp16 is **UNVERIFIED**.

**Blocker on sm_75: `adam-atan2`.**
- `pretrain.py:20` has `from adam_atan2 import AdamATan2`.
- Per https://pypi.org/pypi/adam-atan2/json, version 0.0.3 is published as an sdist only.
- Its `setup.py` sets `NVIDIA_SUPPORTED_ARCHS = {"80", "86", "89", "90"}` with the comment `# TODO(one): Needs testing on consumer GPUs.`, plus the classifier `"Operating System :: Unix"`.
- `adam_atan2.py:4` is a bare `import adam_atan2_backend` with no fallback. A pure-torch reference exists only in the package's test file.

**Other hard requirements.**
- CUDA is hard-coded: `pretrain.py:130` `with torch.device("cuda")` and `:249` `torch.load(..., map_location="cuda")`.
- `torch.compile` is on unless `DISABLE_COMPILE` is set (`pretrain.py:134-135`).

### G2 Checkpoints

**No official Samsung checkpoint was found.**
- The README has no checkpoint link.
- https://huggingface.co/api/models?author=SamsungSAILMontreal lists 20 models and none of them is TRM.
- `?author=AlexiaJM` returns `[]`.

**ARC Prize Foundation re-training (third party):** https://huggingface.co/arcprize/trm_arc_prize_verification, `license:mit`.
- Its README says: *"They were trained using the code and recipe of the official TRM repository … We did not contribute to the TRM reserach nor maintain the TRM code."*
- It reports *"ARC-AGI-1: 40%, $1.76/task"* and *"ARC-AGI-2: 6.2%, $2.10/task"*.
- Training: *"on a single 8:H100 node. Each run takes ~20-30h."*
- Files:
  - `arc_v1_public/step_518071`: 1,822,205,258 bytes.
  - `arc_v2_public/step_723914`: 2,467,988,810 bytes.

**Downloaded:** `data/external/trm_ckpt/arcprize_arc_v1_public_step_518071`, 1,822,205,258 bytes.
- **sha256 `53689643ad1606d7c22c758f8af0a71b3b66275dea074f214d2f1048d9a01fb0`**, which equals the HF LFS oid.
- I re-ran `sha256sum` on it for this report.

**Other third-party ARC checkpoints**, with sizes from `/api/models/<id>/tree/main`:

| Repo | Licence | Files |
|---|---|---|
| `Sanjin2024/TinyRecursiveModels-ARC-AGI-1` | apache-2.0 | 1,822,205,258 B |
| `Sanjin2024/TinyRecursiveModels-ARC-AGI-2` | apache-2.0 | 2,467,988,810 B |
| `alphaXiv/trm-model-arc-agi-1` | mit | 2 files × 1,822,205,258 B |
| `Trelis/TRM-ARC-AGI-II` | apache-2.0 | 10 steps × 2,467,988,810 B, plus per-step `submission.json` |
| `seconds-0/trm-arc2-8gpu` | mit | 2,467,988,405 B |

**Why a "7M" model is 1.8 GB.** arXiv 2511.02886 §4.5.2: *"there are ~2.5 GB of parameters required to capture 1,000 augmentations of ~1,000 tasks … the TRM is more a 500M+ parameter model than a 7M parameter model."* The ARC-AGI-1 state_dict is 1.82 GB, which is more than the 1.385 GB of VRAM free with the core loaded. Loading it on the GPU without unloading the core is therefore **UNVERIFIED and likely to fail**.

### G3 Papers

**arXiv 2511.02886**, "Test-time Adaptation of Tiny Recursive Models", R. McGovern (Trelis), v1 4 Nov 2025. Source: https://arxiv.org/abs/2511.02886.

Scores:
- *"That approach scored approximately 7.8% on the public ARC AGI II evaluation set"*.
- *"pre-trained on 1,280 public tasks for 700k+ optimizer steps over 48 hours on 4xH100 SXM GPUs to obtain a ~10% score on the public evaluation set. That model was then post-trained in just 12,500 gradient steps during the competition to reach a score of 6.67% on semi-private evaluation tasks."*
- Table 1 (semi-private): *"TRM paper replication 6.67"*, *"Expanded data, 200k epochs 4.25"*, *"Filtered hard data, 1M epochs 1.27"*.
- Re-submissions scored *"from 3.33 to 6.67"*.

Uncontaminated ARC-AGI-2 public-eval tasks: **114 of 120.**
- Appendix A: *"Six tasks in the ARC AGI II evaluation split also appear in ARC AGI I. When adapting models pre-trained on ARC AGI I, the arc-agi_evaluation2clean_challenges.json split filters these duplicates to avoid contamination."* The table lists `evaluation2clean` with 114 tasks.
- The paper does not list the six IDs. They match my own computation in G4.

Solved task IDs: **not published.**
- The paper lists *"Closer visual inspection of the tasks solved versus not solved"* as future work.
- The fork https://github.com/TrelisResearch/TinyRecursiveModels has no solved-ID file.
- HF `Trelis/TRM-ARC-AGI-II` publishes raw per-step `submission.json` files. A solved list could be derived from them, but none is published.

Training:
- *"approximately 750k optimizer steps with a global batch size of 768"*.
- *"roughly 48 hours on 4xH100 SXM GPUs"*.
- Post-training: *"a global batch size of 384 … learning rate … doubled (to 2e-4 and 2e-2)"* and *"fine-tuned for 12.5k steps"*.
- Budget: *"four L4 accelerators for twelve hours."*

**arXiv 2512.11847**, "Tiny Recursive Models on ARC-AGI-1: Inductive Biases, Identity Conditioning, and Test-Time Compute", Roye-Azar et al. (Western University), v2 8 Jan 2026. Source: https://arxiv.org/abs/2512.11847.

- It studies *"arcprize/trm_arc_prize_verification"*, the same checkpoint downloaded in G2.

Scores, on the ARC-AGI-1 public eval (400 tasks):
- Table 1: *"Paper mode (official) 1000 Yes 40.00%"* and *"Single augmentation 1 No 29.25%"*.
- Table 2: blank or randomized puzzle IDs give *"0.00%"*.
- Table 3: Pass@1 is *"38.25%"* at recursion step 1 and *"40.50%"* at step 4.
- Table 6: *"TRM (7M parameters) 2.4 GB 31.3 samples/s"*.

ARC-AGI-2 is **not addressed**: *"We do not use ARC-AGI-2 or private competition splits in our experiments."* The paper gives no count of uncontaminated tasks.

Solved task IDs: **not published.** The repo https://github.com/AntonioRoye/TinyRecursiveModels (commit `010206d1`) writes `per_example.jsonl` at runtime, but no result files are committed.

Training and hardware:
- *"only the first 2,500 optimization steps out of a nominal schedule of approximately 778,000 steps"*.
- *"a single NVIDIA H100 with 80 GB of memory … smaller devices would suffice."*
- Batch size and wall-clock time are not stated.

### G4 ARC-AGI-2 against ARC-AGI-1 (computed here)

**Clones.**
- `data/external/arc-agi-2` at `f3283f72` (https://github.com/arcprize/ARC-AGI-2).
- `data/external/arc-agi-1` at `39903044` (https://github.com/fchollet/ARC-AGI).

**Task counts.** ARC-AGI-2 has **120** public-eval tasks and 1000 training tasks. ARC-AGI-1 has 400 training and 400 evaluation tasks.

**Command:** `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe data/external/arc_overlap.py`. I re-ran it for this report. It refuses with exit 2 if a clone is missing.

| Criterion (ARC-AGI-2 eval against all 800 ARC-AGI-1 tasks) | Count | IDs |
|---|---:|---|
| Identical train+test grids, train order ignored | **6** | `0934a4d8 136b0064 16b78196 981571dc aa4ec2a5 da515329`, each equal to ARC-AGI-1 `evaluation/<same id>` |
| Identical including train-pair order | 0 | Train pairs are reordered; the sets are equal |
| Shares any identical (input, output) pair | 7 | The six above, plus `db695cfb` (all 5 train pairs = ARC-AGI-1 `evaluation/55783887`; test pair new) |

**Uncontaminated eval tasks:** 114 of 120 under the "identical" criterion, or 113 of 120 if the `db695cfb` near-duplicate is also excluded.

**For context,** 766 of the 1000 ARC-AGI-2 training tasks are identical (as pair-sets) to an ARC-AGI-1 task.

---

## C3 Track W (conflict panel)

### UCDP

**Pages read:** https://ucdp.uu.se/downloads/ and https://ucdp.uu.se/downloads/olddw.html. The second says: *"This page contains old, historical versions of UCDP datasets."*

**No release date is stated on either page** for any GED annual or Candidate file. The table below uses the HTTP `Last-Modified` header (`curl -sIL`) as a proxy only. Every URL returned 200.

| GED version | URL | Last-Modified (proxy) |
|---|---|---|
| 26.1 (current) | https://ucdp.uu.se/downloads/ged/ged261-csv.zip | 08 Jun 2026 |
| 25.1 | …/ged/ged251-csv.zip | 11 Jun 2025 |
| 24.1 | …/ged/ged241-csv.zip | 22 May 2024 |
| 23.1 | …/ged/ged231-csv.zip | 06 Jun 2023 |
| 22.1 | …/ged/ged221-csv.zip | 12 May 2022 |
| 21.1 | …/ged/ged211-csv.zip | 09 Jun 2021 |
| 20.1 | …/ged/ged201-csv.zip | 16 Jun 2020 |
| 19.1 | …/ged/ged191-csv.zip | 02 Jun 2019 |
| 18.1 | …/ged/ged181-csv.zip | 26 Jun 2018 |
| 17.1 | …/ged/ged171-csv.zip | 30 Jun 2017 |

**Candidate files.** olddw.html plus the main page list **129** Candidate CSVs of the form `https://ucdp.uu.se/downloads/candidateged/GEDEvent_v<ver>.csv`, and all 129 returned 200. The full list with headers is in `data/external/ucdp/cand_heads.txt`.

| Series | Coverage |
|---|---|
| 26.0.1–26.0.8 | Global, plus quarterly 26.01.26.03 and 26.01.26.06 |
| 21.0.x–25.0.x | Global, monthly, plus quarterly cumulatives |
| 20.0.x | *"January-March covers Africa, April-July covers Africa and Middle East, August-September covers Africa, Asia, Europe and Middle East, October-December global"* |
| 18.0.x, 19.0.x | *"(covers Africa)"* |

**Upload timing.**
- Recent Candidate files are uploaded around the 20th of the following month. 26.0.8 was uploaded 20 Sep 2026, and 26.0.7 on 20 Aug 2026.
- The 18.0.x and 19.0.x files carry Apr/May 2020 timestamps because they were re-uploaded, so their Last-Modified is not their release date.

**Downloaded to `data/external/ucdp/`.**

| File | Bytes | sha256 |
|---|---:|---|
| `ged261-csv.zip` | 39,122,522 | `8c941d84954e555ee2e54f40fa04d9203bf1e2f962203d0a9930966c4947c667` (re-verified) |
| `GEDEvent_v26_0_8.csv` | 1,443,396 | `2ad6e0b2bfdbaa31873716a3455096923a8539519d69d96aeeea2d0f44a34593` (re-verified) |
| `GEDEvent_v26_0_7.csv` | — | fetched to fill the gap |
| `GEDEvent_v26_01_26_06.csv` | — | fetched to fill the gap |

**Panel counts.** Command: `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe data/external/ucdp_panel.py`. "State-based" means `type_of_violence==1` and `best>0`; the month is taken from `date_start`, counted from 1989-01-01, per `country_id`.
```
== GED 26.1 (ged261-csv.zip)
   rows=417968  date_start min=1989-01-01 max=2025-12-31  date_end max=2025-12-31
   distinct country_id with state-based deaths=106
   countries with >= 40 distinct sb months since 1989-01-01: 56
== Candidate latest (GEDEvent_v26_0_8.csv)
   rows=1806  date_start min=2026-01-01 max=2026-08-31  date_end max=2026-09-10
   distinct country_id with state-based deaths=32
   countries with >= 40 distinct sb months since 1989-01-01: 0
== UNION GED 26.1 + all 2026 candidate files (dedupe on id)
   rows=431627  distinct country_id with state-based deaths=112
   countries with >= 40 distinct sb months since 1989-01-01: 56
```

What the counts show:
- **The panel of countries with at least 40 months is 56, and it comes entirely from GED.** The Candidate file alone gives at most 2 months per country.
- **26.0.8 is mostly August but not only August:** 1774 of its 1806 rows are 2026-08, 26 are 2026-07, and a few are earlier months.
- **Candidate rows carry `code_status`.** In 26.0.8, 1026 are "Clear" and the rest are "Check …" flags.
- **A continuous 2026 panel needs 26.01.26.06 + 26.0.7 + 26.0.8.**

### VIEWS

**API base: https://api.viewsforecasting.org.** The README at https://raw.githubusercontent.com/prio-data/views_api/master/README.md says: *"The VIEWS API is available in _alpha_ testing mode at [https://api.viewsforecasting.org]"*. The endpoints are `/{run}/{loa}/{tv}` with the parameters `iso`, `countryid`, `month`, `date_start`, `date_end` and `pagesize`, according to `/openapi.json`.

**Past vintages: YES.** `GET /` returns 91 run ids:
- `r_2021_01_01` … `r_2021_12_01` and `escwa_2021_*`, from 2021.
- `fatalities001_2021_12_t01` … `fatalities001_2023_03_t01`.
- `fatalities002_2023_04_t01` … `_2025_10_t01`.
- `fatalities003_2025_10_t01` … `fatalities003_2026_08_t01`.

Old runs still serve data. For example, `fatalities001_2021_12_t01/cm/sb?iso=SDN` returned HTTP 200 with 36 rows.

**The API carries no issue date.**
- Run metadata is `start_date`/`end_date` as `month_id` integers only.
- Per https://github.com/prio-data/views_api/wiki/Dataset-naming-conventions, the date in a run name is *"the calendar year ( YYYY ) and month ( MM ) of the last data that informs a given set of predictions … For pre-2022 data releases, date instead refers to the release date"*.
- Release dates appear only in the wiki table https://github.com/prio-data/views_api/wiki/Available-datasets, which has a *"Release date"* column. For example:
  - *"fatalities003_2026_07_t01 … 2026-08-26"*
  - *"fatalities002_2025_03_t01 … 2025-07-23"*
  - *"fatalities001_2021_12_t01 … 2023-04-27"*
- **Several vintages were released months after their data month, in batches. A backtest must key on the wiki release date, not the run name.**

**Proof of access.** `GET https://api.viewsforecasting.org/fatalities003_2026_08_t01/cm/sb?iso=SDN&pagesize=100` returned HTTP 200, saved as `data/external/views/cm_sb_SDN_fatalities003_2026_08_t01.json`, sha256 `a97e31f9c583560294edf77c957763fa0374d0e8a71751e443dfb008ea640702` (re-verified). Excerpt:
```
"models":["main_dich","main_mean","main_mean_ln"],"row_count":36,"start_date":561,"end_date":596,
"data":[{"country_id":245,"month_id":561,"name":"Sudan","isoab":"SDN","year":2026,"month":9,
"main_mean_ln":5.5909,"main_dich":1.0,"main_mean":266.9778}, ...
```
The codebook defines `main_mean` as *"Point prediction of the number of fatalities in state-based armed conflict."*

**Field names differ between versions.** fatalities001 uses `sc_cm_sb_main`, while fatalities003 uses `main_mean`.

---

## Items that could not be determined

**C1**
- The requested plan file is not in the repo.

**C2**
- No official Samsung TRM checkpoint was found; only third-party ones exist.
- Whether `adam-atan2` 0.0.3 builds for sm_75 or on Windows was not attempted, per the no-GPU rule. Close with: `venv_train/Scripts/python.exe -m pip install --no-build-isolation adam-atan2==0.0.3 && venv_train/Scripts/python.exe -c "from adam_atan2 import AdamATan2"`.
- Whether TRM trains or evaluates stably in fp32/fp16 on this GPU is UNVERIFIED.
- Whether the 1.82 GB checkpoint can be evaluated here (on GPU with the core unloaded, or on CPU) is UNVERIFIED. `pretrain.py:249` hard-codes `map_location="cuda"`.
- Neither paper publishes a list of solved task IDs.
- 2512.11847 gives no batch size, no wall-clock time and nothing on ARC-AGI-2.
- 2511.02886 gives post-training wall-clock only as the 12-hour budget.
- The HF search for `TRM` hit its 100-result cap, so the checkpoint list may be incomplete.

**C3**
- Stated release dates for GED annual and Candidate files: none are on the download pages. Only the Last-Modified proxy is available, and the GED codebook PDFs were not opened.
- The release date of `fatalities003_2026_08_t01`: the wiki says *"End of Sept TBA"*, but the API already serves it.
- Release dates for `fatalities001_2022_00_t01` and `fatalities001_2023_00_t01`, which are absent from the wiki table.
- Whether VIEWS run contents are immutable after release: no checksum or immutability statement was found.
- Whether UCDP event ids are stable between a Candidate release and the later GED annual release covering the same months.

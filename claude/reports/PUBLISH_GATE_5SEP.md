# THE PUBLISH GATE — diagnosis, 5 September 2026

Read-only. Nothing fixed. The GPU stayed with the training run; the 03:04 cycle untouched.

## HEADLINE: the item is stale. Publishing has been working for five nights.

Open item (1) says the publish gate has been silent since 17 Aug 04:07. The first half
is right and the second half is five days out of date.

```
commits to emilborissov17-dot/cortex-civilization-watch, per day
  2026-08-10 .. 2026-08-17    28/day
  2026-08-18 .. 2026-08-30    ZERO      <- the gap: 13 nights
  2026-08-31                  56        <- resumed (two cycles that day)
  2026-09-01 .. 2026-09-04    28/day
```

Last commit before the gap: `2026-08-17T01:07:16Z` = **04:07 local**, exactly the
timestamp in the item. Last commit overall: `2026-09-04T01:11:07Z`, i.e. last night.

The gap was **13 nights, not 19**, and it closed on 31 Aug at 12:39 UTC.

## 1. THE GATE MAP — `_witness_or_refuse`, `fast_cycle_runner.py:1947`

Applied to `github_publish` (line 2979), `self_modifier` (3017), `execute_patches` (3023).

| # | gate | lines | checks | on failure | writes an event? |
|---|---|---|---|---|---|
| 1 | human channel | 1963-1971 | `approve_reader.channel_alive()` | `return False` | **NO** |
| 1b | *same gate, exception* | 1970-1971 | — | `except Exception: pass`, falls through | **NO** |
| 2 | notary | 1978-1994 | `core.notary.may_act(step, prev)` | `return False` | **YES** — `night_events.jsonl`, subject `"{step} ОТКАЗАНА от нотариуса"` |
| 2b | *same gate, exception* | 1995-1996 | — | prints, falls through to gate 3 | **NO** |
| 3 | MeTTa witness | 1998-2018 | `core.metta_check.witness_present()` | `return False` | **YES** — subject `"{step} ОТКАЗАНА"` |

**The exact branch that refuses without writing an event is gate 1, line 1969** — the
`return False` after the human-channel print. Its failure is visible only as a line in
the cycle log, never as an event.

**And gate 1b is worse than 1**: `except Exception: pass` at 1970-1971 means an import
error in `approve_reader`, or any exception inside `channel_alive()`, deletes the human
second witness *and prints nothing at all*. The gate reports when it says no; it never
reports that it was not asked.

Note the ordering consequence: **gate 2 returning False means gate 3 never runs.** A
notary refusal ends the function at 1994.

## 2. WHAT `channel_alive()` ACTUALLY TESTS — a cached file, not a network call

`experiments/needs/approve_reader.py:395`. It makes **no HTTP request**. It reads
`memory/human_channel_state.json` through `channel_state()` and branches on one field.

The HTTP call to Telegram lives in a *different* function — `run()` (line 417), executed
by the separate `telegram_approvals` step, which writes the state file via
`_mark_channel()`. So `channel_alive()` is reading someone else's cached verdict.

States and treatment:

| state | set when | `channel_alive()` |
|---|---|---|
| `alive` | Telegram returned 200 | **True** |
| `dead` | HTTP/timeout failure, or `ok=false` | False |
| `unknown` | file missing, unreadable, or has no `state` field | **False** |
| `not_configured` | no telegram config / missing token or chat_id | **True** (deliberate) |

**Yes — "unknown" is treated exactly as "dead".** Line 412: `if state in ("dead",
UNKNOWN_CHANNEL): return False`. They are indistinguishable to every caller.

This is deliberate and documented, not an oversight. The docstring: *"Невежеството не
бива да струва по-малко от лошата новина; иначе най-безопасният начин да минеш през
портата е да не гледаш"* — ignorance must not cost less than bad news, or the safest way
through the gate is not to look. `not_configured` stays permissive on purpose: it is a
checked, definite answer rather than an absence of checking.

## 3. THE 17 AUG CHANGE — correlation, and weaker than "same day" suggests

Commit `b03310a` *"not looking scored higher than looking and finding it dead"*,
**17 Aug 19:50:39 +0300**. It split `channel_state()` out of `channel_alive()` and
flipped the missing-record case:

```diff
- return True, "няма запис за канала — не се третира като отказ"
+ return {"state": UNKNOWN_CHANNEL, "why": "няма запис — каналът НЕ Е проверяван"}
...
+ if state in ("dead", UNKNOWN_CHANNEL):
+     return False, why
```

**This cannot explain the silence, because it postdates it.** The last successful
publish was `2026-08-17T01:07:16Z` — 04:07 local. The commit landed at 19:50 local, about
**15h 45m later**. Publishing had already stopped that morning; the change arrived that
evening. Same calendar date, opposite ends of it.

**What actually caused the 13-night gap** is in the events the gate did write:

```
2026-08-28T09:15:22  github_publish ОТКАЗАНА от нотариуса
    level_0 (неизвестен произход) (наследено от memory/web_intelligence)
```

Gate 2, the notary, refusing on **inherited unknown provenance from
`memory/web_intelligence`** — not the human channel at all.

## 4. `channel_alive()` RUN NOW, IN ISOLATION

```
state file : memory/human_channel_state.json   (exists, mtime 2026-09-05 00:44:02)
contents   : {"ts": "2026-09-04T21:44:02Z", "state": "alive",
              "why": "200 OK, 0 нови съобщения", "human_msgs": 0,
              "last_human_msg_utc": "2026-09-03T00:38:01Z"}

channel_alive() -> (True, 'alive: 200 OK, 0 нови съобщения')
```

**Alive.** The state file is refreshed roughly every minute by `CORTEX_Approvals`. Gate 1
is not blocking anything today. The human last actually wrote on 3 Sep.

### The other two gates, run now — and they disagree with each other

```
notary.may_act("github_publish", "hyperclaw_plan")
    -> (False, 'level_0 (неизвестен произход) — слабо звено: MeTTa мълчи')

metta_check.witness_present()
    -> True
```

The notary says *MeTTa is silent*; the direct MeTTa check says *present*. **Caveat I will
not gloss:** I ran `may_act` outside a cycle, so it sees no in-cycle seals and reports
`level_0 (unknown origin)`. That is probably an artefact of running it standalone, not
proof the gate misfires in a real cycle — last night's cycle passed this gate and
published. Worth a proper in-cycle check before anyone acts on it.

## 5. THE TARGET IS HEALTHY

```
GET /repos/emilborissov17-dot/cortex-civilization-watch   -> 200
  full_name : emilborissov17-dot/cortex-civilization-watch
  private   : false
  pushed_at : 2026-09-04T01:11:07Z

latest commits
  2026-09-04T01:11:06Z  b9d0e76e  [2026-09-04] verified hypotheses (1)
  2026-09-04T01:11:05Z  e25bfd70  [2026-09-04] Daily index
  2026-09-04T01:11:03Z  7d0e1be6  [2026-09-04] WATER_REVIEW update
```

Repo exists, is public, token authenticates (loaded from `.env` via `GITHUB_TOKEN`), and
the last write was last night. And the cycle log agrees:

```
cycle_2026-09-04_030401.log
  [STEP] github_publish
  [GitHub] Публикувам данни от: 2026-09-04
  [GitHub] OK ECONOMY_WORK_REVIEW
  [GitHub] OK EDUCATION_CULTURE_REVIEW
```

**This is a gate that is currently passing a healthy channel, not one refusing it.**

## 6. THE CORRECTION THAT MATTERS MOST

**The refusals were not silent. They were written, and nobody read them.**

`memory/night_events.jsonl` holds **26 `github_publish` refusal events**, spanning
16-31 Aug — exactly the gap. Each names the gate and the reason. The mechanism worked;
the reading of it did not.

So the lesson from these 13 nights is not only "a gate can refuse silently" — it is also
**"an event nobody reads is the same as no event"**. Gate 1 is genuinely silent and must
be fixed. Gate 2 was loud for thirteen nights into a file that went unread for thirteen
nights.

## 7. INCIDENTAL FINDING — a live GitHub PAT in a settings file

`.claude/settings.local.json` contains a plaintext `ghp_...` token inside two permitted
PowerShell command strings. Checked before reporting:

- **not tracked** by git
- **ignored** globally (`~/.config/git/ignore:1  **/.claude/settings.local.json`)
- `git log --all -S <token>` -> **never committed**, in any branch

So it has not leaked into the repository. It is still a live credential sitting in
plaintext in a file that tooling reads, and it is a *different* token from the one
`github_publisher.py` uses (that one comes from `.env`). Value deliberately not
reproduced here.

## WHAT I WOULD FIX FIRST — and it stands whatever the diagnosis said

Every refusal must write an event naming which gate refused and why. Concretely:

1. `fast_cycle_runner.py:1969` — gate 1's `return False` writes no event. Add one.
2. `fast_cycle_runner.py:1970-1971` — `except Exception: pass` must record that the human
   check was *skipped*, which today is invisible in every channel.
3. `fast_cycle_runner.py:1995-1996` — the notary-unavailable branch prints and falls
   through with no event.

A gate that can refuse silently is how nights disappear. That is true here even though
this particular gate turned out to be passing.

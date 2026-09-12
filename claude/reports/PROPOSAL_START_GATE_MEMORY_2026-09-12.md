# PROPOSAL — let the start gate learn its own threshold from blackbox.jsonl

**Status: PROPOSAL TO A HUMAN. Nothing has been changed.** `config/scheduler.json`
is on the protected-path denylist and `core/homeostasis.py` holds the gate; neither
has been touched. This file exists so the question arrives with a number instead of
an opinion.

Written 12 Sep 2026, from `memory/blackbox.jsonl` and `memory/existence_ledger.jsonl`
as they stood at 21:00 local.

---

## 1. What the gate is today

`core/homeostasis.py:206`

```python
    if ram_pct > 92:
        assessment["can_start"] = False
```

One constant, in percent. On this machine (13.9 GB visible) 92% is **≈ 1108 MB
available**. The message it prints says `Need 2+ GB free RAM to start cycle`, but
that string is not the condition — the condition is the 92, and the two disagree.

## 2. What the record says the cycle actually costs

`core/blackbox.py:44-50` writes an `rss_mb` / `avail_mb` row at cycle `start` and
at cycle `exit`. Pairing them by pid and crossing the outcome with the existence
ledger gives, for every cycle that reached an exit:

```
appetite (start avail − exit avail), MB, finished cycles only:
    350, 1627, 1647, 1868, 1895, 1895, 1950, 2693
    n = 8   median 1882   p95 2693
```

A cycle eats about **1.9 GB**, and in the worst of eight nights **2.7 GB**.

The gate lets one start with 1.1 GB.

That is not a theoretical gap. Two cycles have now walked through it:

| cycle | avail at start | outcome |
|---|---:|---|
| 12 Sep 20:04 | **2063 MB** | `CYCLE_DIED` — no exit row, killed mid-run |
| 09 Sep 03:04 | **2444 MB** | `CYCLE_FINISHED`, with **549 MB** left at the end |

The lowest start that still finished is 2444 MB. The highest start that died is
2063 MB. Across these nine cycles the two bands do not overlap — but both sit far
above the line the gate actually draws.

## 3. The proposal

Replace the constant with a threshold computed from the machine's own record.

```
required_at_start = clamp( p95(appetite) + HEADROOM , FLOOR , CAP )

  appetite  = start_avail − exit_avail, per cycle, from memory/blackbox.jsonl
  p95       = core.step_contract.p95   (borrowed, not re-implemented)
  HEADROOM  =  500 MB   what the cycle must still have when it finishes
  FLOOR     = 2500 MB   never demand less, however cheap a run of nights has been
  CAP       = 4500 MB   never demand more than this machine can plausibly free
  MIN_N     =    4      below four paired cycles, use FLOOR and say so
```

With today's record: `clamp(2693 + 500, 2500, 4500)` = **3193 MB**.

**Why a floor and a cap.** The failure mode of any self-calibrating number is that
it calibrates itself into uselessness. One quiet night — 07 Sep cost 350 MB,
because most of the work no-opped — must not be able to drop the bar under what a
normal cycle eats; the FLOOR stops that. And one pathological night must not be
able to raise the bar above what a laptop with a browser open can ever offer, which
would convert the gate from a guard into a permanent refusal; the CAP stops that.

**Why p95 and not the mean.** The mean (1741 MB) describes a night that does not
happen. The gate is asked to survive the expensive night, not the average one.

## 4. What the rule would have done, night by night

```
cycle                               start   exit   used  what happened   | rule
2026-09-05T03:04:01                  6782   4831   1950  CYCLE_FINISHED  | RUN
2026-09-06T03:04:01                  3920   2273   1647  CYCLE_FINISHED  | RUN
2026-09-07T03:04:01                  6028   5678    350  CYCLE_FINISHED  | RUN
2026-09-08T03:04:02                  3981   1288   2693  CYCLE_FINISHED  | RUN
2026-09-09T03:04:02                  2444    549   1895  CYCLE_FINISHED  | REFUSED
2026-09-10T03:04:02                  6457   4562   1895  CYCLE_FINISHED  | RUN
2026-09-11T03:04:02                  5198   3571   1627  CYCLE_FINISHED  | RUN
2026-09-12T03:04:02                  3231   1363   1868  CYCLE_FINISHED  | RUN
2026-09-12T20:04:02                  2063    nan    nan  CYCLE_DIED      | REFUSED
2026-09-12T20:39:02                  2471    nan    nan  still running   | REFUSED

finished cycles the rule would still have run : 7/8
finished cycles it would have refused         : 1/8
deaths it would have prevented                : 1/1
```

Today's gate would have run **every single row**, including the one that died.

## 5. The cost, stated plainly

**It would have refused a night that worked.** 09 Sep started with 2444 MB and
finished. Under this rule it would not have started. That is one lost night in
eight, bought for one death prevented — and the night it refused ended with 549 MB
of headroom, which is closer to the edge than any night should be. But it is a real
cost and it should be weighed, not waved away.

**It may be refusing a second one right now.** The cycle running as this is written
(12 Sep 20:39) started with 2471 MB, is 21 minutes in and has reached `deduction`
without trouble. If it finishes, the tally becomes 6/8 rather than 7/8, and the
FLOOR of 2500 is the parameter to argue about.

**The appetite sample is biased low, and cannot not be.** A cycle that dies writes
no `exit` row, so it contributes no appetite measurement. Every number in section 2
comes from a cycle that survived. The true appetite of a night that died is at
least what it had, and unknowable beyond that. So `p95(appetite)` is a **lower
bound** on what the cycle can want, and a threshold built on it errs towards being
too generous, never too strict.

**n = 8 is small, and p95 of eight samples is the maximum.** `core/step_budget.py:238`
already names this trap in another context: with few samples the 95th percentile
just returns the largest observation, so the rule is really "the worst night so
far, plus 500 MB". That is defensible as a starting position and it is not what the
formula will mean at n = 40. The MIN_N guard covers the other end; nothing covers
this one except saying it out loud.

## 6. Where it would go, if a human says yes

- the parameters belong in `config/scheduler.json`, next to `step_ceilings_sec`,
  because that file's own note makes it the single source of truth for limits and
  says they are human-tunable only;
- the computation belongs in one function, read by `core/homeostasis.py` at the
  gate, so there is not a second place that decides how much memory is enough;
- the gate's message must print the computed number and the record it came from —
  `refusing: 2063 MB available, 3193 MB required (p95 of 8 recorded cycles + 500)`
  — because a refusal a human cannot audit is a refusal a human will disable.

## 7. Reproducing this

Every number above comes from two files already in the repo and no new state:

```
memory/blackbox.jsonl            start/exit rows, step == "cycle"
memory/existence_ledger.jsonl    CYCLE_FINISHED / CYCLE_DIED / CYCLE_KILLED
```

Pairing is by `pid` within `blackbox.jsonl`, and the outcome is matched to a
`CYCLE_STARTED` within 180 s of the start row — the ledger records the launcher's
pid and the blackbox records the real interpreter's, so the two cannot be joined on
pid directly. This is worth knowing before anyone tries to reproduce it that way.

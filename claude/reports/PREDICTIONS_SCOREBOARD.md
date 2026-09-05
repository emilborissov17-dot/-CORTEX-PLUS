# PREDICTIONS SCOREBOARD — Claude's pre-registered numbers vs measured outcomes

Source of predictions: claude/PREDICTIONS_5SEP_CLAUDE_ON_14.md (sha256 9237fb3c…, sealed
5 Sep 16:50, before any result). Kimi judges PASS / NO / UNRESOLVABLE. Brier at the end.

| date | test | Claude's prediction | P (Claude) | outcome | measured | Brier |
|---|---|---|---|---|---|---|
| 5 Sep 18:33 | Run A, UNSEEN sig01, K=4 ranking | AT CHANCE, 0.18–0.26 | P(above base w/ CI)=0.15 | NO (at chance) | adapter 0.2222 [0.1585, 0.2905]; base 0.2667 [0.1921, 0.3441]; axis rule 0.7778; BEYOND_TRIVIAL False | (1-0.85)^2 = 0.0225 |
| 5 Sep 20:11 | THE FLOOR on k1b_A (free_expression.py) | "near-zero divergence — Run A learned nothing measurable, so its floor should sound like Qwen" | (no P stated) | HALF RIGHT: text identical (divergence 0.0, both `<silent>`); WRONG on meaning — the distribution moved | P(silent) adapter 0.8977 vs base 0.2698; first-token entropy 0.4707 vs 1.1589 nats; samples silent 5/5 vs 4/5; delta_total 47.48 over 144 modules, top = layers 30–35 o_proj | — (no probability was given; scored as a miss on interpretation) |

Notes 5 Sep:
- The base model's CI now includes 0.20 under the clustered effective-n (157 pairs), so
  "base above chance" from K1B_CONTROL_RANK_V2 (unclustered) does not hold on this bench.
- The AXIS RULE — read the axis name in the prompt, prefer the candidate answering that
  axis — scores 0.78 on the same items. Neither base nor adapter learned even that. The
  adapter is BELOW the base (not significantly). NLL delta +1.33 nats is the same
  distributional gain the deranged control showed (+1.22): style, not mapping.
- LEARNED = UNKNOWN because the control's items file was not passed (--control-items);
  the control's own report gives 0.2111 — adapter 0.2222 is indistinguishable from it.
- Feeds PRE-COMMITMENT switch 2 (9 Sep) together with T1 zero-shot.

- 20:11 THE FLOOR: greedy text was the LEAST informative measurement — identical output
  hid a threefold jump in the probability of silence and a 60% drop in first-token
  entropy. Same lesson as NLL-vs-ranking from the other side: a metric that reports "no
  change" can be reading the wrong surface. Recorded against Claude, not against the
  system. Two candidate readings, NOT yet separable: (a) the adapter learned literal
  instruction-following from the corpus ("reply with exactly <silent>"), (b) a learned
  preference for silence given this state. Separation needs the floor opened after PC1
  and PC3 (different corpus, known rule) and, later, in the sandbox.
- Operational: claude/reports/FLOOR_k1b_A.jsonl carries a UTF-8 BOM (PowerShell
  Out-File); parse with utf-8-sig or fix the launcher to write BOM-less.

- 20:47 CORRECTION (found by Claude Code while building the battery): `p_silent_first_token`
  is the probability of the FIRST token of "<silent>", which tokenises as "<" + "silent" +
  ">". So the 0.8977 vs 0.2698 above is P("<") — the mass on every string that starts with
  "<", not on "<silent>" specifically. Variant C would have been blind to it (<pass> shares
  the first token). A check answering a different question than the one asked — mine, in
  the floor, on the same day the rule was written down. The battery reports p_seq (teacher-
  forced probability of the whole string) next to p_first. What stands unchanged from the
  first record: greedy `<silent>` both sides, divergence 0.0, samples 5/5 vs 4/5 silent,
  first-token entropy 0.47 vs 1.16. What is NOT yet known: P(<silent>) proper, adapter vs
  base. Read the battery, not the first record, for that.

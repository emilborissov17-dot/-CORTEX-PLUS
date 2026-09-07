# BET_2026-09-07.json IS VOID FOR THE DEBUT — do not grade it

Sealed 2026-09-07T10:39:46+03:00, committed in `d711d41`.

**Superseded the same morning**, before any grading, by a hard requirement added after
it was sealed: **every bet must carry a RATIONALE** — the model's own one-line statement
of why that number, by what mechanism. `BET_2026-09-07.json` predates that requirement
and records only a number, so it is not the debut and **must not be graded as one**.

**The file is left exactly as sealed.** Not edited, not deleted. A sealed bet that gets
rewritten after the world has started answering it is not a bet, and that principle does
not bend just because the bet turned out not to count. It stays as the record of what was
sealed at 10:39 and of the three defects reported with it — `qwen3:8b` instead of the 3B,
four distinct prompt hashes rather than one, and a `V0_date` that read `2026-09-07` for a
value belonging to `2026-09-06`.

**Also on the record: `first_bet` will now refuse to overwrite it.** `seal_bet` raises
`FileExistsError` when a sealed bet already exists for that day. The real debut therefore
cannot silently clobber this file — it will need a different day, or an explicit
`allow_overwrite=True` that somebody has to type on purpose.

**The debut indicator is under review** (earthquakes versus a market basket). No bet is
sealed until that is confirmed.

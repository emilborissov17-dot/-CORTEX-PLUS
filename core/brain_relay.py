#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/brain_relay.py — WHAT THE BRAIN SAID REACHES THE PHONE.

WHY
----
On 20 August 2026 at 19:03:32 the brain wrote its own autopsy into
memory/brain_journal.jsonl:

    "failure": true, "cause": "CLOUD_BACKEND_FAILURE",
    "transient": false, "halt_and_call_human": true

It asked for a human. Nobody was told. The line sat in a 250-row JSONL file
that nothing tails, and the cycle stayed dead until it was found by hand hours
later.

WHAT IS URGENT AND WHAT CAN WAIT
---------------------------------
IMMEDIATE — sent on its own, and it bypasses quiet hours:
    kind in {autopsy, reconsider, cycle_review, cycle_report}
    OR any row asking for a human: halt_and_call_human,
       or failure=true with transient=false

DIGEST — one grouped message:
    kind in {constancy, cycle_plan, constellation}

constancy alone is 192 of the 250 rows. Sending those one by one would train
the operator to ignore the channel, and then the autopsy would be ignored too.

THE FIELDS ARRIVE TRUNCATED, AND THAT IS SALVAGED
--------------------------------------------------
core/brain.py capped summary at 400 chars and, until today, put ONLY
{role, model} in payload. So a structured verdict survived on disk as JSON cut
off mid-string:

    ..."remedy": "Провери статуса на локалния qwen3:8b и опреде

salvage_fields() parses what it can and keeps COMPLETE key/value pairs only —
a half-read value is worse than a missing one, because it looks whole. The
write side is fixed in the same commit (full dict into payload), but 250 rows
of history are already truncated and this must read them.

COLD START
-----------
A relay that has never run does NOT send 250 rows of history. It takes the
newest 5, and reports how many it skipped, so the silence is accounted for
rather than merely quiet.

    venv\\Scripts\\python.exe core/brain_relay.py --selftest
    venv\\Scripts\\python.exe core/brain_relay.py --dry-run
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
JOURNAL = BASE / "memory" / "brain_journal.jsonl"
CURSOR = BASE / "memory" / "brain_relay_cursor.json"

IMMEDIATE_KINDS = frozenset({"autopsy", "reconsider", "cycle_review", "cycle_report"})
DIGEST_KINDS = frozenset({"constancy", "cycle_plan", "constellation"})

COLD_START_TAIL = 5

IMMEDIATE, DIGEST, SKIP = "IMMEDIATE", "DIGEST", "SKIP"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Salvage
# ---------------------------------------------------------------------------

_PAIR = re.compile(
    r'"(?P<k>[A-Za-z_][A-Za-z0-9_]*)"\s*:\s*'
    r'(?P<v>"(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)',
    re.S)


def salvage_fields(row: dict) -> dict:
    """Every COMPLETE key/value pair we can recover from a journal row.

    Prefers payload["fields"] — written whole since 21 Aug 2026. Falls back to
    scraping the truncated summary, keeping only pairs whose value terminates.
    A half-read value is worse than a missing one: it looks whole.
    """
    payload = row.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("fields"), dict):
        return dict(payload["fields"])

    text = row.get("summary")
    if not isinstance(text, str):
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    out: dict = {}
    for m in _PAIR.finditer(text):
        raw = m.group("v")
        try:
            out[m.group("k")] = json.loads(raw)
        except Exception:
            continue
    return out


def asks_for_a_human(fields: dict) -> str | None:
    """Does this verdict call for a person? Returns the reason, or None."""
    if fields.get("halt_and_call_human") is True:
        return "halt_and_call_human"
    if fields.get("failure") is True and fields.get("transient") is False:
        return "failure=true, transient=false"
    return None


def classify(row: dict) -> tuple[str, str, dict]:
    """(IMMEDIATE|DIGEST|SKIP, why, salvaged_fields)."""
    fields = salvage_fields(row)
    kind = row.get("kind")

    escalation = asks_for_a_human(fields)
    if escalation:
        return IMMEDIATE, escalation, fields
    if kind in IMMEDIATE_KINDS:
        return IMMEDIATE, f"kind={kind}", fields
    if kind in DIGEST_KINDS:
        return DIGEST, f"kind={kind}", fields
    return SKIP, f"kind={kind} is not relayed", fields


# ---------------------------------------------------------------------------
# Cursor and dedup
# ---------------------------------------------------------------------------

def content_hash(row: dict) -> str:
    return hashlib.sha1(
        json.dumps({"kind": row.get("kind"), "summary": row.get("summary")},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def load_cursor(path: pathlib.Path | None = None) -> dict:
    try:
        return json.loads((path or CURSOR).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cursor(cur: dict, path: pathlib.Path | None = None) -> None:
    p = path or CURSOR
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def read_journal(path: pathlib.Path | None = None) -> list[dict]:
    try:
        text = (path or JOURNAL).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_immediate(row: dict, fields: dict, why: str) -> str:
    head = f"CORTEX++ · {row.get('kind')} · {str(row.get('ts'))[:19]}"
    if why not in ("kind=" + str(row.get("kind")),):
        head += "\n⚠ ИСКА ЧОВЕК: " + why
    lines = [head]
    for key in ("cause", "why", "verdict", "action_needed", "remedy",
                "blind_spot", "carry_forward", "quote"):
        if key in fields and fields[key] not in (None, ""):
            lines.append(f"{key}: {str(fields[key])[:300]}")
    if len(lines) == 1:
        lines.append(str(row.get("summary"))[:400])
    model = (row.get("payload") or {}).get("model")
    if model:
        lines.append(f"(model: {model})")
    return "\n".join(lines)


def render_digest(rows: list[tuple[dict, dict]]) -> str:
    from collections import Counter
    kinds = Counter(r.get("kind") for r, _ in rows)
    lines = [f"CORTEX++ · дайджест · {len(rows)} мисли",
             ", ".join(f"{k}×{n}" for k, n in kinds.most_common())]
    for row, fields in rows[-5:]:
        bit = (fields.get("reading") or fields.get("analysis")
               or fields.get("focus") or row.get("summary") or "")
        lines.append(f"· {row.get('kind')}: {str(bit)[:120]}")
    if len(rows) > 5:
        lines.append(f"(+{len(rows) - 5} по-стари)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The relay
# ---------------------------------------------------------------------------

def relay(journal_path=None, cursor_path=None, sender=None,
          dry_run: bool = False) -> dict:
    """Send what is new. The cursor advances ONLY on a clean send."""
    rows = read_journal(journal_path)
    cur = load_cursor(cursor_path)
    seen = set(cur.get("sent_hashes", []))
    cold = not cur.get("initialised")

    skipped_cold = 0
    if cold and len(rows) > COLD_START_TAIL:
        skipped_cold = len(rows) - COLD_START_TAIL
        # MARK THE SKIPPED HISTORY AS SEEN, or the cold start merely DELAYS the
        # flood: the second run finds 245 unsent rows and posts every one. The
        # first version did exactly that, and the test for it went red.
        seen.update(content_hash(r) for r in rows[:skipped_cold])
        rows = rows[-COLD_START_TAIL:]

    immediate, digest, skipped = [], [], 0
    for row in rows:
        h = content_hash(row)
        if h in seen:
            continue
        bucket, why, fields = classify(row)
        if bucket == IMMEDIATE:
            immediate.append((row, fields, why, h))
        elif bucket == DIGEST:
            digest.append((row, fields, h))
        else:
            skipped += 1

    sent, failed = [], []

    def _send(text: str, escalation: bool, hashes: list[str]) -> None:
        if dry_run:
            sent.append({"text": text, "escalation": escalation, "hashes": hashes})
            return
        try:
            ok = (sender or _default_sender)(text, escalation)
        except Exception as exc:  # noqa: BLE001
            ok, exc_text = False, f"{type(exc).__name__}: {exc}"
            failed.append({"error": exc_text, "hashes": hashes})
        if ok:
            sent.append({"text": text, "escalation": escalation, "hashes": hashes})
            seen.update(hashes)
        elif not failed or failed[-1].get("hashes") != hashes:
            failed.append({"error": "sender returned falsey", "hashes": hashes})

    for row, fields, why, h in immediate:
        _send(render_immediate(row, fields, why),
              asks_for_a_human(fields) is not None, [h])

    if digest:
        _send(render_digest([(r, f) for r, f, _ in digest]), False,
              [h for _, _, h in digest])

    if not dry_run:
        cur["initialised"] = True
        cur["last_run"] = _now()
        cur["sent_hashes"] = sorted(seen)[-2000:]
        if skipped_cold:
            cur["cold_start_skipped"] = skipped_cold
        save_cursor(cur, cursor_path)

    result = {
        "ts": _now(), "journal_rows": len(read_journal(journal_path)),
        "cold_start": cold, "cold_start_skipped": skipped_cold,
        "immediate": len(immediate), "digest_rows": len(digest),
        "not_relayed": skipped, "sent": sent, "failed": failed,
    }
    print(f"[RELAY] {len(sent)} message(s): {len(immediate)} immediate, "
          f"{len(digest)} digest row(s), {skipped} not relayed"
          + (f", {skipped_cold} skipped at cold start" if skipped_cold else "")
          + (" — DRY RUN" if dry_run else ""))
    for f in failed:
        print(f"[RELAY] send failed: {f['error']} — cursor NOT advanced")
    return result


def _default_sender(text: str, escalation: bool) -> bool:
    """Through the supervisor's one path to the phone."""
    try:
        import supervisor
        supervisor.alarm_human(
            "мозъкът", text,
            dedup_key=f"brain:{hashlib.sha1(text.encode()).hexdigest()[:12]}",
            trigger="MANUAL" if escalation else None)
        return True
    except Exception:
        return False


def run() -> dict:
    return relay()


def _selftest() -> int:
    import tempfile
    print("core/brain_relay.py --selftest")
    ok = True

    rows = read_journal()
    autopsies = [r for r in rows if r.get("kind") == "autopsy"]
    checks = [("the live journal is readable", len(rows) > 0),
              ("it holds autopsies", len(autopsies) > 0)]

    if autopsies:
        fields = salvage_fields(autopsies[-1])
        checks += [
            ("truncated autopsy salvages fields", len(fields) >= 3),
            ("it recovers the escalation flag",
             asks_for_a_human(fields) is not None or "halt_and_call_human" not in
             str(autopsies[-1].get("summary"))),
        ]
        print(f"  salvaged {len(fields)} field(s): {sorted(fields)[:6]}")

    with tempfile.TemporaryDirectory() as tmp:
        cur = pathlib.Path(tmp) / "cursor.json"
        res = relay(cursor_path=cur, dry_run=True)
        checks.append((f"cold start sends few, skipped {res['cold_start_skipped']}",
                       res["cold_start_skipped"] >= len(rows) - COLD_START_TAIL))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    relay(dry_run="--dry-run" in sys.argv)

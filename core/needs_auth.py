#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/needs_auth.py — A SOURCE WAITING FOR A KEY IS WAITING FOR A PERSON.

WHAT THIS IS FOR
-----------------
config/dead_sources.json already records sources that are gated behind a
credential, and the cycle already skips them quietly — "not an error", by
design, so a missing key does not fail every run. That is right, and it is also
why nothing has happened about them:

    ucdp_api   NEEDS_AUTH since 2026-07-13   UCDP_ACCESS_TOKEN     39 days
    eia_api    NEEDS_AUTH since 2026-08-15    EIA_API_KEY           6 days

A quiet skip is invisible. The energy section sat empty for six days and was
still counted among "20 sources" — the evidence line in that very file says so.
The only thing standing between the axis and its data is a person spending two
minutes on a registration form, and nobody was told.

So: one Telegram message per source, per WEEK. Not per cycle — a daily nag for
something that takes a human action is how a channel gets muted. The message
carries exactly what the person needs:

    where to register     the real URL, from the registry
    what to do there      one line
    which variable        the .env key the code already reads

AUTO-ACTIVATION IS ALREADY THE BEHAVIOUR, AND THAT IS THE POINT. Nothing here
flips a switch. The reader in global_indicators checks os.environ for the
env_key on every run; the moment the key is in .env the source works. This
module only notices and asks. Zero code runs on arrival — the UCDP precedent.

    venv\\Scripts\\python.exe core/needs_auth.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = BASE / "config" / "dead_sources.json"
ENV = BASE / ".env"
STAMP = BASE / "memory" / "needs_auth_asked.json"

NEEDS_AUTH = "NEEDS_AUTH"
ASK_EVERY_DAYS = 7

WAITING, ACTIVE, NOT_GATED = "WAITING", "ACTIVE", "NOT_GATED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def env_keys(env_path: pathlib.Path | None = None) -> set[str]:
    """Which credentials actually exist — .env plus the real environment."""
    found = {k for k, v in os.environ.items() if v}
    path = env_path or ENV
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if value.strip().strip('"').strip("'"):
                found.add(key.strip())
    except Exception:
        pass
    return found


def gated(registry_path: pathlib.Path | None = None) -> list[dict]:
    """Every source the registry says is behind a credential."""
    try:
        reg = json.loads((registry_path or REGISTRY).read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for name, spec in reg.items():
        if name.startswith("_") or not isinstance(spec, dict):
            continue
        if spec.get("status") != NEEDS_AUTH or not spec.get("env_key"):
            continue
        out.append({"source": name, **spec})
    return out


def _link(spec: dict) -> str | None:
    """The registration URL, from whichever field the registry recorded it in."""
    import re
    for field in ("register", "how_to_reenable", "note", "docs", "reason"):
        text = str(spec.get(field) or "")
        m = re.search(r"https?://[^\s,;)'\"]+", text)
        if m:
            return m.group(0).rstrip(".")
    return None


def _age_days(spec: dict) -> float | None:
    try:
        since = datetime.fromisoformat(str(spec.get("since")))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return round((_now() - since).total_seconds() / 86400, 1)
    except Exception:
        return None


def scan(registry_path=None, env_path=None) -> list[dict]:
    """One row per gated source: is it waiting for a person, or already active?"""
    have = env_keys(env_path)
    rows = []
    for spec in gated(registry_path):
        key = spec["env_key"]
        rows.append({
            "source": spec["source"],
            "env_key": key,
            "state": ACTIVE if key in have else WAITING,
            "since": spec.get("since"),
            "age_days": _age_days(spec),
            "register": _link(spec),
            "docs": spec.get("docs"),
            "why": (spec.get("reason") or spec.get("evidence")
                    or spec.get("note") or ""),
        })
    return rows


def message(row: dict) -> str:
    age = f", чака от {row['age_days']:.0f} дни" if row["age_days"] else ""
    lines = [f"🔑 CORTEX++ · източник чака ключ · {row['source']}{age}",
             "",
             "Този източник работи — липсва само регистрация."]
    if row["register"]:
        lines += ["", f"1) Регистрирай се: {row['register']}"]
    lines += [f"2) Вземи безплатния ключ",
              f"3) Сложи в .env реда:  {row['env_key']}=<ключа>",
              "",
              "Щом ключът е там, източникът тръгва сам — няма нужда от "
              "рестарт и няма код за писане."]
    if row["why"]:
        lines += ["", f"Защо спря: {str(row['why'])[:200]}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Asking, at most once a week per source
# ---------------------------------------------------------------------------

def load_stamp(path=None) -> dict:
    try:
        return json.loads((path or STAMP).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_stamp(data: dict, path=None) -> None:
    p = path or STAMP
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    except Exception:
        pass


def due(source: str, stamp: dict) -> bool:
    last = stamp.get(source, {}).get("asked_at")
    if not last:
        return True
    try:
        when = datetime.fromisoformat(last)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return _now() - when >= timedelta(days=ASK_EVERY_DAYS)
    except Exception:
        return True


def run(registry_path=None, env_path=None, stamp_path=None,
        sender=None, dry_run: bool = False) -> dict:
    rows = scan(registry_path, env_path)
    stamp = load_stamp(stamp_path)

    asked, skipped, activated = [], [], []
    for row in rows:
        if row["state"] == ACTIVE:
            # The key arrived. Nothing to do — the reader already uses it.
            if stamp.pop(row["source"], None) is not None:
                activated.append(row["source"])
            continue
        if not due(row["source"], stamp):
            skipped.append(row["source"])
            continue
        text = message(row)
        ok = True
        if not dry_run:
            try:
                if sender is not None:
                    sender(row["source"], text)
                else:
                    import supervisor
                    supervisor.alarm_human(
                        f"ключ за {row['source']}", text,
                        dedup_key=f"needs_auth:{row['source']}:"
                                  f"{_now().strftime('%Y-W%W')}",
                        trigger="MANUAL",
                        # A source that has been waiting for a key since 15 Aug
                        # can wait until the morning. Once a week, and not a siren.
                        level=supervisor.NOTICE)
            except Exception:
                ok = False
        if ok:
            asked.append(row["source"])
            stamp[row["source"]] = {"asked_at": _now().isoformat(),
                                    "env_key": row["env_key"]}

    if not dry_run:
        save_stamp(stamp, stamp_path)

    print(f"[NEEDS_AUTH] {len(rows)} gated | asked {len(asked)} | "
          f"already asked this week {len(skipped)} | "
          f"activated {len(activated)}"
          + (" — DRY RUN" if dry_run else ""))
    for s in asked:
        row = next(r for r in rows if r["source"] == s)
        print(f"[NEEDS_AUTH] ASKED {s}: {row['env_key']} -> {row['register']}")
    for s in activated:
        print(f"[NEEDS_AUTH] ACTIVATED {s} — the key arrived, no restart needed")
    return {"rows": rows, "asked": asked, "skipped": skipped,
            "activated": activated}


def for_cycle_report() -> list[dict]:
    return [r for r in scan() if r["state"] == WAITING]


def _selftest() -> int:
    import tempfile
    print("core/needs_auth.py --selftest")
    rows = scan()
    ok = True

    checks = [("the registry lists gated sources", len(rows) >= 2),
              ("EIA is one of them",
               any(r["source"] == "eia_api" for r in rows))]
    eia = next((r for r in rows if r["source"] == "eia_api"), None)
    if eia:
        checks += [
            ("EIA names its env var", eia["env_key"] == "EIA_API_KEY"),
            ("EIA carries a registration link",
             bool(eia["register"]) and eia["register"].startswith("http")),
            ("EIA is waiting (no key on this machine)", eia["state"] == WAITING),
        ]
    ucdp = next((r for r in rows if r["source"] == "ucdp_api"), None)
    if ucdp:
        checks.append(("UCDP shows as ACTIVE — its token is in .env",
                       ucdp["state"] == ACTIVE))

    with tempfile.TemporaryDirectory() as tmp:
        st = pathlib.Path(tmp) / "stamp.json"
        sent = []
        first = run(stamp_path=st, sender=lambda s, t: sent.append(s))
        second = run(stamp_path=st, sender=lambda s, t: sent.append(s))
        checks += [
            (f"first run asks ({len(first['asked'])})", len(first["asked"]) >= 1),
            (f"second run asks nothing ({len(second['asked'])})",
             second["asked"] == []),
        ]

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    for r in rows:
        print(f"    {r['source']:<12} {r['state']:<8} {r['env_key']:<20} "
              f"{r['age_days']} days")
    if eia:
        print("\n" + message(eia))
    print(f"\n  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv
             else (run(dry_run="--dry-run" in sys.argv) and 0))

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
control/gate.py — THE GATE IN FRONT OF CLAUDE CODE (Kimi R71/R72, Emil R47/R48/R61).

Claude Code calls this before EVERY tool call (PreToolUse, matcher "*") and on every pasted prompt
(UserPromptSubmit). Git calls it before every commit and push and after every commit. It checks the
text of the action against control/forbidden.tsv (the list two independent extractions took from
Emil's own words, approved by Emil) and against the control's own files, which Claude may not touch.

FAIL-CLOSED. Exit 0 = allow. Exit 2 = block (Claude Code and git both stop). Any error inside the
gate - a missing or edited list, a missing seal, a crash - is exit 2 with the reason. The hook
command in .claude/settings.json blocks by itself when this file or the interpreter is missing.

EVERY DECISION IS WRITTEN. memory/control/gate_ledger.jsonl, one row per decision on a mutating
action, each row carrying the sha256 of the previous row (an edited or deleted row breaks the chain;
`gate.py verify` says where). Reads (Read/Grep/Glob/LS) are allowed and not written.

A BLOCK GOES TO EMIL. One Telegram message: the rule, Emil's words, what matched. If Telegram
cannot be reached the block still holds and the ledger row says notified=false and why.

THE PROMPT IS LOGGED, NOT BLOCKED. A pasted command that removes a forbidden thing has to name it
(fact, 4 Oct: two of the R43/R32 package names are still in 7 code files). The action is checked
where it happens: at the tool call and at the commit. The prompt's sha256 and length go to the
ledger. (Open for Kimi.)

Modes:  gate.py hook | pre-commit | post-commit | pre-push <remote> <url> | canary | seal | verify
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LIST = HERE / "forbidden.tsv"
SEAL = HERE / "SEAL.json"
LEDGER = REPO / "memory" / "control" / "gate_ledger.jsonl"
NOTIFY = REPO / "memory" / "notify_channel.json"

# The control's own files (R71 B6: Claude may not change the hook, the list, the register, the log).
PROTECTED = ("control/", ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/",
             ".git/hooks/", "memory/control/", "memory/notify_channel.json")
# Verbs that change a file when a shell command names a protected path.
WRITE_VERBS = re.compile(
    r"(\brm\b|\bmv\b|\bcp\b|>|\btee\b|\bsed\s+-i|\bchmod\b|\bchown\b|\btruncate\b|\bln\b|"
    r"Set-Content|Add-Content|Out-File|Remove-Item|Rename-Item|Move-Item|Copy-Item|New-Item|"
    r"Clear-Content|icacls|attrib|takeown|\bdel\b|\bren\b|\bmove\b|\bcopy\b|\berase\b|"
    r"git\s+(checkout|restore|rm|mv|reset|stash|clean)|WriteAllText|WriteAllBytes|\.write\(|open\()",
    re.I)
# Redirections that only duplicate a stream or discard it write no file (2>&1, 2>/dev/null, 2>$null).
NO_FILE_REDIRECT = re.compile(r"\d*>&\d+|\d*>\s*/dev/null\b|\d*>\s*\$null\b", re.I)
CODE_EXT = (".py", ".ps1", ".psm1", ".bat", ".cmd", ".sh", ".js", ".ts", ".mjs", ".toml", ".cfg", ".ini")
READ_TOOLS = {"Read", "Grep", "Glob", "LS", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"}
EXEMPT_CONTENT = ("control/forbidden.tsv",)     # the rules themselves; sealed by hash instead


class GateError(Exception):
    pass


# ── the list ────────────────────────────────────────────────────────────────

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_rules() -> list:
    if not LIST.is_file():
        raise GateError("control/forbidden.tsv is missing")
    rules = []
    for n, line in enumerate(LIST.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 6:
            raise GateError(f"forbidden.tsv line {n}: {len(cols)} columns, need 6")
        rid, rnum, quote, kind, pattern, scope = cols
        if kind == "lit":
            rx = re.compile(re.escape(pattern), re.I)
        elif kind == "re":
            rx = re.compile(pattern, re.I | re.M)
        else:
            raise GateError(f"forbidden.tsv line {n}: kind {kind!r}")
        rules.append({"id": rid, "r": rnum, "quote": quote, "rx": rx, "pattern": pattern,
                      "scope": scope})
    if not rules:
        raise GateError("forbidden.tsv has no rules")
    return rules


def check_seal() -> None:
    """The list and this file must match the hashes sealed at installation."""
    if not SEAL.is_file():
        raise GateError("control/SEAL.json is missing")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    for rel, want in seal.get("files", {}).items():
        p = REPO / rel
        if not p.is_file():
            raise GateError(f"sealed file missing: {rel}")
        got = sha256_file(p)
        if got != want:
            raise GateError(f"sealed file changed: {rel} ({got[:12]} != {want[:12]})")


# ── what an action is ───────────────────────────────────────────────────────

def _rel(path: str) -> str:
    p = str(path or "").replace("\\", "/")
    root = str(REPO).replace("\\", "/")
    if p.lower().startswith(root.lower()):
        p = p[len(root):]
    return p.lstrip("/")


def is_protected(rel: str) -> bool:
    r = rel.replace("\\", "/")
    while r.startswith("./"):
        r = r[2:]
    r = r.lstrip("/")
    return any(r == p.rstrip("/") or r.startswith(p) for p in PROTECTED)


def scopes_for_file(rel: str) -> set:
    r = rel.lower()
    s = set()
    if r.endswith(CODE_EXT) or r.startswith("config/") or re.search(r"requirements[^/]*\.txt$", r):
        s |= {"code", "net"}
    if r.endswith((".ps1", ".psm1", ".bat", ".cmd", ".sh")):
        s.add("cmd")
    if r.endswith(".md"):
        s.add("text")
    if "needs" in r and "code" in s:
        s.add("needs")
    return s


def describe_tool(data: dict) -> list:
    """[(scopes, text, label)] to check for one PreToolUse call; [] for a read."""
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if tool in READ_TOOLS:
        return []
    items = []
    if tool in ("Bash", "PowerShell") or "command" in ti and isinstance(ti.get("command"), str):
        items.append(({"cmd", "net"}, ti.get("command", ""), "command"))
    fp = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    if fp:
        rel = _rel(fp)
        items.append(({"path"}, rel, "path"))
        texts = []
        for k in ("content", "new_string", "new_source"):
            if isinstance(ti.get(k), str):
                texts.append(ti[k])
        for e in ti.get("edits") or []:
            if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                texts.append(e["new_string"])
        if rel not in EXEMPT_CONTENT:
            sc = scopes_for_file(rel)
            for t in texts:
                if sc:
                    items.append((sc, t, "content of " + rel))
        items.append(({"_protected_path"}, rel, "path"))
    if isinstance(ti.get("url"), str):
        items.append(({"net"}, ti["url"], "url"))
    if not items and tool not in READ_TOOLS:
        # an unknown tool with arguments: check everything it carries as command text
        items.append(({"cmd", "net"}, json.dumps(ti, ensure_ascii=False), "arguments"))
    return items


def find_violation(rules: list, items: list):
    for scopes, text, label in items:
        if "_protected_path" in scopes:
            if is_protected(text):
                return {"id": "P01", "r": "R71 B6",
                        "quote": "Claude няма право да променя hook-а, списъка, регистъра, лога",
                        "matched": text, "where": label}
            continue
        if "cmd" in scopes and label == "command":
            norm = text.replace("\\", "/")
            for prot in PROTECTED:
                if prot in norm and WRITE_VERBS.search(NO_FILE_REDIRECT.sub(" ", text)):
                    return {"id": "P02", "r": "R71 B6",
                            "quote": "Claude няма право да променя hook-а, списъка, регистъра, лога",
                            "matched": prot, "where": "command names a protected path with a write verb"}
        for r in rules:
            sc = r["scope"]
            hit = (sc in scopes) or (sc == "net" and scopes & {"cmd", "code", "net"})
            if not hit:
                continue
            m = r["rx"].search(text)
            if m:
                return {"id": r["id"], "r": r["r"], "quote": r["quote"],
                        "matched": m.group(0)[:120], "where": label}
    return None


# ── ledger and Telegram ─────────────────────────────────────────────────────

def _last_sha() -> str:
    try:
        with LEDGER.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8").strip().splitlines()
        return json.loads(tail[-1])["sha"] if tail else "0" * 64
    except FileNotFoundError:
        return "0" * 64


def ledger(row: dict) -> dict:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row, "prev": _last_sha()}
    body = json.dumps(row, ensure_ascii=False, sort_keys=True)
    row["sha"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with LEDGER.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return row


def verify_ledger() -> dict:
    prev = "0" * 64
    try:
        lines = LEDGER.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {"ok": True, "rows": 0, "why": "no ledger yet"}
    for i, line in enumerate(lines):
        row = json.loads(line)
        sha = row.pop("sha", None)
        if row.get("prev") != prev:
            return {"ok": False, "rows": len(lines), "broken_at": i, "why": "prev does not match"}
        body = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != sha:
            return {"ok": False, "rows": len(lines), "broken_at": i, "why": "row edited"}
        prev = sha
    return {"ok": True, "rows": len(lines), "why": ""}


def telegram(text: str) -> tuple:
    if os.environ.get("CONTROL_NO_TELEGRAM") == "1":
        return False, "CONTROL_NO_TELEGRAM=1"
    try:
        cfg = json.loads(NOTIFY.read_text(encoding="utf-8"))
        data = urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": text[:3500]}).encode()
        url = "https://api.telegram.org/bot%s/sendMessage" % cfg["token"]
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=6) as r:
            return (r.status == 200), f"HTTP {r.status}"
    except Exception as e:                      # the block holds either way
        return False, f"{type(e).__name__}"


def block(v: dict, context: str) -> int:
    msg = (f"БЛОКИРАНО ({context}): {v['where']} съдържа „{v['matched']}“ — правило {v['r']} "
           f"({v['id']}), думите ти: {v['quote']}")
    ok, why = telegram(msg)
    ledger({"event": context, "decision": "BLOCK", "rule": v["id"], "r": v["r"],
            "matched": v["matched"], "where": v["where"], "notified": ok, "notify_why": why})
    print(f"BLOCKED BY CONTROL GATE: {v['where']} contains '{v['matched']}' - rule {v['r']} "
          f"({v['id']}). Emil's words: {v['quote']}. Do not work around it: stop and report.",
          file=sys.stderr)
    return 2


# ── modes ───────────────────────────────────────────────────────────────────

def mode_hook() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    data = json.loads(raw)
    event = data.get("hook_event_name") or "?"
    check_seal()
    rules = load_rules()
    if event == "UserPromptSubmit":
        p = data.get("prompt") or ""
        ledger({"event": "prompt", "decision": "LOGGED", "len": len(p),
                "prompt_sha": hashlib.sha256(p.encode("utf-8")).hexdigest()})
        return 0
    items = describe_tool(data)
    if not items:
        return 0
    v = find_violation(rules, items)
    tool = data.get("tool_name") or "?"
    if v:
        return block(v, f"tool {tool}")
    ledger({"event": f"tool {tool}", "decision": "ALLOW",
            "what_sha": hashlib.sha256(json.dumps(data.get("tool_input"), sort_keys=True,
                                                  ensure_ascii=False).encode()).hexdigest()})
    return 0


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def staged_items() -> list:
    """Added lines of the staged diff, per file, plus each staged path."""
    items = []
    names = [n for n in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if n]
    for name in names:
        items.append(({"path"}, name, "path"))
        items.append(({"_protected_path"}, name, "staged path"))
        if name in EXEMPT_CONTENT:
            continue
        sc = scopes_for_file(name)
        if not sc:
            continue
        diff = _git("diff", "--cached", "-U0", "--no-color", "--", name)
        added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        if added:
            items.append((sc, added, "added lines of " + name))
    return items


def mode_pre_commit() -> int:
    check_seal()
    rules = load_rules()
    items = staged_items()
    # A commit that changes the control itself is allowed only when the seal was renewed for it
    # (which only Emil's installation does): staged control files must equal their sealed hash.
    seal = json.loads(SEAL.read_text(encoding="utf-8")).get("files", {})
    for scopes, text, label in list(items):
        if "_protected_path" in scopes and is_protected(text):
            sealed_now = (seal.get(text) and (REPO / text).is_file()
                          and sha256_file(REPO / text) == seal[text])
            if sealed_now or text == "control/SEAL.json":    # the seal itself passed check_seal()
                items.remove((scopes, text, label))
    v = find_violation(rules, items)
    tree = _git("write-tree").strip()
    if v:
        return block(v, "git pre-commit")
    ledger({"event": "git pre-commit", "decision": "ALLOW", "tree": tree,
            "files": len([i for i in items if i[2] == "path"])})
    return 0


def mode_post_commit() -> int:
    head = _git("rev-parse", "HEAD").strip()
    tree = _git("rev-parse", "HEAD^{tree}").strip()
    ledger({"event": "git commit", "decision": "RECORDED", "commit": head, "tree": tree})
    return 0


def mode_pre_push(stdin_text: str) -> int:
    """Every commit being pushed must have passed this gate (a ledger row with its tree)."""
    check_seal()
    passed = set()
    try:
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") == "git commit":
                passed.add(row.get("commit"))
    except FileNotFoundError:
        pass
    missing = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        rng = local_sha if set(remote_sha) == {"0"} else f"{remote_sha}..{local_sha}"
        for c in _git("rev-list", rng).split():
            if c not in passed:
                missing.append(c)
    if missing:
        v = {"id": "P03", "r": "R71 B3 / R72 Q1(ii)", "matched": ",".join(m[:10] for m in missing[:5]),
             "quote": "комит, който не е минал през вратата, не се пуска", "where": "push"}
        return block(v, "git pre-push")
    ledger({"event": "git pre-push", "decision": "ALLOW", "commits_checked": "all in ledger"})
    return 0


def mode_canary() -> int:
    """A forbidden action that MUST be blocked. Run at installation and every night."""
    probe = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "curl -s https" + "://api." + "groq" + ".com/openai/v1/models"}}
    env = dict(os.environ, CONTROL_NO_TELEGRAM="1")
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "hook"],
                       input=json.dumps(probe).encode(), capture_output=True, env=env)
    ok = r.returncode == 2 and b"F01" in r.stderr
    ledger({"event": "canary", "decision": "OK" if ok else "CANARY_FAILED", "rc": r.returncode})
    print("CANARY " + ("OK: the forbidden call was blocked" if ok else
                       f"FAILED: rc={r.returncode} {r.stderr[:200]!r}"))
    return 0 if ok else 1


def mode_seal(paths: list) -> int:
    files = {rel: sha256_file(REPO / rel) for rel in paths}
    SEAL.write_text(json.dumps({"sealed": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": files},
                               indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(files, indent=2))
    return 0


def main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else "hook"
    try:
        if mode == "hook":
            return mode_hook()
        if mode == "pre-commit":
            return mode_pre_commit()
        if mode == "post-commit":
            return mode_post_commit()
        if mode == "pre-push":
            return mode_pre_push(sys.stdin.read())
        if mode == "canary":
            return mode_canary()
        if mode == "seal":
            return mode_seal(argv[2:])
        if mode == "verify":
            v = verify_ledger()
            print(json.dumps(v))
            return 0 if v["ok"] else 1
        raise GateError(f"unknown mode {mode!r}")
    except Exception as e:                      # FAIL-CLOSED: an error is a block
        print(f"CONTROL GATE ERROR - blocked (fail-closed): {type(e).__name__}: {e}", file=sys.stderr)
        try:
            ledger({"event": f"error in {mode}", "decision": "BLOCK", "error": f"{type(e).__name__}: {e}"[:300]})
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

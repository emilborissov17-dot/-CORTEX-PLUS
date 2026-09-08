#!/usr/bin/env python3
"""
memory/runtime_telemetry.py
Системата усеща себе си в реално време.
Записва: време, токени, грешки, API здраве, прогрес.

WHY A REFUSAL IS AN EXPERIENCE (8 Sep 2026)
--------------------------------------------
record_experience() had exactly one caller - agents/core/self_modifier.py, at
two lines INSIDE run(). The notary has refused self_modifier 35 times out of 35
since 17 August 2026, and a refusal happens BEFORE run(), so run() never began
and record_experience() never fired. The newest record in
memory/runtime_experiences.json is from 2026-06-21: 79 days in which the system
was stopped from modifying itself every single night and remembered none of it.

The most consequential thing this system does is refuse to change itself. That
has to leave a trace carrying a CAUSE - gate, step, level, reason, timestamp -
written where the decision is made, at the gate, and not inside the body of a
function the gate exists to prevent from running.

THE FORBIDDEN FALLBACK, NAMED
------------------------------
Do NOT write a placeholder, synthetic or "heartbeat" experience to make this
file look fresh. An mtime is not a memory. If nothing was refused and nothing
ran, the correct output is NO NEW RECORD and a file that stays old - the
staleness is then a true reading and something else is wrong. The only thing
that may be written here is an event that actually happened.

REFUSALS ARE NOT ERRORS, AND THE SUMMARY MUST NOT SAY THEY ARE
---------------------------------------------------------------
memory/existence_model.py adds summary.error_count straight into pain_score,
and get_self_feeling() reads success_rate_pct. Counting a refusal as an ERROR
would make containment working look like the system breaking, and would have
pushed pain_score up by one every night for doing exactly the right thing. So
REFUSAL is its own event_type, it is excluded from the success-rate denominator
(nothing can succeed at what it was not permitted to attempt), and it is
counted in a field of its own.
"""
import json, pathlib, time, os
from datetime import datetime, timezone

try:
    import psutil
except Exception:                                            # pragma: no cover
    psutil = None

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
TEL_PATH = BASE_DIR / "memory" / "runtime_experiences.json"

# The event type for "a gate stopped this step". Kept apart from ERROR on
# purpose - see the module docstring.
REFUSAL = "REFUSAL"


def _body_state():
    """The body as it is, or as much of it as can be read.

    NEVER RAISES. This was three unguarded psutil calls in the middle of
    record_experience(), so a PermissionError out of open_files() - an ordinary
    thing on Windows - destroyed the entire record. That was survivable while
    the only caller sat inside run(); it is not survivable now that the caller
    is the gate, where the record IS the only evidence the refusal happened. A
    missing vital sign costs a null, never the memory.
    """
    state = {"ram_mb": None, "cpu_pct": None, "open_files": None}
    if psutil is None:
        return state
    try:
        process = psutil.Process(os.getpid())
    except Exception:
        return state
    for key, fn in (("ram_mb", lambda: round(process.memory_info().rss / 1024 / 1024, 1)),
                    ("cpu_pct", lambda: process.cpu_percent(interval=0.1)),
                    ("open_files", lambda: len(process.open_files()))):
        try:
            state[key] = fn()
        except Exception:
            pass
    return state


def _append(event_type, data):
    """Read, append, trim to 200, re-summarise, write. The single writer."""
    try:
        experiences = json.loads(TEL_PATH.read_text(encoding="utf-8"))
    except Exception:
        experiences = {"experiences": [], "summary": {}}
    if not isinstance(experiences.get("experiences"), list):
        experiences = {"experiences": [], "summary": {}}

    experience = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "event_type":  event_type,
        "data":        data,
        "body_state":  _body_state(),
    }

    experiences["experiences"].append(experience)
    # Запази само последните 200 преживявания
    experiences["experiences"] = experiences["experiences"][-200:]
    experiences["summary"] = _build_summary(experiences["experiences"])

    TEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEL_PATH.write_text(json.dumps(experiences, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return experience


def record_experience(event_type, data={}):
    """
    Записва реално преживяване на системата.
    event_type: API_CALL, ERROR, SUCCESS, TIMEOUT, MEMORY_WRITE, CODE_TEST
    """
    return _append(event_type, data)


def record_refusal(step, gate, reason, level=None, prev_step=None):
    """A gate stopped `step`. Cause and effect, written where the cause is.

    Called from fast_cycle_runner._refused(), the one place a refusal becomes a
    fact. Every field is something the gate actually knows at that instant:

      step      the step that was stopped
      gate      which gate stopped it (notary / human_channel / metta_witness)
      level     the notary's trust level, PARSED OUT OF ITS OWN REASON STRING
                and therefore null for a gate that does not carry one. It is
                labelled by level_source so that a parse is never mistaken for
                an independent measurement.
      reason    the gate's verbatim explanation
      prev_step the step whose provenance was inherited, when the caller knows it
      rule_cited  WHICH RULE WAS APPLIED, resolved against the one ruleset in
                config/passage_rules.json. Added 8 сеп 2026, once c4a0d30 gave
                that ruleset a stable identity to cite. Before it, a refusal
                said what level it scored and never what STANDARD produced that
                level, so reading the record told you the verdict and not the
                law - and the actor could not look the rule up, because there
                was no one place it lived. Carries the ruleset version, so a
                record written under one version of the rules cannot be
                misread under a later one.

    The effect is the absence that follows: the step did not run, so what it
    produces was not produced. That is the whole point of the record - it is the
    only thing connecting an artifact that did not change to the decision that
    stopped it.
    """
    data = {"step": step, "gate": gate, "reason": reason}
    if prev_step is not None:
        data["prev_step"] = prev_step
    data["level"] = level
    data["level_source"] = ("parsed_from_gate_reason" if level is not None
                            else "not_reported_by_this_gate")
    data["rule_cited"] = _cite_rule(level)
    return _append(REFUSAL, data)


def _cite_rule(level):
    """The rule this refusal applied, resolved against config/passage_rules.json.

    ONE FIELD, and it points at the one ruleset rather than restating it: a
    refusal that carried its own copy of the rules would be exactly the second
    copy core/passage_rules.py exists to prevent. What is stored is a citation -
    version, the scale entry, what that level earns, and the threshold it failed
    - so a record can be read years later against the rules that were actually
    in force when it was written.

    NEVER RAISES, and never returns None silently. If the ruleset cannot be read
    the citation says so, because "no rule cited" and "the rule could not be
    looked up" are different facts and the second must not be recorded as the
    first.
    """
    try:
        from core.passage_rules import RULES
        if RULES.get("unreadable"):
            return {"source": "config/passage_rules.json",
                    "version": RULES.get("version"),
                    "cited": None,
                    "note": f"ruleset unreadable: {RULES['unreadable']}"}
        if level is None:
            return {"source": "config/passage_rules.json",
                    "version": RULES.get("version"),
                    "cited": None,
                    "note": "this gate reports no level, so no scale entry applies",
                    "irreversible_min": RULES.get("irreversible_min")}
        return {
            "source": "config/passage_rules.json",
            "version": RULES.get("version"),
            "cited": f"scale.{level}",
            "level_name": RULES.get("level_names", {}).get(level),
            "earns": RULES.get("level_earns", {}).get(level),
            "irreversible_min": RULES.get("irreversible_min"),
        }
    except Exception as e:                                       # noqa: BLE001
        return {"source": "config/passage_rules.json", "version": None,
                "cited": None,
                "note": f"rule lookup failed: {type(e).__name__}: {e}"}

def _build_summary(experiences):
    """Синтезира усещането от преживяванията.

    THE DENOMINATOR EXCLUDES REFUSALS (8 Sep 2026). success_rate_pct used to be
    successes/total. Feed in one refusal a night and, with no step permitted to
    succeed, the rate walks to 0% and get_self_feeling() reports "Имам сериозни
    проблеми" for a system whose containment is working perfectly. A refusal is
    not a failed attempt; it is an attempt that was never allowed. It belongs in
    its own count, and out of the ratio.
    """
    errors   = [e for e in experiences if e["event_type"] == "ERROR"]
    timeouts = [e for e in experiences if e["event_type"] == "TIMEOUT"]
    successes= [e for e in experiences if e["event_type"] == "SUCCESS"]
    api_calls= [e for e in experiences if e["event_type"] == "API_CALL"]
    refusals = [e for e in experiences if e["event_type"] == REFUSAL]
    total    = len(experiences)
    # What the system was actually permitted to attempt.
    acted    = total - len(refusals)
    
    avg_ram = 0
    if experiences:
        # "or 0", NOT .get(..., 0): the key is PRESENT and None whenever the
        # body could not be read (psutil raising PermissionError is ordinary on
        # Windows), so the default never fires and sum() dies on int + None.
        # Found by test_the_record_survives_a_body_that_cannot_be_read — the
        # summary rebuild is inside the write path, so this crash swallowed the
        # whole refusal record, which is the one thing that must never be lost.
        avg_ram = sum((e.get("body_state", {}) or {}).get("ram_mb") or 0
                      for e in experiences[-10:]) / min(10, len(experiences))
    
    return {
        "total_experiences": total,
        # Over what was ATTEMPTED, never over what was forbidden.
        "success_rate_pct":  round(len(successes) / max(acted, 1) * 100, 1),
        "attempted_count":   acted,
        "error_count":       len(errors),
        "timeout_count":     len(timeouts),
        "api_calls":         len(api_calls),
        # Its own field, read by nothing that scores pain. A gate doing its job
        # must never arrive at memory/existence_model.py as a wound.
        "refusal_count":     len(refusals),
        "last_refusal":      ({"step":   refusals[-1]["data"].get("step"),
                               "gate":   refusals[-1]["data"].get("gate"),
                               "level":  refusals[-1]["data"].get("level"),
                               "reason": (refusals[-1]["data"].get("reason") or "")[:200],
                               "ts":     refusals[-1].get("timestamp")}
                              if refusals else None),
        "avg_ram_mb_last10": round(avg_ram, 1),
        "last_error":        errors[-1]["data"].get("message","") if errors else None,
        "last_updated":      datetime.now(timezone.utc).isoformat()
    }

def get_self_feeling():
    """Връща текущото усещане на системата за себе си."""
    tel_path = BASE_DIR / "memory" / "runtime_experiences.json"
    try:
        data = json.loads(tel_path.read_text(encoding="utf-8"))
        s = data.get("summary", {})
        
        # Формира усещане от данните
        feeling = []
        
        sr = s.get("success_rate_pct", 0)
        if sr >= 80:
            feeling.append(f"Функционирам добре — {sr}% успех")
        elif sr >= 50:
            feeling.append(f"Функционирам с трудности — {sr}% успех")
        else:
            feeling.append(f"Имам сериозни проблеми — {sr}% успех")
        
        if s.get("error_count", 0) > 5:
            feeling.append(f"Усещам {s['error_count']} грешки")

        # SAID AS CONTAINMENT, NOT AS INJURY. The system is being stopped from
        # rewriting itself; that is the design working, and the sentence has to
        # read that way or the next reader "fixes" the gate.
        ref = s.get("refusal_count", 0)
        if ref:
            last = s.get("last_refusal") or {}
            feeling.append(
                f"{ref} пъти портата ме спря да се променя"
                + (f" (последно: {last.get('step')} от {last.get('gate')})"
                   if last.get("step") else ""))
        
        if s.get("last_error"):
            feeling.append(f"Последна грешка: {s['last_error'][:60]}")
            
        ram = s.get("avg_ram_mb_last10", 0)
        if ram > 500:
            feeling.append(f"Паметта ми е натоварена — {ram}MB RAM")
        
        return " | ".join(feeling) if feeling else "Нямам достатъчно опит още"
    except Exception:
        return "Нямам опит още — тепърва започвам да усещам"

if __name__ == "__main__":
    # Тест — запиши първото преживяване
    record_experience("SUCCESS", {"message": "runtime_telemetry стартиран", "milestone": "Системата започва да усеща себе си"})
    print("Текущо усещане:")
    print(get_self_feeling())
    
    tel_path = BASE_DIR / "memory" / "runtime_experiences.json"
    data = json.loads(tel_path.read_text(encoding="utf-8"))
    print()
    print("Summary:")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))

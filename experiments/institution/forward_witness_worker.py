"""
experiments/institution/forward_witness_worker.py — RF1-RF6 in MeTTa, the second opinion.

Runs in venv312_metta (hyperon + stdlib only, like metta_oracle_worker.py). Reads
{"facts": {"RF1": {...} | null, ...}} on stdin, writes
{"ok": true, "hyperon_version": ..., "results": {"RF1": true|false|"not_evaluated"}}.
The facts are extracted by forward_witness.py (shared with the Python reference);
the relations between them - comparisons, equalities, conjunctions - are evaluated
here by hyperon, independently of the Python reference.
"""
import json
import sys


def lit(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))


def AND(*xs):
    out = xs[0]
    for x in xs[1:]:
        out = "(and %s %s)" % (out, x)
    return out


def EQ(a, b):
    return "(== %s %s)" % (lit(a), lit(b))


def GT(a, b):
    return "(> %s %s)" % (lit(a), lit(b))


def program(rule, f):
    if rule == "RF1":
        return AND(EQ(f["found"], True), EQ(f["status_prefix"], "confirmed"))
    if rule == "RF2":
        return AND(GT(f["registered"], f["commitment_date"]), GT(f["window_start"], f["registered"]))
    if rule == "RF3":
        return AND(EQ(f["ws_d"], 1), EQ(f["ws_y"], f["we_y"]), EQ(f["ws_m"], f["we_m"]),
                   EQ(f["we_d"], f["days_in_month"]), GT(f["stage1_late_by"], f["window_end"]),
                   EQ(f["stage1_rule_is_release_plus_14"], True), EQ(f["final_is_coverage_rule"], True))
    if rule == "RF4":
        return AND(EQ(f["row_kept_threshold"], f["config_threshold"]),
                   EQ(f["row_not_kept_threshold"], f["config_threshold"]))
    if rule == "RF5":
        return AND(EQ(f["sha_file"], f["sha_seal"]), EQ(f["sha_seal"], f["sha_signature"]))
    if rule == "RF6":
        return AND(EQ(f["as_of_row"], f["as_of_data"]), EQ(f["total_row"], f["total_recomputed"]),
                   EQ(f["mean_x100_row"], f["mean_x100_recomputed"]),
                   EQ(f["hits_row"], f["hits_recomputed"]), EQ(f["months_row"], f["months_recomputed"]),
                   EQ(f["p_x10000_row"], f["p_x10000_recomputed"]))
    raise KeyError(rule)


def main():
    req = json.loads(sys.stdin.read())
    try:
        import hyperon
        from hyperon import MeTTa
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "hyperon import: %s: %s" % (type(e).__name__, e)}))
        return
    m = MeTTa()
    out = {}
    progs = {}
    for rule, facts in sorted((req.get("facts") or {}).items()):
        if facts is None:
            out[rule] = "not_evaluated"
            continue
        try:
            prog = program(rule, facts)
            progs[rule] = prog
            res = m.run("!" + prog)
            vals = [str(x) for r in res for x in r]
            out[rule] = True if vals == ["True"] else (False if vals == ["False"] else "not_evaluated")
        except Exception as e:  # noqa: BLE001
            out[rule] = "not_evaluated"
            progs[rule] = "ERROR %s: %s" % (type(e).__name__, e)
    print(json.dumps({"ok": True, "hyperon_version": getattr(hyperon, "__version__", "?"),
                      "results": out, "programs": progs}))


if __name__ == "__main__":
    main()

"""
metta_oracle_worker — the half that runs INSIDE the 3.12 sidecar venv.

Reads one JSON request on stdin, answers one JSON response on stdout. Imports
hyperon and NOTHING from this repo: the sidecar exists precisely because hyperon
cannot be installed next to the main venv (Python 3.14, no hyperon wheel), so this
file must stay importable by a bare interpreter that knows only hyperon + stdlib.

  request : {"levels": {AXIS: concern 0-3}, "rules": [[id, src, need, tgt, floor], ...]}
  response: {"ok": true, "hyperon_version": "...", "derived": {...},
             "inconsistencies": [{axis, scored, implied, proofs: [...]}]}

Errors are ANSWERED, never raised: a crash here would surface to the caller as a
dead pipe, which is indistinguishable from "the oracle found nothing".
"""
import json
import sys


def main():
    try:
        req = json.load(sys.stdin)
    except Exception as e:
        json.dump({"ok": False, "error": f"unreadable request: {type(e).__name__}: {e}"},
                  sys.stdout)
        return

    try:
        import hyperon
        from hyperon import MeTTa

        levels = {str(k): int(v) for k, v in (req.get("levels") or {}).items()}
        rules = req.get("rules") or []

        m = MeTTa()
        prog = []
        for ax, c in levels.items():
            prog.append(f"(concern {ax} {c})")
        for r in rules:
            rid, src, need, tgt, fl = r
            prog.append(f"(rule {rid} {src} {need} {tgt} {fl})")
        prog.append("(= (eff $ax) (match &self (concern $ax $v) $v))")
        prog.append("(= (eff $ax) (match &self (rule $r $src $need $ax $fl) "
                    "(if (>= (eff $src) $need) $fl (empty))))")
        prog.append("(= (why $ax) (match &self (rule $r $src $need $ax $fl) "
                    "(if (>= (eff $src) $need) (fired $r from $src floor $fl) (empty))))")
        m.run("\n".join(prog))

        def vals(res):
            return [a for g in res for a in g]

        derived, bad = {}, []
        for ax in sorted({r[3] for r in rules}):
            if ax not in levels:
                continue
            got = []
            for x in vals(m.run(f"!(eff {ax})")):
                try:
                    got.append(int(str(x)))
                except ValueError:
                    pass
            floor = max(got) if got else levels[ax]
            derived[ax] = floor
            if floor > levels[ax]:
                bad.append({"axis": ax, "scored": levels[ax], "implied": floor,
                            "proofs": [str(w) for w in vals(m.run(f"!(why {ax})"))]})

        json.dump({"ok": True,
                   "hyperon_version": getattr(hyperon, "__version__", "unknown"),
                   "python": sys.version.split()[0],
                   "n_axes": len(levels), "n_rules": len(rules),
                   "derived": derived, "inconsistencies": bad}, sys.stdout)
    except Exception as e:
        json.dump({"ok": False, "error": f"{type(e).__name__}: {e}"}, sys.stdout)


if __name__ == "__main__":
    main()

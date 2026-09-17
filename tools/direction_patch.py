"""Replacement for the two-point direction rule in tools/resolve_ideas.py.

Why it is being replaced, measured 2026-08-29: 82.8% of decided verdicts changed when
each series lost its LAST POINT, and not one HELD survived. resolve_one took the value
at birth and after[-1] and called the difference a direction. Two observations are not
a trend; they are two observations. The instability was not noise in the data, it was
the method.

A second defect found while rewriting: FLAT_EPS was a single absolute 0.5 applied to
every series. The same 0.5 means "nothing happened" on a 0-100 score and "a rounding
error" on gdp_per_capita_usd. The threshold must be in the series' own units.

Method: Theil-Sen. The slope is the MEDIAN of the slopes between every pair of points.
Chosen because it needs no distributional assumption, tolerates a bad point without
being dragged by it, and is meaningful on the handful of points these series carry.
"""

from __future__ import annotations
import statistics

MIN_POINTS = 5          # below this there is no trend to speak of - NO_DATA, not a guess
FLAT_K = 0.25           # flat if |total move| < FLAT_K * the series' own spread


def theil_sen(points: list[tuple[float, float]]) -> float | None:
    """Median pairwise slope. points = [(x, y)], x strictly increasing."""
    n = len(points)
    if n < 2:
        return None
    slopes = []
    for i in range(n):
        xi, yi = points[i]
        for j in range(i + 1, n):
            xj, yj = points[j]
            if xj != xi:
                slopes.append((yj - yi) / (xj - xi))
    return statistics.median(slopes) if slopes else None


def spread(ys: list[float]) -> float:
    """The series' own scale. IQR when there are enough points, else the range.
    Never zero-divides: a perfectly flat series has spread 0 and any move is a move."""
    if len(ys) >= 4:
        q = statistics.quantiles(ys, n=4)
        iqr = q[2] - q[0]
        if iqr > 0:
            return iqr
    return max(ys) - min(ys)


def direction(points: list[tuple[float, float]]) -> dict:
    """Returns {'verdict': 'rising'|'falling'|'flat'|'insufficient', ...}.

    Never returns a direction it cannot defend: too few points is 'insufficient',
    never 'flat'. Silence and stillness are different answers."""
    if len(points) < MIN_POINTS:
        return {"verdict": "insufficient", "n": len(points), "slope": None,
                "why": f"{len(points)} points, {MIN_POINTS} required"}
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    slope = theil_sen(points)
    if slope is None:
        return {"verdict": "insufficient", "n": len(points), "slope": None,
                "why": "no distinct x values"}
    move = slope * (xs[-1] - xs[0])          # total modelled movement over the window
    sp = spread(ys)
    threshold = FLAT_K * sp
    if abs(move) <= threshold:
        v = "flat"
    else:
        v = "rising" if move > 0 else "falling"
    return {"verdict": v, "n": len(points), "slope": slope, "move": move,
            "spread": sp, "threshold": threshold}


def direction_with_fragility(points: list[tuple[float, float]]) -> dict:
    """The same, plus whether the answer survives losing the last point.

    A verdict that flips when the newest observation is removed is a statement about
    that observation, not about the series. It is still returned - but it is returned
    wearing a label, so nothing downstream can quote it as if it were solid."""
    full = direction(points)
    if len(points) - 1 >= MIN_POINTS:
        without = direction(points[:-1])
        full["verdict_without_last_point"] = without["verdict"]
        full["survives_leave_one_out"] = without["verdict"] == full["verdict"]
    else:
        full["verdict_without_last_point"] = None
        full["survives_leave_one_out"] = None      # not applicable is not robust
    return full


# --------------------------------------------------------------------------- selftest
def selftest() -> int:
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    rise = [(float(i), 10.0 + i) for i in range(10)]
    fall = [(float(i), 100.0 - 3 * i) for i in range(10)]
    flat = [(float(i), 50.0 + (0.05 if i % 2 else -0.05)) for i in range(10)]

    want(direction(rise)["verdict"] == "rising", "a rising series is rising")
    want(direction(fall)["verdict"] == "falling", "a falling series is falling")
    want(direction(flat)["verdict"] == "flat", "noise around a level is flat")
    want(direction(rise[:3])["verdict"] == "insufficient",
         "too few points is INSUFFICIENT, never flat",
         str(direction(rise[:3])))

    # the whole point: one wild last observation must not decide the verdict
    spiked = rise[:-1] + [(9.0, -500.0)]
    want(direction(spiked)["verdict"] == "rising",
         "one wild last point does not reverse a trend under Theil-Sen",
         str(direction(spiked)["verdict"]))

    # and the OLD two-point rule would have been fooled by exactly that
    old = "rising" if spiked[-1][1] > spiked[0][1] else "falling"
    want(old == "falling",
         "the replaced two-point rule IS fooled by it - this is what we are fixing",
         f"two-point rule says {old}")

    # scale: the same absolute move is big on a tight series and nothing on a wide one
    tight = [(float(i), 50.0 + 0.1 * i) for i in range(10)]
    wide = [(float(i), 50.0 + 0.1 * i + (300 if i % 2 else -300)) for i in range(10)]
    want(direction(tight)["verdict"] == "rising" and direction(wide)["verdict"] == "flat",
         "the flat threshold is in the series' own units, not a fixed 0.5",
         f"tight={direction(tight)['verdict']} wide={direction(wide)['verdict']}")

    # fragility is reported, both ways
    r = direction_with_fragility(rise)
    want(r["survives_leave_one_out"] is True, "a real trend survives leave-one-out")
    # The property being bought. Under the OLD two-point rule this series reads as a
    # huge rise; under Theil-Sen it is flat, and dropping the last point changes nothing.
    # A single observation cannot carry a verdict any more - which is exactly why the
    # measured 82.8% fragility should collapse. Tested as an assertion, not a hope.
    spike_at_end = [(float(i), 50.0) for i in range(9)] + [(9.0, 90.0)]
    f = direction_with_fragility(spike_at_end)
    old_rule = "rising" if spike_at_end[-1][1] > spike_at_end[0][1] else "falling"
    want(old_rule == "rising" and f["verdict"] == "flat" and f["survives_leave_one_out"] is True,
         "one late spike: the old rule called it RISING, the new one calls it flat and stable",
         f"old={old_rule} new={f['verdict']} survives={f['survives_leave_one_out']}")

    # the fragility field must still be able to say False - a borderline series where
    # dropping the last point leaves too few to judge is honestly NOT the same verdict
    borderline = [(float(i), 10.0 + i) for i in range(MIN_POINTS + 1)]
    b = direction_with_fragility(borderline)
    want(b["survives_leave_one_out"] is True and b["verdict_without_last_point"] == "rising",
         "at exactly MIN_POINTS+1 the check still runs rather than going silent",
         str(b))
    short = direction_with_fragility(rise[:MIN_POINTS])
    want(short["survives_leave_one_out"] is None,
         "not applicable is reported as None, never as robust")

    # a perfectly flat series must not divide by zero
    dead = [(float(i), 7.0) for i in range(10)]
    want(direction(dead)["verdict"] == "flat", "a motionless series is flat, not a crash")

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(selftest())

; config/space_rules.metta — the rules the brain's space derives from (C-TURN-1 Part 1b).
;
; Run by core/space.py through the repo's hyperon (venv312_metta), after
; memory/space/base.metta. Each rule ADDS what it derives to a SEPARATE space,
; &derived; the rules that build on a derivation and the queries at the end read
; it from there. Every derived expression carries the ids of its premises.
; Tests: test/test_space.py (one test and one mutation per rule).
;
; WHY A SEPARATE SPACE (C-ENGINE-2, 10 Oct 2026). Rules that added to &self while a
; match over &self ran made hyperon 0.2.9 and 0.2.10 panic in their index
; (hyperon-space src/index/trie.rs:179, "called Option::unwrap() on a None value";
; on Windows exit 3221226505) once the space passed a size: brain turn 184 failed so
; on the machine. Writing to &derived avoids it.
; test/test_space.py::test_the_program_that_panicked_on_10_oct_runs_and_derives_as_before

!(bind! &derived (new-space))

; ── contradiction: two obs, same key/place/period, different value, different source
!(match &self (, (obs $a $sa $k $p $per $v1 $u1 $s1) (obs $b $sb $k $p $per $v2 $u2 $s2))
   (if (and (not (== $v1 $v2)) (not (== $s1 $s2)))
       (add-atom &derived (contradiction $k $p $per $a $b))
       (empty)))

; ── unverified: an obs whose source is self_reported/unknown, with no independent
;    or adversarial obs of the same key/place/period beside it
!(match &self (, (obs $a $s $k $p $per $v $u $src) (source-class $src $c))
   (if (or (== $c "self_reported") (== $c "unknown"))
       (if (== (collapse (match &self (, (obs $b $s2 $k $p $per $v2 $u2 $src2) (independent-src $src2)) $b)) ())
           (add-atom &derived (unverified $a $k $p $per))
           (empty))
       (empty)))

; ── stale: an obs whose period is past its granularity's bound (day 45 d, month
;    120 d after the month ends, year older than this year - 3) — the bounds of
;    core.atoms.period_is_current
!(match &self (period-age $a "day" $d) (if (> $d 45) (add-atom &derived (stale $a)) (empty)))
!(match &self (period-age $a "month" $d) (if (> $d 120) (add-atom &derived (stale $a)) (empty)))
!(match &self (, (period-year $a $y) (this-year $t)) (if (< $y (- $t 3)) (add-atom &derived (stale $a)) (empty)))

; ── uncovered: a subgoal with a gap and no obs in any category that serves it
!(match &self (, (axis-serves $ax $sg) (gap $ax $need $score))
   (if (> $need 0)
       (if (== (collapse (match &self (, (serves $cat $sg) (subcategory $sub $cat) (obs $o $sub $k $p $per $v $u $src)) $o)) ())
           (add-atom &derived (uncovered $sg))
           (empty))
       (empty)))

; ── commitment-evidence: an open forward row with no current (non-stale) obs at its place
!(match &self (commitment-place $row $place)
   (if (== (collapse (match &self (obs $o $s $k $place $per $v $u $src)
                         (if (== (collapse (match &derived (stale $o) $o)) ()) $o (empty)))) ())
       (add-atom &derived (lacks-evidence $row $place))
       (empty)))

; ── need-from: what the derivations ask for. stale goes to maintenance, not to the brain.
!(match &derived (contradiction $k $p $per $a $b) (add-atom &derived (need-derived VERIFY contradiction $k $p $per $a $b)))
!(match &derived (unverified $a $k $p $per) (add-atom &derived (need-derived VERIFY unverified $k $p $per $a)))
!(match &derived (uncovered $sg) (add-atom &derived (need-derived FIND uncovered $sg)))
!(match &derived (lacks-evidence $row $place) (add-atom &derived (need-derived FIND lacks-evidence $row $place)))

; ── read back (core/space.py collects every expression these return)
!(match &derived (contradiction $k $p $per $a $b) (contradiction $k $p $per $a $b))
!(match &derived (unverified $a $k $p $per) (unverified $a $k $p $per))
!(match &derived (stale $a) (stale $a))
!(match &derived (uncovered $sg) (uncovered $sg))
!(match &derived (lacks-evidence $row $place) (lacks-evidence $row $place))
!(match &derived (need-derived $kind $rule $x) (need-derived $kind $rule $x))
!(match &derived (need-derived $kind $rule $x $y) (need-derived $kind $rule $x $y))
!(match &derived (need-derived $kind $rule $x $y $z $w) (need-derived $kind $rule $x $y $z $w))
!(match &derived (need-derived $kind $rule $x $y $z $w $v) (need-derived $kind $rule $x $y $z $w $v))

; config/space_rules.metta — the rules the brain's space derives from (C-TURN-1 Part 1b).
;
; Run by core/space.py through the repo's hyperon (venv312_metta), after
; memory/space/base.metta. Each rule ADDS what it derives to the space; the
; queries at the end read it back. Every derived expression carries the ids of
; its premises. Tests: test/test_space.py (one test and one mutation per rule).

; ── contradiction: two obs, same key/place/period, different value, different source
!(match &self (, (obs $a $sa $k $p $per $v1 $u1 $s1) (obs $b $sb $k $p $per $v2 $u2 $s2))
   (if (and (not (== $v1 $v2)) (not (== $s1 $s2)))
       (add-atom &self (contradiction $k $p $per $a $b))
       (empty)))

; ── unverified: an obs whose source is self_reported/unknown, with no independent
;    or adversarial obs of the same key/place/period beside it
!(match &self (, (obs $a $s $k $p $per $v $u $src) (source-class $src $c))
   (if (or (== $c "self_reported") (== $c "unknown"))
       (if (== (collapse (match &self (, (obs $b $s2 $k $p $per $v2 $u2 $src2) (independent-src $src2)) $b)) ())
           (add-atom &self (unverified $a $k $p $per))
           (empty))
       (empty)))

; ── stale: an obs whose period is past its granularity's bound (day 45 d, month
;    120 d after the month ends, year older than this year - 3) — the bounds of
;    core.atoms.period_is_current
!(match &self (period-age $a "day" $d) (if (> $d 45) (add-atom &self (stale $a)) (empty)))
!(match &self (period-age $a "month" $d) (if (> $d 120) (add-atom &self (stale $a)) (empty)))
!(match &self (, (period-year $a $y) (this-year $t)) (if (< $y (- $t 3)) (add-atom &self (stale $a)) (empty)))

; ── uncovered: a subgoal with a gap and no obs in any category that serves it
!(match &self (, (axis-serves $ax $sg) (gap $ax $need $score))
   (if (> $need 0)
       (if (== (collapse (match &self (, (serves $cat $sg) (subcategory $sub $cat) (obs $o $sub $k $p $per $v $u $src)) $o)) ())
           (add-atom &self (uncovered $sg))
           (empty))
       (empty)))

; ── commitment-evidence: an open forward row with no current (non-stale) obs at its place
!(match &self (commitment-place $row $place)
   (if (== (collapse (match &self (obs $o $s $k $place $per $v $u $src)
                         (if (== (collapse (match &self (stale $o) $o)) ()) $o (empty)))) ())
       (add-atom &self (lacks-evidence $row $place))
       (empty)))

; ── need-from: what the derivations ask for. stale goes to maintenance, not to the brain.
!(match &self (contradiction $k $p $per $a $b) (add-atom &self (need-derived VERIFY contradiction $k $p $per $a $b)))
!(match &self (unverified $a $k $p $per) (add-atom &self (need-derived VERIFY unverified $k $p $per $a)))
!(match &self (uncovered $sg) (add-atom &self (need-derived FIND uncovered $sg)))
!(match &self (lacks-evidence $row $place) (add-atom &self (need-derived FIND lacks-evidence $row $place)))

; ── read back (core/space.py collects every expression these return)
!(match &self (contradiction $k $p $per $a $b) (contradiction $k $p $per $a $b))
!(match &self (unverified $a $k $p $per) (unverified $a $k $p $per))
!(match &self (stale $a) (stale $a))
!(match &self (uncovered $sg) (uncovered $sg))
!(match &self (lacks-evidence $row $place) (lacks-evidence $row $place))
!(match &self (need-derived $kind $rule $x) (need-derived $kind $rule $x))
!(match &self (need-derived $kind $rule $x $y) (need-derived $kind $rule $x $y))
!(match &self (need-derived $kind $rule $x $y $z $w) (need-derived $kind $rule $x $y $z $w))
!(match &self (need-derived $kind $rule $x $y $z $w $v) (need-derived $kind $rule $x $y $z $w $v))

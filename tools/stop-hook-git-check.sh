#!/usr/bin/env bash
# tools/stop-hook-git-check.sh — WARN ABOUT CODE DRIFT, NOT ABOUT BREATHING.
#
# A Claude Code Stop hook. It looks at the working tree when a turn ends and
# says something ONLY if real work is sitting uncommitted.
#
# WHY THE FILTER EXISTS
# ----------------------
# CORTEX++ writes to disk as a condition of being alive. One cycle rewrites
# memory/, snapshots/, news/, daily/, knowledge/, data/, cortex_memory/,
# output/, openclaw_queue/ — scores, ledgers, latest snapshots, the heartbeat.
# `git status` in this repo right now: 697 changed paths, of which 594 are that.
# None of them are ever committed, by policy.
#
# A check that counts those reports "you have 697 uncommitted changes" after
# every single turn, which is the same as reporting nothing: the number is always
# huge, so it never means anything, and the one time it hides an uncommitted
# module the human scrolls past it. The runtime paths are not "less important"
# here. They are NOT SIGNAL AT ALL, and are dropped before counting.
#
# CODE IS NEVER NOISE, WHEREVER IT SITS
# ---------------------------------------
# The obvious failure of a prefix filter is the day someone puts a .py under one
# of these directories and the check goes quiet about it forever. So the filter
# is not the last word: anything that looks like code or configuration is
# reported even when it lives under an ignored prefix. Verified before this list
# was widened — none of these directories currently holds a single .py, and if
# one ever does, ALWAYS_LOUD catches it.
#
# The list is deliberately literal. A path that starts producing churn gets added
# here, by hand, with a reason — never a wildcard that quietly grows until the
# check filters out the thing it was built to find.
#
# CONTRACT: never blocks. Exit 0 always, even on error. A hook that can stand
# between the human and the end of a turn is a hook that will one day do exactly
# that, over a git failure that has nothing to do with them.
#
#     bash tools/stop-hook-git-check.sh --selftest

set -uo pipefail

# Runtime churn: written by the cycle, never committed.
#   knowledge news daily snapshots memory   — Emil's list, 22 Aug 2026
#   data cortex_memory output               — scores, hypergraph, WB cache, essence
#   openclaw_queue daily_signals agents/out — queue feeds and agent scratch output
IGNORED_PREFIXES='^(knowledge|memory|snapshots|news|daily|data|cortex_memory|output|openclaw_queue|daily_signals|agents/out)/'

# Reported no matter where it lives. The escape hatch for the prefix list.
# [.] rather than \. — awk reads the backslash out of the string before the
# regex ever sees it, and warns about it on every single line.
ALWAYS_LOUD='([.](py|sh|bat|ps1|toml|cfg|ini|ya?ml)$|^config/|^[.]github/)'

MAX_LISTED=8

changed_paths() {
    # cut -c4- strips the two status columns and the space.
    # "old -> new" is a rename: judge it by where the file landed.
    # Git quotes paths with odd bytes; strip the quotes so the prefix matches.
    git status --porcelain 2>/dev/null \
        | cut -c4- \
        | sed -e 's/^.* -> //' -e 's/^"//' -e 's/"$//' \
        | grep -v '^$'
}

# One awk pass, because the prefix filter and the always-loud escape hatch have
# to be applied in that order to the same line — two greps cannot express "drop
# this unless it is code".
drift() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    changed_paths | awk -v ign="$IGNORED_PREFIXES" -v loud="$ALWAYS_LOUD" '
        $0 ~ loud { print; next }
        $0 ~ ign  { next }
        { print }
    '
}

main() {
    local paths count
    paths=$(drift)
    [ -z "$paths" ] && exit 0

    count=$(printf '%s\n' "$paths" | wc -l | tr -d ' ')
    echo "UNCOMMITTED: $count code/config path(s) (runtime churn excluded)"
    printf '%s\n' "$paths" | head -n "$MAX_LISTED" | sed 's/^/  /'
    if [ "$count" -gt "$MAX_LISTED" ]; then
        echo "  ... and $((count - MAX_LISTED)) more"
    fi
    exit 0
}

selftest() {
    echo "tools/stop-hook-git-check.sh --selftest"
    echo "  repo                 $(git rev-parse --show-toplevel 2>/dev/null || echo 'NOT A GIT REPO')"

    local all real noise
    all=$(changed_paths | grep -c '' || true)
    real=$(drift | grep -c '' || true)
    noise=$((all - real))
    echo "  git status says      $all changed path(s)"
    echo "  runtime churn        $noise filtered"
    echo "  reported as drift    $real"

    # Asserted against literal names, not the live tree, so the check still
    # means something on a clean checkout.
    local ok=0 verdict
    check() {   # path, expected: QUIET | LOUD
        verdict=$(printf '%s\n' "$1" | awk -v ign="$IGNORED_PREFIXES" -v loud="$ALWAYS_LOUD" '
            $0 ~ loud { print "LOUD"; next }
            $0 ~ ign  { print "QUIET"; next }
            { print "LOUD" }')
        if [ "$verdict" = "$2" ]; then
            echo "  OK    $2  $1"
        else
            echo "  FAIL  wanted $2, got $verdict: $1"; ok=1
        fi
    }

    for p in memory/state.json snapshots/body/x.json news/news_latest.json \
             daily/2026-08-22.md knowledge/base.json data/cortex_hypergraph.json \
             cortex_memory/abstractions/essence.md output/wb_cache/BG.json \
             openclaw_queue/axis_feeds.jsonl agents/out/energy_review_qwen.txt; do
        check "$p" QUIET
    done
    for p in core/survival_mode.py test/test_x.py fast_cycle_runner.py \
             docs/AUDIT.md plans/plan-2026-08-22.md agents/core/goal_planner.py; do
        check "$p" LOUD
    done
    # The escape hatch: code under an ignored prefix is still reported.
    for p in memory/heartbeat.py data/loader.py config/scheduler.json \
             snapshots/tool.sh .github/workflows/ci.yml; do
        check "$p" LOUD
    done

    echo "  RESULT: $([ $ok -eq 0 ] && echo OK || echo BROKEN)"
    return $ok
}

case "${1:-}" in
    --selftest) selftest ;;
    *)          main ;;
esac

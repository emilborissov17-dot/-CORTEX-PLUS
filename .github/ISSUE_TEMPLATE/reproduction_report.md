---
name: Reproduction report
about: You ran the suite on your machine. Tell us what you got — before you read what we got.
title: "repro: <OS> <commit> — <one line>"
labels: reproduction
---

<!--
READ THIS FIRST.

Fill in sections 1-4 BEFORE opening docs/KNOWN_FORK_FINDINGS.md or any of our
numbers. A reproduction that starts by looking up the expected answer is not a
reproduction; it is a spot-the-difference puzzle, and the differences it finds
are the ones you were already looking for.

Section 5 is where you compare. Fill it in last.

An issue with sections 1-4 and nothing else is welcome and useful. An issue with
only section 5 is not.
-->

## 1. Machine

- **OS and version:**
- **Python:** <!-- output of `python --version` — the exact interpreter you used -->
- **How you installed deps:** <!-- `pip install -r requirements.txt`, conda, distro packages, ... -->
- **Any pin you could not satisfy:** <!-- this alone is a finding worth filing -->

## 2. Commit

- **Commit hash:** <!-- `git rev-parse HEAD` -->
- **Branch:**
- **Working tree clean?** <!-- `git status --porcelain` — paste it if not -->

## 3. Suite result

Paste the last line of `python -m pytest test/ -q` verbatim:

```
<e.g. 20 failed, 1266 passed, 1 skipped, 1 xfailed in 520.78s>
```

And the `short test summary info` block:

```

```

## 4. First divergence

The first place your run stops matching what the repo's own artifacts say — a
test that fails here and is not in our known-red list, a number in
`output/cortex_scores_latest.json` that differs, a step that dies where ours
does not.

- **Where:** <!-- file:line, test name, or artifact path -->
- **What you got:**
- **What the repo said it should be:** <!-- from a committed artifact, not from our docs -->
- **Full output:**

```

```

## 5. Only now: compare with ours

`docs/KNOWN_FORK_FINDINGS.md` lists what we already know is broken. After
filling in everything above:

- [ ] My divergence is already in KNOWN_FORK_FINDINGS.md — <!-- which one? -->
- [ ] My divergence is new
- [ ] My numbers match ours and I am reporting that, which is also useful

**Anything our list gets wrong:**
<!-- If a finding of ours does not reproduce on your machine, say so. A known
     failure that is actually machine-specific is a worse defect than an
     unknown one, because it has already been written down as settled. -->

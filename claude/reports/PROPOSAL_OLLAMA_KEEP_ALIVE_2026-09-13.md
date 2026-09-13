# PROPOSAL — asking ollama to let go, and what it would actually free

13 September 2026. **Nothing implemented. Numbers and a recommendation; Emil decides.**

---

## The idea, and it is sound

`core/aggressive_cleanup.release_working_set` trims our own working set — about
30 MB — and refuses to touch another process. That refusal is correct and should
stay: the machine belongs to a human and a cleaner that kills what it did not
start is not a cleaner.

But ollama has a public door. `POST /api/generate` with `{"model": "...",
"keep_alive": 0}` asks the server to unload a model it is holding. We are the ones
who asked it to load; asking it to let go is a request through the interface it
publishes, not a kill.

## What it would free, measured just now rather than assumed

```
RAM available            537 MB   (96.2% used — above the 92% gate, right now)
ollama.exe pid 2512      80 MB    RSS
ollama.exe pid 289604   872 MB    RSS
/api/ps: qwen2.5:3b     size 2208 MB   size_vram 2208 MB   expires 13:22:41
```

**The model is in VRAM, not in system RAM.** `size` and `size_vram` are the same
number, so all 2208 MB of it sits on the GPU. The survival gate reads
`psutil.virtual_memory()`, which does not see VRAM at all.

So the honest estimate of what `keep_alive: 0` returns to the gate is **not
2.2 GB**. It is whatever the ollama server process releases from its own RSS when
it drops the model — bounded above by the **872 MB** that process currently holds,
and in practice less, because an allocator returning pages to the OS is a hope
rather than a guarantee.

That is still worth having. At this moment it would move the machine from 537 MB
to somewhere near 1.4 GB — across the 92% gate line (~1.1 GB on this 14.2 GB
machine), though still well under the 2444 MB that is the lowest start from which
a cycle has ever finished.

## When it helps

**A model left resident by a cycle that died.** This is the real case and it
happened twice today. A cycle loads a model, dies, and the model keeps its
keep_alive timer running with nobody to use it. Today's expiry was 13:22:41 —
five minutes of a dead cycle's model still parked. If the supervisor's new
pre-spawn check refuses at 09:34 because of memory a corpse is holding, the
polite request is exactly the right move and costs a reload nobody was going to
avoid anyway.

**Before a long non-model step.** `web_intelligence` and the snapshot agents do
not need the local model; holding it through them buys nothing.

## When it is pointless, or worse

**When the next step needs the model in seconds.** `core/model_window.py` already
exists precisely because unloading and reloading around every step was measured to
be the wrong trade — the 8b window is held open deliberately so steps inside it do
not thrash. Adding an unload that fires during that window would undo a decision
that was made with evidence.

**When the pressure is not the model.** Today at 09:34 the machine had 138 MB
free. The model was 2208 MB of VRAM; the 14 GB of system memory were being held by
something else entirely — Chrome, Edge, Discord and the dying cycle's own
children. Unloading would have returned a few hundred megabytes into a hole an
order of magnitude larger. It would not have saved that night.

**When it hides the real cause.** A cleanup that reliably buys 800 MB makes it
comfortable to keep running a cycle on a machine that has 500 MB, and the next
failure arrives later and less legibly. The thing that actually killed three
cycles today is a browser with thirty processes running inside the night, and that
is being fixed by moving the fetching out — not by finding more memory to feed it.

## Recommendation

**Yes, but narrowly, and not as a general cleanup step.**

Put it in exactly one place: `core/aggressive_cleanup.cure_refusal`, on the path
that already runs before a refusal is charged, and only when the gate is ALREADY
refusing. Never on a schedule, never before a step, never while
`core/model_window.is_open()` says the window is deliberately held.

Three conditions worth writing into it:

1. **Only when the gate is refusing.** It is a cure, not hygiene.
2. **Only when `model_window.is_open()` is False.** The window was a measured
   decision and this must not quietly reverse it. `_free_ollama()` in the runner
   already respects exactly this condition — the precedent exists.
3. **Record the before and after.** `available` before, after, and the model that
   was dropped. Without that, the next person cannot tell whether it did anything,
   and "it probably helps" is how a cleanup survives long after it stopped
   working.

**What I would not do:** add it to the nightly path, or use it to justify raising
the number of cycles the machine attempts. The gate exists to stop cycles that
cannot finish; a cleanup that makes marginal cycles start is the gate leaking.

## One number that is not in this file

How much RSS the ollama server actually returns on unload. It can be measured in
about a minute — read `available`, POST `keep_alive: 0`, wait five seconds, read
again — but it changes live state on a machine currently at 96.2%, and this is a
proposal. If you want the number before deciding, say so and I will take it.

"""
core/self_improve — THE SPLIT: the brain writes the SPEC, a specialist writes the CODE.

EXPERIMENTAL. On branch experimental/self-mod. Nothing in this package is wired
into fast_cycle_runner.py, core/notary.py or the nightly cycle, and none of it
writes to production memory/ or snapshots/. It runs only when a human invokes
tools/self_improve_pipeline.py.

WHY THE SPLIT (measured, 2026-08-04)
------------------------------------
The local model never closes the write -> test -> fix loop: 0 out of 3, with
identical retries at any temperature. The cloud model closes it 3 out of 3. But
the local brain is the one that KNOWS this system — it is what runs every night,
reads its own journal and observes its own failures.

So neither model is asked to do the other's job:

    requirer      local brain (qwen)  -> a SPEC, and never a line of code
    implementer   cloud ladder        -> a patch, from a spec it did not write

The spec/code boundary already exists inside agents/core/self_modifier.py and is
crossed in one place — see requirer.py's docstring for the exact line. This
package makes that crossing explicit and puts a different model on each side.
"""

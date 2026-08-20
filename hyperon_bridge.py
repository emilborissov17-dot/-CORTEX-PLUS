#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
hyperon_bridge.py — the MeTTa entry point for this repo.

WHAT THIS USED TO BE
---------------------
Eighteen lines that registered a token called "cortex-qwen" whose implementation
was:

    def call_cortex_qwen(prompt): return f"[CORTEX-QWEN MOCK RESPONSE] {prompt}"

and ran `!(cortex-qwen "ENERGY REVIEW")` to print the echo back. Nothing called
it, and it demonstrated only that MeTTa can call a Python function — which was
never in doubt. A file named "bridge" that bridges to a mock is worse than no
file: it reads, at a glance, as a working symbolic integration.

WHAT IT IS NOW
---------------
A thin front door onto core/metta_parallel.py, which emits a real MeTTa program
over the axis feeds and evaluates it — through hyperon in the venv312_metta
sidecar when that exists, through an equivalent Python reference otherwise, with
the engine recorded either way.

    venv\\Scripts\\python.exe hyperon_bridge.py            # run and print
    venv\\Scripts\\python.exe hyperon_bridge.py --program  # show the MeTTa source
"""
import json
import sys

from core.metta_parallel import (assess, disagreements, gather_facts,
                                 metta_program, run, sidecar_python)


def main() -> int:
    if "--program" in sys.argv:
        print(metta_program(gather_facts()))
        return 0

    print(f"[BRIDGE] sidecar: {sidecar_python() or 'ABSENT — python-reference'}")
    result = run()
    if result.get("engines_agree") is False:
        print("[BRIDGE] WARNING: hyperon and the reference disagreed; the "
              "reference was used. See engine_error in the output file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

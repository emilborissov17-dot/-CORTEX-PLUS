#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The opentelemetry packages must be one family, not a family and a stranger.

WHAT HAPPENED (12 Sep 2026, the first error the black box ever recorded).
cortex_reasoner died with

    ModuleNotFoundError: No module named
    'opentelemetry.exporter.otlp.proto.common._exporter_metrics'

Nothing in this repo imports opentelemetry. chromadb does, and a fresh install had
pulled opentelemetry-exporter-otlp-proto-grpc 1.42.1 alongside a 1.37.0 family:

    opentelemetry-api                        1.37.0
    opentelemetry-exporter-otlp-proto-common 1.37.0
    opentelemetry-exporter-otlp-proto-grpc   1.42.1   <- alone
    opentelemetry-sdk                        1.37.0

1.42.1 imports a private module that 1.37.0's common package does not ship. The
grpc exporter was the only package out of step, and one import away from the
cycle's reasoning step.

WHY A TEST AND NOT ONLY A PIN. requirements.txt now pins the grpc exporter, and a
pin is a request: `pip install` some other day, or a transitive resolve from a
package that wants a newer chromadb, can lift it again. The pin states the
intention; this states the condition, and fails the moment it stops holding —
before a night does.

WHY THE MAJOR.MINOR AND NOT THE PATCH. The break was 1.37 against 1.42, a minor
jump across which private module layout moved. Patch releases inside one minor
have not done that, and demanding exact equality would go red on a security patch
that is not a problem. The rule is the one the failure taught, no wider.

THE 0.58b0 PACKAGES ARE NOT IN THIS FAMILY and are deliberately excluded: the
instrumentation and semantic-convention packages carry their own 0.x line that
tracks the 1.x one at a different number. Folding them in would make the test
demand something upstream never promised.
"""
from __future__ import annotations

import re

import pytest

# The core runtime family: these move together upstream and are the ones whose
# private modules import each other.
FAMILY = (
    "opentelemetry-api",
    "opentelemetry-sdk",
    "opentelemetry-proto",
    "opentelemetry-exporter-otlp-proto-common",
    "opentelemetry-exporter-otlp-proto-grpc",
    "opentelemetry-exporter-otlp-proto-http",
)


def _installed() -> dict:
    from importlib.metadata import PackageNotFoundError, version
    out = {}
    for name in FAMILY:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            continue
    return out


def _minor(v: str) -> str:
    m = re.match(r"^(\d+)\.(\d+)", v)
    return f"{m.group(1)}.{m.group(2)}" if m else v


def test_the_family_shares_one_major_minor():
    got = _installed()
    if len(got) < 2:
        pytest.skip("fewer than two of the family are installed here")
    lines = sorted(got.items())
    minors = {_minor(v) for v in got.values()}
    assert len(minors) == 1, (
        "the opentelemetry family has drifted apart:\n  "
        + "\n  ".join(f"{k:<42} {v}" for k, v in lines)
        + "\n\nOn 12 Sep 2026 exactly this — the grpc exporter at 1.42.1 beside a "
          "1.37.0 family — killed cortex_reasoner with ModuleNotFoundError on "
          "opentelemetry.exporter.otlp.proto.common._exporter_metrics. Pin the odd "
          "one back to the family's version rather than lifting the rest.")


def test_the_import_that_actually_broke_still_works():
    """The direct reproduction, so the guard cannot pass on version arithmetic
    alone while the import it exists to protect is still broken."""
    pytest.importorskip("opentelemetry.exporter.otlp.proto.grpc",
                        reason="the grpc exporter is not installed here")
    import opentelemetry.exporter.otlp.proto.grpc.trace_exporter  # noqa: F401


def test_chromadb_the_only_thing_that_wants_it_still_imports():
    """No module in this repo imports opentelemetry; chromadb does, and chromadb
    is what the reasoning step reaches through. If this fails, the family is out
    of step again whatever the numbers say."""
    pytest.importorskip("chromadb", reason="chromadb is not installed here")
    import chromadb  # noqa: F401

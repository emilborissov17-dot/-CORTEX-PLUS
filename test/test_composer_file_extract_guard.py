"""A file address that does not resolve is a NAMED failure, not a TypeError.

THE DEFECT. composer.fetch's `file` branch did:

    v = _dotted(data, src["extract"])
    return (float(v), ...)

_dotted returns None when the dotted path is absent from the payload — the key
was renamed, the section is missing, the file is a stub — and float(None) then
raised:

    TypeError: float() argument must be a string or a real number, not 'NoneType'

That message names neither the file, nor the path, nor the source. A reader
learns only that arithmetic happened somewhere. It is exactly the class the CSV
and json_rows readers already close by raising RowNotFound with the address:
"an address was declared and the payload does not hold it".

PROVENANCE, stated because this file sits among six others where it differs. The
uncommitted version of composer.py carried a guard here and a `git reset --hard`
destroyed it. Unlike its six siblings, composer.py left NO pre-reset .pyc — it is
one of the two files recorded as permanently lost — so the original wording is
unrecoverable and NOTHING here is a reconstruction of it. This is written from
the defect itself, which stands on its own terms: float(None) is wrong whatever
the lost version said.

It surfaced as test_promotion_seam.py dying inside composer.py:276 rather than
reporting a bad source.
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "composers"))

from experiments.composers import composer as comp    # noqa: E402
import readers                                         # noqa: E402


@pytest.fixture
def payload(tmp_path, monkeypatch):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"world_bank": {"life_expectancy": 73.1}}),
                 encoding="utf-8")
    monkeypatch.setattr(comp, "REPO", tmp_path)
    return "snap.json"


def test_a_resolvable_address_still_works(payload):
    """The negative control: the guard must not break the working path."""
    v, dd = comp.fetch({"kind": "file", "path": payload,
                        "extract": "world_bank.life_expectancy"})
    assert v == 73.1
    assert dd is None


def test_a_missing_address_raises_row_not_found_not_type_error(payload):
    with pytest.raises(readers.RowNotFound) as e:
        comp.fetch({"kind": "file", "path": payload,
                    "extract": "world_bank.does_not_exist", "id": "gi_probe"})
    msg = str(e.value)
    assert "does_not_exist" in msg, "the failure must name the ADDRESS"
    assert "snap.json" in msg, "and the file it was looked for in"
    assert "gi_probe" in msg, "and the source that declared it"


def test_it_is_not_a_type_error(payload):
    """The whole point: a bare TypeError says arithmetic broke, not which source
    is misconfigured."""
    with pytest.raises(Exception) as e:
        comp.fetch({"kind": "file", "path": payload, "extract": "nope"})
    assert not isinstance(e.value, TypeError), (
        "float(None) must never be reached — the address is checked first")


def test_a_missing_section_is_named_too(payload):
    with pytest.raises(readers.RowNotFound):
        comp.fetch({"kind": "file", "path": payload, "extract": "absent.section"})


def test_the_guard_runs_before_the_float(payload):
    """Order, by AST: the None check must precede the float() that used to blow."""
    import ast
    src = (REPO / "experiments" / "composers" / "composer.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "fetch")
    guard = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
             and isinstance(n.test.ops[0], ast.Is)
             and getattr(n.test.comparators[0], "value", "x") is None]
    assert guard, "no `if v is None:` guard in fetch()"
    floats = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "float"]
    assert min(guard) < max(floats), (
        "the guard must precede the float() it exists to protect")

"""Journaled templates are model-output-shaped, so they must be English.

core/language_gate.py reads memory/brain_journal.jsonl and scores every row as
though it were model output. A remember() call whose text is a hardcoded
Bulgarian f-string therefore lands in the purity window as "the model answered
in the wrong language" — and because a template fires every time its code path
does, it fails DETERMINISTICALLY. Measured on 27 Aug 2026, skip_decision was
0/5 clean, and 0/15 across the five days before it: a floor breach manufactured
entirely by our own logging.

This is checked with ast, not with a substring scan, because the thing under
test is which STRING LITERALS reach remember() as its summary argument. A grep
for Cyrillic in core/brain.py matches its docstrings and comments, which are
Bulgarian on purpose and never journaled.
"""
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
CYRILLIC = range(0x0400, 0x0500)

# Sites still emitting a Bulgarian journal template. This is a DEBT LEDGER, not
# an exemption: shrink it when you fix one, and the last line of this module
# fails loudly if it is stale in either direction.
KNOWN_REMAINING = {"core/reconsider.py"}


def _has_cyrillic(s: str) -> bool:
    return any(ord(c) in CYRILLIC for c in s)


def _literal_text(node) -> str:
    """Every string constant that is baked into this argument at author time.

    An f-string is a JoinedStr: its Constant parts are what the programmer
    wrote, its FormattedValue parts are runtime data and not ours to judge.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(node, ast.BinOp):
        return _literal_text(node.left) + _literal_text(node.right)
    return ""


def _remember_templates(path: pathlib.Path):
    """[(lineno, kind, literal_text)] for each remember(kind, summary, ...)."""
    # utf-8-sig: at least one module in core/ carries a BOM, and ast.parse
    # rejects U+FEFF as a non-printable character.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else None)
        if name != "remember" or len(node.args) < 2:
            continue
        kind = node.args[0].value if (isinstance(node.args[0], ast.Constant)
                                      and isinstance(node.args[0].value, str)) else "?"
        out.append((node.lineno, kind, _literal_text(node.args[1])))
    return out


def _offenders(path: pathlib.Path):
    return [(ln, kind) for ln, kind, text in _remember_templates(path)
            if _has_cyrillic(text)]


def test_brain_journals_in_english():
    """core/brain.py's skip_decision and skip_denied templates are English."""
    path = REPO / "core" / "brain.py"
    templates = _remember_templates(path)
    kinds = {kind for _, kind, _ in templates}
    assert {"skip_decision", "skip_denied"} <= kinds, (
        "the templates this test exists for are gone from core/brain.py; "
        f"found kinds: {sorted(kinds)}")
    assert _offenders(path) == [], (
        "core/brain.py journals a Bulgarian template; the language gate scores "
        f"it as model output and it can never be clean: {_offenders(path)}")


def test_the_english_templates_actually_pass_the_gate():
    """Not just Cyrillic-free — clean by the gate that does the judging."""
    import sys
    sys.path.insert(0, str(REPO))
    from core import brain
    from core import language_gate as gate

    verdicts = ["РАЗРЕШЕНО", "ЗАБРАНЕНО", "НЕИЗВЕСТНО"]
    whys = [
        "надолу по реда има стъпка, която чете неин продукт, а той липсва или е стар",
        "никой надолу не чака неин продукт",
        "за тази стъпка няма изведени нито входове, нито изходи — "
        "незнанието не е разрешение",
        "MeTTa не се зарежда (ModuleNotFoundError) — без граф няма разрешение",
    ]
    for verdict in verdicts:
        for why in whys:
            line = ("some_step: the brain wants to skip; the graph says "
                    f"{brain._verdict_en(verdict)} — {brain._why_en(why)}")
            ok, reason = gate.is_english_enough(line)
            assert ok, f"{verdict}/{why[:30]} -> {reason}: {line}"


def test_an_unmapped_graph_token_passes_through_verbatim():
    """A fifth reason must reach the journal as itself, so the gate flags it.

    Substituting English for a token we do not recognise would hide the drift
    behind a translation that was never made.
    """
    import sys
    sys.path.insert(0, str(REPO))
    from core import brain
    assert brain._verdict_en("НЕЩО_НОВО") == "НЕЩО_НОВО"
    assert brain._why_en("нова причина") == "нова причина"
    assert brain._verdict_en(None) == ""
    assert brain._why_en(None) == ""


def test_the_remaining_bulgarian_journal_sites_are_exactly_the_known_ones():
    """The debt ledger is accurate — in both directions."""
    found = set()
    for path in sorted((REPO / "core").rglob("*.py")):
        if _offenders(path):
            found.add(path.relative_to(REPO).as_posix())
    assert found == KNOWN_REMAINING, (
        "the Bulgarian-journal-template ledger is stale. "
        f"found={sorted(found)} known={sorted(KNOWN_REMAINING)} — "
        "if you fixed one, remove it from KNOWN_REMAINING; if you added one, "
        "it will fail the language purity floor every time it fires.")

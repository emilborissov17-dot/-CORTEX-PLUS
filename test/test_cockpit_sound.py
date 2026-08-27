"""The stream can be heard, when asked — and not one moment before.

A sound toggle is the easiest control in a cockpit to get wrong, because the
failure is not that it does not work: it is that it works when nobody asked.
So the tests here are mostly about silence.

The strongest guarantee is structural rather than behavioural: the AudioContext
is not constructed at load and then left unused, it is not constructed AT ALL
until the click handler runs. A page nobody has clicked has no audio object to
start.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

sys.path.insert(0, str(REPO / "test"))
import cockpit_surface as surf   # noqa: E402

PAGE = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):]


def _strip_comments(js: str) -> str:
    """JS with block and line comments removed.

    Every text assertion below runs against this. Twice now a test of the form
    "this word must not appear" has failed on the COMMENT EXPLAINING why the
    word must not appear, which tests the prose and not the program.
    """
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", js)


CODE = _strip_comments(SCRIPT)


def _fn(name: str) -> str:
    """The source of one top-level function, by counting its braces.

    Slicing to the next `function` keyword swept up the comment block sitting
    between two functions, which is how the docs for one ended up inside the
    body of the next.
    """
    i = CODE.index("function %s(" % name)
    j = CODE.index("{", i)
    depth = 0
    for k in range(j, len(CODE)):
        if CODE[k] == "{":
            depth += 1
        elif CODE[k] == "}":
            depth -= 1
            if depth == 0:
                return CODE[i:k + 1]
    return CODE[i:]


# -- off, and off by construction ----------------------------------------

def test_sound_is_off_by_default():
    assert re.search(r"let\s+soundOn\s*=\s*false", CODE), (
        "soundOn does not start false")


def test_there_is_no_audio_object_until_someone_clicks():
    """Not 'created and unused' — not created.

    A suspended AudioContext built at load is still a page that decided to make
    an audio object without being asked. This asserts the constructor appears
    only inside the toggle handler.
    """
    ctors = [m.start() for m in re.finditer(r"new\s*\(?\s*window\.AudioContext",
                                            CODE)]
    assert ctors, "no AudioContext is ever constructed; the toggle is inert"
    handler = _fn("soundToggle")
    start = CODE.index(handler)
    for c in ctors:
        assert start <= c < start + len(handler), (
            "an AudioContext is constructed outside the click handler, at "
            "offset %d — that is a page making audio nobody asked for" % c)


def test_the_context_starts_null():
    assert re.search(r"let\s+audioCtx\s*=\s*null", CODE)


def test_nothing_autoplays():
    for banned in (".play()", "autoplay", "<audio", "new Audio("):
        assert banned not in CODE, (
            "the page can start audio on its own: %r" % banned)


def test_turning_it_off_actually_stops_it():
    h = _fn("soundToggle")
    assert "suspend()" in h, (
        "the toggle flips a flag without suspending the context")


def test_a_browser_without_web_audio_does_not_break_the_page():
    h = _fn("soundToggle")
    assert "catch" in h and re.search(r"soundOn\s*=\s*false", h), (
        "a missing AudioContext would throw out of the click handler and take "
        "the rest of the page's wiring with it")


# -- it sonifies what is already on the page ------------------------------

def test_sound_adds_no_server_surface():
    """No new route, and the sound path never fetches anything."""
    for name in ("soundToggle", "sonify", "blip"):
        body = _fn(name)
        for banned in ("get('/api", "fetch(", "XMLHttpRequest", "WebSocket"):
            assert banned not in body, (
                "%s talks to the server: %r" % (name, banned))


def test_no_api_route_was_added_for_sound():
    rules = {r for r, _m, _f in surf.routes()}
    assert not any("sound" in r or "audio" in r for r in rules), (
        "a server route was added for a client-side toggle: %s" % rules)


def test_it_is_fed_by_the_draw_that_already_happened():
    draw = _fn("drawStream")
    assert "sonify(" in draw, (
        "sound does not come from the lines the panel just drew, so the two "
        "can disagree about what the stream said")
    assert draw.index("el.innerHTML") < draw.index("sonify("), (
        "it sounds before it shows")


def test_a_backlog_is_not_replayed_as_a_burst():
    """A tab left on another page for an hour must not machine-gun on return."""
    s = _fn("sonify")
    assert "Math.min" in s, "the number of blips per draw is unbounded"
    assert "lastHeard" in s


def test_turning_it_on_does_not_replay_history():
    assert re.search(r"lastHeard\s*=\s*null", _fn("soundToggle")), (
        "switching on would sound every line already in the buffer")


def test_pitch_carries_the_channel_and_not_a_verdict():
    """This panel is the one place that shows the stream with no opinion in it.

    A tone that got shriller when something looked wrong would be a second
    opinion about the data, published as sound.
    """
    s = _fn("sonify")
    assert "channel" in s
    for verdict in ("severity", "degraded", "failed", "level", "alarm"):
        assert verdict not in s, (
            "the pitch encodes %r, which makes the sound a judgement" % verdict)


# -- it is a control like any other ---------------------------------------

def test_the_toggle_is_in_the_parsed_inventory():
    names = {name for _kind, name, _where in surf.controls()}
    assert "soundtoggle" in names, (
        "the sweep cannot see this control, so it will never be exercised")
    assert "snd" in names


def test_it_is_wired_where_every_other_control_is_wired():
    w = _fn("wirePanel")
    assert "#soundtoggle" in w, (
        "the handler is bound somewhere other than wirePanel, so a re-render "
        "leaves a button that looks alive and does nothing — which is exactly "
        "what COMMAND 30.1 was about")


def test_it_survives_a_re_render():
    """render() replaces #view wholesale; the state must not live in the DOM."""
    assert re.search(r"^let\s+soundOn", CODE, re.M), (
        "soundOn is not module-level state, so a re-render resets it")
    ctrl = _fn("streamControls")
    assert "soundOn?'on':''" in ctrl.replace(" ", ""), (
        "the button does not render its own state, so after a re-render the "
        "label and the flag can disagree")


def test_the_label_says_which_way_it_is():
    ctrl = _fn("streamControls")
    assert "SOUND ON" in ctrl and "SOUND OFF" in ctrl
    assert "aria-pressed" in ctrl


# -- the page still parses ------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_the_page_script_still_parses(tmp_path):
    """A cheap gate where the expensive one used to be.

    The renderer sweep catches a syntax error in this file, and the sweep now
    runs ONCE per command rather than before every commit. A broken page
    between those two moments would be invisible; this costs a tenth of a
    second and answers the same question.

    COMMAND 30 PART 0 was exactly this failure: one bad character and the whole
    cockpit rendered nothing.
    """
    js = tmp_path / "page.js"
    js.write_text(SCRIPT[len("<script>"):SCRIPT.rindex("</script>")],
                  encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True,
                       text=True)
    assert r.returncode == 0, "the cockpit's script does not parse:\n%s" % r.stderr

"""The acceptance sweep: every control, judged by a renderer.

A control "works" here only if Chrome agrees something VISIBLY changed —
computed style, a bounding box, an element count, the text on screen, the tab
that is active, or a request that actually left the page. Reading .hidden,
.checked or any other in-memory property is not evidence and this file never
does it. That rule exists because the dead CLOSE button shipped behind a test
asserting `wrap.hidden === true`: the property was true and the renderer painted
the panel 742 pixels wide anyway.

The checklist comes from test/cockpit_surface.py, which PARSES the page and the
server. A list typed by hand inherits the blind spots of whoever typed it, and
the control nobody remembered is exactly the one that breaks.

Runs against a cockpit server on a free high port and a headless Chrome with its
own throwaway profile. It never touches the operator's cockpit or Chrome
profile. Where no browser exists it SKIPS LOUDLY with the reason named — a sweep
that passes for lack of a renderer is worse than no sweep at all.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "test"))
sys.path.insert(0, str(REPO))

import cdp                      # noqa: E402
import cockpit_surface as cs    # noqa: E402

UNAVAILABLE = cdp.why_unavailable()
needs_renderer = pytest.mark.skipif(
    UNAVAILABLE is not None,
    reason=f"RENDER SWEEP SKIPPED — {UNAVAILABLE}")

pytestmark = [needs_renderer, pytest.mark.render_sweep]


# ── the world under test ────────────────────────────────────────────────────

class Sweep:
    """A live cockpit and a live browser, for the length of the session."""

    def __init__(self):
        self.port = cdp.free_port()
        # test/sweep_server.py redirects every WRITE surface into this
        # directory before Flask starts. The first version of the sweep drove
        # the operator's own repo and left four probe rows in the real
        # human_input_queue.db — a table with a DELETE trigger. Backing files up
        # was not enough: the run was killed before its teardown and the damage
        # survived, so the isolation is structural now.
        self.sandbox = pathlib.Path(tempfile.mkdtemp(prefix="cockpit_sandbox_"))
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO / "test" / "sweep_server.py"),
             str(self.port), str(self.sandbox)],
            cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.browser = cdp.Browser().__enter__()
        self._wait_for_server()

    def _wait_for_server(self, timeout: float = 30.0) -> None:
        import urllib.request
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url("/"), timeout=3).read()
                return
            except Exception:
                time.sleep(0.4)
        raise RuntimeError("the cockpit server never came up")

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def open(self, settle: float = 3.0):
        self.browser.goto(self.url("/"), settle=settle)
        return self.browser

    def close(self):
        try:
            self.browser.__exit__(None, None, None)
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
            shutil.rmtree(self.sandbox, ignore_errors=True)


@pytest.fixture(scope="module")
def sweep():
    s = Sweep()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="module")
def loaded(sweep):
    """The page, loaded once. Reloading per test cost 3s x 58 and the run hit
    the ten-minute cap without finishing."""
    b = sweep.open(settle=3.5)
    return b


@pytest.fixture
def page(sweep, loaded):
    """Reset to a known state WITHOUT a reload: overview, nothing open.

    Cheaper than a navigation and just as isolated for what is under test —
    every assertion below re-derives what it needs from the renderer.
    """
    # The mark-as-seen ledger is append-only BY DESIGN, so the first test to
    # press "24 unread" marks all 24 and every later test finds nothing to
    # press — which read as "this control does not render on this machine".
    # Clearing the SANDBOX's ledger (never the operator's) puts them back.
    (sweep.sandbox / "pending_expression.json").unlink(missing_ok=True)

    loaded.js("""
      try {
        openAxis = null; degOpen = false; unreadShown = []; legendOpen = false;
        bodyMissingOpen = false; openProposals.clear();
        if (typeof closeRun === 'function') closeRun();
      } catch (e) {}
      return true;
    """)
    loaded.js("return switchTo('overview'), true;")
    # The unread button DISABLES itself when the count reaches zero, so after
    # one test has pressed it every later test clicked a dead control and read
    # the result as "this does not render here". Clearing the sandbox ledger
    # above restores the count; this makes the button believe it.
    loaded.js("return refreshUnread(), true;")
    time.sleep(1.2)
    return loaded


# Some tabs are not slow because the page is slow. /api/somatic takes a real
# sensor reading, and the terminal mounts three xterms. Counting their controls
# after 2s reported five of them ABSENT on the first full run — all five render
# fine given time. A sweep that is too impatient invents defects.
# terminal raised from 4.0 after #closebtn was reported ABSENT on one pass of an
# otherwise green run. An intermittent skip is worse than a slow test: it reads
# as "this machine cannot exercise that control" when the truth is impatience.
SLOW_TABS = {"body": 6.0, "terminal": 6.0, "glass": 4.0, "expression": 3.5}


def go(b, tab: str, settle: float = 1.2):
    """Switch tab through the page's own control, then let it render."""
    b.js(f"return switchTo({tab!r}), true;")
    time.sleep(max(settle, SLOW_TABS.get(tab, 0.0)))


# ── 2.4  every tab renders, and can be left again ───────────────────────────

@pytest.mark.parametrize("tab", cs.tabs())
def test_every_tab_renders_and_can_be_left(page, tab):
    go(page, tab)
    view = page.visible("#view")
    assert view["visible"], f"the {tab} tab renders nothing visible"
    assert view["h"] > 40, f"the {tab} tab renders a {view['h']}px-tall view"
    body = page.text("#view").strip()
    assert body, f"the {tab} tab renders an empty view"

    go(page, "overview")
    assert page.js("return active;") == "overview", (
        f"the sweep could not leave the {tab} tab")


# ── 2.3  every panel renders data, or says in words why it has none ─────────

NO_DATA_WORDS = ("no data", "not wired", "never been written", "nothing",
                 "absent", "empty", "unavailable", "not available",
                 "no target", "too few", "waiting", "none")


@pytest.mark.parametrize("tab", [t for t in cs.tabs() if t != "terminal"])
def test_every_panel_shows_data_or_states_why_not(page, tab):
    go(page, tab, settle=2.0)
    panels = page.js("""
      return Array.from(document.querySelectorAll('#view .panel')).map(p => {
        const h = p.querySelector('h2');
        const body = p.cloneNode(true);
        const hh = body.querySelector('h2'); if (hh) hh.remove();
        const r = p.getBoundingClientRect();
        return {title: (h ? h.innerText : '(untitled)').trim(),
                text: (body.innerText || '').trim(),
                w: Math.round(r.width), h: Math.round(r.height),
                svg: p.querySelectorAll('svg').length,
                rows: p.querySelectorAll('tr,.sline,.tl,.unrow,.step').length};
      });
    """)
    assert panels, f"the {tab} tab renders no panels at all"

    blank = []
    for p in panels:
        has_data = p["rows"] > 0 or p["svg"] > 0 or len(p["text"]) > 24
        says_why = any(w in p["text"].lower() for w in NO_DATA_WORDS)
        if not (has_data or says_why):
            blank.append(f"{tab}/{p['title']!r} text={p['text'][:40]!r} "
                         f"rows={p['rows']}")
    assert not blank, (
        "these panels are blank and do not say why:\n  " + "\n  ".join(blank))


# ── 2.1 + 2.6  every control changes something, first render and after ──────

# EVERY control the parsed inventory finds, and how to reach it. `arrange` is
# whatever has to happen first for the control to exist — the unread list has to
# be opened before its rows are on screen, an axis before its close button.
#
# The first version of this table held eight of twenty-four, and the sweep was
# GREEN. Green because it was not looking. test_cockpit_sweep_coverage.py now
# refuses that: add a control to the page and it goes red naming it.
CONTROLS = {
    # tab bar and the tabs themselves
    "tab":      dict(tab="overview", sel=".tab",      what="the active tab changes"),
    "jump":     dict(tab="overview", sel=".jump",     what="goes to PENDING at an anchor"),
    "ask-run":  dict(tab="overview", sel=".ask-run",  what="the overlay becomes visible"),
    "cmd":      dict(tab="overview", sel=".cmd",      what="goes to TERMINAL with the command typed"),

    "degchip":  dict(tab="cycle",    sel=".degchip",  what="a panel names the degraded steps"),
    "prow":     dict(tab="pending",  sel=".prow",     what="the row expands"),
    "pf":       dict(tab="pending",  sel=".pf",       what="goes to TERMINAL"),
    "axis":     dict(tab="world",    sel=".axis",     what="an axis panel appears"),
    "axisclose": dict(tab="world",   sel="#axisclose", what="the axis panel closes",
                      arrange="const a=document.querySelector('.axis'); if(a) a.click();"),

    "bodymissing": dict(tab="body",  sel="#bodymissing", what="the missing-sensor list appears"),
    "sw":       dict(tab="body",     sel="[data-sw]", what="the toggle's own label flips",
                     mutates="config_expression.yaml", confirm=True),

    "tlcycle":  dict(tab="expression", sel="#tlcycle", what="the timeline reloads",
                     event="change"),
    "unread":   dict(tab="overview", sel="#unread",   what="the unread list is rendered",
                     mutates="memory/expression_pending.json"),
    "unrow":    dict(tab="overview", sel=".unrow",    what="scrolls to the line in the timeline",
                     arrange="const u=document.querySelector('#unread'); if(u) u.click();",
                     arrange_settle=5.0, settle=2.5,
                     mutates="memory/pending_expression.json"),
    "unreaddone": dict(tab="overview", sel="#unreaddone", what="the unread list is dismissed",
                       arrange="const u=document.querySelector('#unread'); if(u) u.click();",
                       arrange_settle=5.0, settle=2.5,
                       mutates="memory/pending_expression.json"),

    "spd":      dict(tab="glass",    sel=".spd",      what="the stream speed changes"),

    "asksend":  dict(tab="overview", sel="#asksend",  what="a receipt appears under the box",
                     arrange="document.querySelector('#askbox').value='sweep probe';",
                     mutates="memory/human_input_queue.db"),
    "askbox":   dict(tab="overview", sel="#askbox",   what="Enter sends and a receipt appears",
                     arrange="document.querySelector('#askbox').value='sweep probe two';",
                     event="enter", mutates="memory/human_input_queue.db"),
    "swmic":    dict(tab="overview", sel="#swmic",    what="the label flips MIC OFF/ON",
                     mutates="config_expression.yaml", confirm=True),
    "swcam":    dict(tab="overview", sel="#swcam",    what="the label flips CAM OFF/ON",
                     mutates="config_expression.yaml", confirm=True),

    "tabbtn":   dict(tab="terminal", sel=".tabbtn",   what="the shell pane changes",
                     pick=1),   # not [0]: that is the pane already showing
    "connect":  dict(tab="terminal", sel="#connect",  what="the session state word changes"),
    "closebtn": dict(tab="terminal", sel="#closebtn", what="the session state word changes"),
}

# The files a control can write. The server under test has them redirected into
# a sandbox (test/sweep_server.py), so this fixture is not the protection — it
# is the PROOF that the protection held. A restore-afterwards fixture is not
# enough on its own: the first run was killed by a timeout before teardown and
# the damage survived it.
MUTABLE = ("config_expression.yaml",
           "memory/pending_expression.json",
           "memory/human_input_queue.db",
           "memory/cockpit_forks_cache.json")


@pytest.fixture(scope="module", autouse=True)
def real_files_are_untouched():
    before = {rel: (REPO / rel).read_bytes() if (REPO / rel).exists() else None
              for rel in MUTABLE}
    yield
    changed = [rel for rel in MUTABLE
               if ((REPO / rel).read_bytes() if (REPO / rel).exists() else None)
               != before[rel]]
    assert not changed, (
        "the sweep wrote to the operator's own files: " + ", ".join(changed) +
        " — the sandbox in test/sweep_server.py is not covering every write "
        "surface")


def _snapshot(b) -> dict:
    """Everything about the page a RENDERER can report. No properties.

    WIDENED after the first full run. Two controls were reported dead that were
    working perfectly — .tabbtn switches which shell pane is displayed, and
    #connect rewrites the terminal's status line — because this snapshot looked
    at neither. A sweep that judges by observation is only as good as what it
    bothers to observe, and a false accusation costs exactly as much trust as a
    missed defect.
    """
    return {"text_len": len(b.text("#view")),
            "panels": b.count("#view .panel"),
            "active": b.js("return active;"),
            "overlay": b.visible("#runwrap")["visible"],
            "note": b.text("#asknote")[:60],
            "termstate": b.text("#tstate"),
            # NOT sliced. The first attempt cut this at 120 characters, which
            # landed one character before the only part of the sentence that
            # ever changes, and reported #connect dead on that basis.
            "termstatus": b.text("#termstatus"),
            # which shell pane the renderer is actually displaying
            "pane": b.js("""
                const p = Array.from(document.querySelectorAll('.pane'))
                  .find(x => getComputedStyle(x).display !== 'none');
                return p ? p.id : null;"""),
            "scrolled": b.js("return Math.round(window.scrollY);"),
            # An unread line scrolls the TIMELINE container, not the window, so
            # window.scrollY never moves and the control read as dead. What the
            # renderer does show is the landing highlight — a real background
            # and outline change on the line that was jumped to.
            "landed": b.js("return document.querySelectorAll('.landed').length;"),
            "orphan": b.js("return document.querySelectorAll('.unrow.orphan').length;"),
            "stream_scroll": b.js("""
                const s = document.querySelector('.stream');
                return s ? Math.round(s.scrollTop) : null;""")}


@pytest.mark.parametrize("name", sorted(CONTROLS))
@pytest.mark.parametrize("pass_no", [1, 2], ids=["first-render", "after-re-render"])
def test_a_control_changes_something_the_renderer_can_see(page, name, pass_no):
    """2.1 and 2.6 together: the same assertion, before and after a re-render."""
    spec = CONTROLS[name]
    tab, selector, what = spec["tab"], spec["sel"], spec["what"]
    go(page, tab, settle=2.0)          # go() raises this for the slow tabs

    if pass_no == 2:
        page.js("return render(), true;")
        time.sleep(max(1.5, SLOW_TABS.get(tab, 0.0)))

    if spec.get("confirm"):
        # the page asks before switching a device on; a headless browser would
        # otherwise block on the dialog. Answering it is not stubbing what is
        # under test — the VISIBLE result of the answer still has to show up.
        page.js("return window.confirm = () => true, true;")

    if spec.get("arrange"):
        page.js(spec["arrange"] + " return true;")
        # arrange_settle, not settle: reaching a control can take longer than
        # operating it. The unread flow makes two round-trips and switches tab.
        time.sleep(spec.get("arrange_settle", spec.get("settle", 1.2)))

    n = page.count(selector)
    if n == 0:
        pytest.skip(
            f"NOT EXERCISED: no {selector} rendered on the {tab} tab with this "
            f"machine's data — {what}")

    before = _snapshot(page)
    mark = page.request_mark()

    ev = spec.get("event")
    if ev == "change":
        acted = page.js(f"""
          const el = document.querySelector({selector!r});
          if (!el || !el.options || el.options.length < 1) return false;
          el.selectedIndex = Math.min(1, el.options.length - 1);
          el.dispatchEvent(new Event('change', {{bubbles:true}}));
          return true;
        """)
        time.sleep(1.5)
    elif ev == "enter":
        acted = page.js(f"""
          const el = document.querySelector({selector!r});
          if (!el) return false;
          el.dispatchEvent(new KeyboardEvent('keydown',
            {{key:'Enter', bubbles:true}}));
          return true;
        """)
        time.sleep(1.5)
    else:
        pick = spec.get("pick")
        if pick is not None:
            # Clicking the FIRST match is not always operating the control. The
            # first .tabbtn is the shell tab that is already open, so clicking
            # it correctly does nothing — and the sweep read that as a dead
            # button. Where order matters, the control says which one to press.
            acted = page.js(f"""
              const els = document.querySelectorAll({selector!r});
              const el = els[{pick}] || els[els.length - 1];
              if (!el) return false;
              el.scrollIntoView({{block:'center'}});
              el.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
              return true;
            """)
            import time as _t
            _t.sleep(spec.get("settle", 1.3))
        else:
            acted = page.click(selector, settle=spec.get("settle", 1.3))

    assert acted, f"{selector} could not be operated"
    after = _snapshot(page)
    reqs = page.requests_since(mark)

    assert (after != before) or reqs, (
        f"{name} on the {tab} tab: operating it changed NOTHING the renderer "
        f"can see and issued no request. Expected: {what}.\n"
        f"  before={before}\n  after ={after}")


# ── 2.2  anything that opens must close, by its control AND by Escape ───────

def test_the_overlay_opens_and_closes_by_its_own_control(page):
    assert not page.visible("#runwrap")["visible"], "the overlay starts open"

    page.click(".ask-run", settle=2.5)
    opened = page.visible("#runwrap")
    assert opened["visible"], (
        f"the overlay did not become visible: {opened}")
    assert opened["w"] > 200 and opened["h"] > 100, (
        f"the overlay is visible but has no area: {opened}")

    page.click("#runclose", settle=1.0)
    closed = page.visible("#runwrap")
    assert not closed["visible"], (
        f"CLOSE did not hide the overlay — THE ORIGINAL BUG: {closed}")
    assert closed["w"] == 0 and closed["h"] == 0, (
        f"the overlay still occupies {closed['w']}x{closed['h']} pixels")


def test_the_overlay_also_closes_on_escape(page):
    page.click(".ask-run", settle=2.5)
    assert page.visible("#runwrap")["visible"]
    page.key("Escape", settle=1.0)
    assert not page.visible("#runwrap")["visible"], (
        "Escape did not close the overlay")


def test_closing_returns_focus_to_the_control_that_opened_it(page):
    page.click(".ask-run", settle=2.5)
    page.click("#runclose", settle=1.0)
    focused = page.js("""
      const a = document.activeElement;
      return a ? (a.className || a.tagName) : null;
    """)
    assert focused and "ask-run" in str(focused), (
        f"focus went to {focused!r} instead of back to the button that opened "
        f"the overlay")


# ── 2.7  the tick may not resurrect a closed overlay, nor swap an open one ──

def test_a_tick_does_not_resurrect_a_closed_overlay(page):
    page.click(".ask-run", settle=2.5)
    page.click("#runclose", settle=1.0)
    assert not page.visible("#runwrap")["visible"]

    page.js("return tick(), true;")
    time.sleep(2.0)
    page.js("return render(), true;")
    time.sleep(1.5)

    assert not page.visible("#runwrap")["visible"], (
        "the 15-second refresh reopened an overlay the reader had closed")


def test_a_tick_does_not_swap_an_open_overlay(page):
    page.click(".ask-run", settle=2.5)
    body_before = page.text("#runout")
    assert body_before.strip(), "the overlay opened with no output in it"

    page.js("return tick(), true;")
    time.sleep(2.0)
    page.js("return render(), true;")
    time.sleep(1.5)

    assert page.visible("#runwrap")["visible"], "the tick closed the overlay"
    assert page.text("#runout") == body_before, (
        "the refresh swapped the overlay's contents underneath the reader")
    assert "refresh" in page.text("#runstale").lower(), (
        "the overlay does not say its snapshot has aged")


# ── 2.5  every route answers, and a failure is VISIBLE ──────────────────────

GET_ROUTES = [r for r, m, _ in cs.routes()
              if r.startswith("/api/") and "GET" in m and "<" not in r]


@pytest.mark.parametrize("route", GET_ROUTES)
def test_every_api_route_answers_on_the_happy_path(sweep, route):
    import urllib.request
    with urllib.request.urlopen(sweep.url(route), timeout=30) as r:
        assert 200 <= r.status < 300, f"{route} -> {r.status}"


def test_a_failing_endpoint_leaves_a_visible_error_not_a_silent_blank(page):
    """An endpoint failing must never leave the reader looking at nothing."""
    go(page, "overview", settle=1.5)
    page.fail_route("/api/cycles", status=500)
    page.js("return render(), true;")
    page.pump_intercepts(seconds=3.0)
    time.sleep(1.5)

    text = page.text("#view").strip()
    view = page.visible("#view")
    page.stop_failing()

    assert view["visible"] and view["h"] > 40, (
        "a 500 left the view with no height at all")
    assert text, "a 500 left the view completely blank"
    assert len(text) > 10, f"a 500 left only {text!r} on screen"


# ── 2.8  negative controls ──────────────────────────────────────────────────

def test_negative_control_an_unbound_control_is_caught(page):
    """A button with no handler must fail the 2.1 assertion."""
    go(page, "overview", settle=1.5)
    page.js("""
      const b = document.createElement('button');
      b.className = 'sweep-deadctl';
      b.textContent = 'dead';
      document.querySelector('#view').appendChild(b);
      return true;
    """)
    before = _snapshot(page)
    mark = page.request_mark()
    page.click(".sweep-deadctl", settle=0.8)
    after = _snapshot(page)
    reqs = page.requests_since(mark)
    assert after == before and not reqs, (
        "a control with NO handler appeared to change something — the sweep's "
        "own change-detector is too loose to be trusted")


def test_negative_control_a_property_flip_with_no_visible_change_is_caught(page):
    """THE CLOSE BUG, REPRODUCED DELIBERATELY.

    An element whose display is pinned by an ID rule: set .hidden and the
    property is true while the renderer keeps painting it. If the sweep's
    visibility judgement accepted that, it would be repeating the mistake that
    caused all of this.
    """
    page.js("""
      const s = document.createElement('style');
      s.textContent = '#sweeptrap{display:flex;width:200px;height:60px}';
      document.head.appendChild(s);
      const d = document.createElement('div');
      d.id = 'sweeptrap'; d.textContent = 'trap';
      document.body.appendChild(d);
      d.hidden = true;                 // the property the old test believed
      return true;
    """)
    time.sleep(0.4)
    prop = page.js("return document.getElementById('sweeptrap').hidden;")
    seen = page.visible("#sweeptrap")

    assert prop is True, "the trap did not set the property"
    assert seen["visible"] is True, (
        "the trap element was actually hidden, so this negative control proves "
        "nothing — check the injected stylesheet")
    assert seen["w"] > 0, "the trap has no area; it cannot demonstrate the bug"
    # and the point: the sweep's own judgement disagrees with the property
    assert seen["visible"] != (not prop), (
        "the sweep would have accepted a property flip as evidence of hiding")


def test_negative_control_a_blank_panel_is_caught(page):
    """The 2.3 rule must reject a panel with nothing in it and no reason."""
    go(page, "overview", settle=1.5)
    page.js("""
      const sec = document.createElement('section');
      sec.className = 'panel';
      sec.innerHTML = '<h2>EMPTY</h2>';
      document.querySelector('#view').appendChild(sec);
      return true;
    """)
    panels = page.js("""
      return Array.from(document.querySelectorAll('#view .panel')).map(p => {
        const b = p.cloneNode(true);
        const h = b.querySelector('h2'); if (h) h.remove();
        return {title: (p.querySelector('h2')||{}).innerText || '',
                text: (b.innerText||'').trim(),
                rows: p.querySelectorAll('tr,.sline,.tl,.unrow,.step').length,
                svg: p.querySelectorAll('svg').length};
      });
    """)
    empty = [p for p in panels
             if p["rows"] == 0 and p["svg"] == 0 and len(p["text"]) <= 24
             and not any(w in p["text"].lower() for w in NO_DATA_WORDS)]
    assert empty, (
        "an injected panel containing nothing but a heading was NOT caught by "
        "the blank-panel rule, so that rule cannot fail")
    assert any(p["title"] == "EMPTY" for p in empty)

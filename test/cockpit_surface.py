"""The cockpit's surface, DERIVED from the page and the server — never listed.

An inventory typed by hand inherits the blind spots of whoever typed it, and the
whole point of the sweep is to catch the control nobody remembered. So the
checklist is parsed: tabs from the TABS literal, panels from the panel() calls,
controls from the markup a renderer will actually receive, routes from the Flask
decorators.

Import this from a test; it holds no assertions of its own.

    venv/Scripts/python.exe test/cockpit_surface.py     # print the inventory
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "cockpit" / "templates" / "cockpit.html"
SERVER = REPO / "cockpit" / "server.py"

PAGE = TEMPLATE.read_text(encoding="utf-8")
CSS = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
STATIC = PAGE[:PAGE.index("<script>")]
SCRIPT = PAGE[PAGE.index("<script>"):]


def tabs() -> list:
    """Every tab, from the TABS array literal."""
    block = SCRIPT[SCRIPT.index("const TABS = ["):]
    block = block[:block.index("];") + 1]
    return re.findall(r"\{id:'([\w-]+)'", block.replace('"', "'"))


def renderers() -> dict:
    """tab id -> the function that builds it, from the RENDER map."""
    block = SCRIPT[SCRIPT.index("const RENDER = {"):]
    block = block[:block.index("};") + 1]
    return dict(re.findall(r"(\w+)\s*:\s*(\w+)", block))


def panels() -> list:
    """[(renderer, title-expression)] — one entry per panel() call."""
    out = []
    for m in re.finditer(r"panel\(\s*('([^']*)'|`([^`]*)`|[^,]+?)\s*,", SCRIPT):
        title = (m.group(2) or m.group(3) or m.group(1)).strip()
        fn = _enclosing_function(m.start())
        out.append((fn, title[:60]))
    return out


def _enclosing_function(idx: int) -> str:
    head = SCRIPT[:idx]
    hits = re.findall(r"(?:async\s+)?function\s+(\w+)\s*\(", head)
    return hits[-1] if hits else "?"


def endpoints_used() -> dict:
    """renderer -> the /api routes it fetches, from get()/fetch() call sites."""
    out = {}
    for m in re.finditer(r"(?:get|fetch)\(\s*'(/api/[\w/]+)", SCRIPT):
        out.setdefault(_enclosing_function(m.start()), set()).add(m.group(1))
    for m in re.finditer(r"(?:get|fetch)\(\s*'(/api/[\w/]+)'\s*\+", SCRIPT):
        out.setdefault(_enclosing_function(m.start()), set()).add(m.group(1) + "<param>")
    return {k: sorted(v) for k, v in out.items()}


def routes() -> list:
    """Every Flask route, from the decorators. (rule, methods, function)."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8-sig"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            attr = getattr(f, "attr", None)
            if attr not in ("get", "post", "route"):
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue
            rule = dec.args[0].value
            methods = [attr.upper()]
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [e.value for e in kw.value.elts
                               if isinstance(e, ast.Constant)]
            out.append((rule, tuple(methods), node.name))
    return sorted(set(out))


# A control is something a human can press. Classes carry the handler in this
# page; ids carry it for the singletons.
CONTROL_CLASSES = ("tab", "tabbtn", "jump", "degchip", "prow", "unrow", "axis",
                   "pf", "cmd", "ask-run", "spd", "snd", "fbtn", "sw", "rg")
CONTROL_IDS = ("asksend", "askbox", "unread", "swmic", "swcam", "runclose",
               "connect", "closebtn", "tlcycle", "axisclose", "bodymissing",
               "unreaddone", "soundtoggle", "regionclose")


def controls() -> list:
    """[(kind, name, where)] — every pressable thing, and whether it is static."""
    out = []
    for cls in CONTROL_CLASSES:
        in_static = re.search(r'class="[^"]*\b' + cls + r'\b', STATIC) is not None
        in_script = re.search(r'class="[^"]*\b' + cls + r'\b', SCRIPT) is not None
        if in_static or in_script:
            out.append(("class", cls, "static" if in_static else "injected"))
    for i in CONTROL_IDS:
        in_static = f'id="{i}"' in STATIC
        in_script = f'id="{i}"' in SCRIPT
        if in_static or in_script:
            out.append(("id", i, "static" if in_static else "injected"))
    return out


# ── the specificity family (0.3) ────────────────────────────────────────────

VISUAL = ("display", "visibility", "opacity")


def specificity(sel: str) -> tuple:
    """(ids, classes+attrs+pseudo-classes, elements) — the CSS cascade order."""
    s = re.sub(r"::[a-z-]+", "", sel)
    ids = len(re.findall(r"#[\w-]+", s))
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:[a-z][\w-]*(?:\([^)]*\))?", s))
    els = len(re.findall(r"(?:^|[\s>+~])([a-z][\w-]*)", s))
    return (ids, cls, els)


def css_rules() -> list:
    """[(selector, {prop: value}, specificity)] for every visual declaration."""
    out = []
    body = CSS[CSS.index(">") + 1:]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", body):
        sels, decls = m.group(1), m.group(2)
        props = {}
        for d in decls.split(";"):
            if ":" not in d:
                continue
            k, v = d.split(":", 1)
            if k.strip() in VISUAL:
                props[k.strip()] = v.strip()
        if not props:
            continue
        for sel in sels.split(","):
            sel = sel.strip()
            if sel and not sel.startswith("@"):
                out.append((sel, props, specificity(sel)))
    return out


HIDING = {"display": "none", "visibility": "hidden", "opacity": "0"}


def _tokens(sel: str) -> frozenset:
    """The simple selectors in one compound selector, order-independent."""
    return frozenset(re.findall(r"#[\w-]+|\.[\w-]+|\[[^\]]+\]|:[a-z][\w-]*", sel))


def hides(props: dict) -> bool:
    return any(props.get(k) == v for k, v in HIDING.items())


def shows(props: dict) -> bool:
    return any(k in props and props[k] != HIDING[k] for k in HIDING)


def hidden_elements() -> dict:
    """What the page ACTUALLY hides, and by what mechanism.

    This is the whole precision of the check. Comparing the UA [hidden] rule
    against every element that merely HAS a display rule flags forty things that
    are never hidden — .tl .src, .bar>i, .spd.on — and a check that cries wolf
    forty times is a check somebody deletes. Only an element the page really
    hides can suffer the CLOSE bug.

    Returns {selector: [mechanism, ...]}.
    """
    out = {}

    # 1. the hidden ATTRIBUTE, set on an id directly or through a local
    for i in set(re.findall(r"\$\('#([\w-]+)'\)\.hidden\s*=", SCRIPT)):
        out.setdefault("#" + i, []).append("[hidden]")
    for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*\$\('#([\w-]+)'\)", SCRIPT):
        if re.search(r"\b" + m.group(1) + r"\.hidden\s*=", SCRIPT):
            out.setdefault("#" + m.group(2), []).append("[hidden]")

    # 2. a CLASS the page toggles, which some rule hides
    hiding_classes = {s.strip(".") for s, p, _ in css_rules()
                      if hides(p) and re.fullmatch(r"\.[\w-]+", s.strip())}
    toggled = set(re.findall(r"classList\.(?:add|remove|toggle)\(\s*'([\w-]+)'", SCRIPT))
    toggled |= set(re.findall(r"\?\s*'([\w-]+)'\s*:\s*'[\w-]*'", SCRIPT))
    toggled |= set(re.findall(r"\?\s*'[\w-]*'\s*:\s*'([\w-]+)'", SCRIPT))
    for c in sorted(hiding_classes & toggled):
        out.setdefault("." + c, []).append("." + c)

    # 3. an INLINE style.display — always wins, nothing can outrank it
    if re.search(r"\.style\.display\s*=", SCRIPT):
        out.setdefault("(inline style.display)", []).append("inline")

    # one entry per MECHANISM, not per call site: hiding the same element from
    # two functions is one fact about the page, not two
    return {k: sorted(set(v)) for k, v in out.items()}


def specificity_family() -> list:
    """For every element the page hides: does anything out-specify the hiding?

    THE CLOSE BUG'S FAMILY. #runwrap{display:flex} at (1,0,0) beat the UA rule
    [hidden]{display:none} at (0,1,0), so setting .hidden flipped a property and
    changed nothing on screen. A pair is FLAGGED when the showing rule outranks
    the rule that is supposed to hide the element — the defect, exactly.

    The user-agent rule is scored explicitly at (0,1,0) because it is the hider
    the page leans on and it is not in this stylesheet, which is precisely why
    nothing noticed it losing.
    """
    rules = css_rules()
    fam = []
    for base, mechanisms in sorted(hidden_elements().items()):
        if base.startswith("("):
            fam.append({
                "element": base, "hiding_rule": "inline style",
                "hiding_spec": "inline", "showing_rule": "-",
                "showing_prop": "-", "showing_spec": "-",
                "author_wins": False,
                "note": "an inline style beats every stylesheet rule by "
                        "construction; nothing can out-specify it",
            })
            continue

        # A rule shows this element if its own last compound CONTAINS the
        # hidden element's selector: .ghost is hidden, and .ghost.lit shows it.
        # Matching on equality missed exactly that shape, which is the opacity
        # form of the same defect.
        showers = [(s, p, sp) for s, p, sp in rules
                   if _tokens(base) <= _tokens(s.split()[-1]) and shows(p)]
        if not showers:
            continue

        for mech in mechanisms:
            hsel = base + mech if mech.startswith("[") else mech
            explicit = [sp for s, p, sp in rules if s == hsel and hides(p)]
            if explicit:
                hspec, shown = max(explicit), hsel
            elif mech == "[hidden]":
                hspec, shown = specificity("[hidden]"), "[hidden] (user agent)"
            else:
                hspec, shown = specificity(mech), mech
            for ssel, sprops, sspec in showers:
                prop = next(k for k in HIDING
                            if k in sprops and sprops[k] != HIDING[k])
                fam.append({
                    "element": base,
                    "hiding_rule": shown,
                    "hiding_spec": hspec,
                    "showing_rule": ssel,
                    "showing_prop": "{}: {}".format(prop, sprops[prop]),
                    "showing_spec": sspec,
                    "author_wins": sspec > hspec,
                    "note": "",
                })
    return fam


def _main() -> None:
    t, r, p = tabs(), renderers(), panels()
    print(f"TABS ({len(t)}): {', '.join(t)}")
    print(f"RENDERERS ({len(r)}): " + ", ".join(f"{k}->{v}" for k, v in r.items()))
    print()
    print(f"PANELS ({len(p)}):")
    for fn, title in p:
        print(f"   {fn:16s} {title}")
    print()
    eu = endpoints_used()
    print(f"ENDPOINTS THE PAGE FETCHES ({sum(len(v) for v in eu.values())}):")
    for fn, urls in sorted(eu.items()):
        print(f"   {fn:16s} {', '.join(urls)}")
    print()
    rt = routes()
    print(f"SERVER ROUTES ({len(rt)}):")
    for rule, methods, fn in rt:
        print(f"   {'/'.join(methods):6s} {rule:34s} {fn}")
    print()
    c = controls()
    print(f"CONTROLS ({len(c)}):")
    for kind, name, where in c:
        print(f"   {kind:6s} {name:14s} {where}")
    print()
    fam = specificity_family()
    print(f"SPECIFICITY FAMILY ({len(fam)} pairs, "
          f"{sum(1 for f in fam if f['author_wins'])} flagged):")
    for f in fam:
        flag = "  <-- AUTHOR RULE WINS" if f["author_wins"] else ""
        print(f"   {f['element']:14s} hide {str(f['hiding_rule']):26s} "
              f"{f['hiding_spec']}  vs  show {f['showing_rule']:14s} "
              f"{f['showing_spec']} ({f['showing_prop']}){flag}")


if __name__ == "__main__":
    _main()

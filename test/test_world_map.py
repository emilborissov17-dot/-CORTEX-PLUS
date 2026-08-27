"""A map you can ask, not a picture you can look at.

The WORLD tab showed seven region codes and a zone word in a two-column table.
Every one of those rows is the top of a real pile — 217 countries, each with
its own zone and its own three scores — and none of it was reachable from the
page that named the region.

The one property worth more than the rest: NOTHING IS FETCHED TO DRAW IT. The
cockpit binds to 127.0.0.1 and a test asserts it. A map that phoned a tile
server would make this page the only thing in the repo that talks to the
internet, and it would do it from the operator's browser rather than from the
cycle, where every other outbound request is accounted for.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))

import cockpit_surface as surf                     # noqa: E402
from cockpit.server import app                     # noqa: E402

PAGE = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>"):]
CODE = re.sub(r"/\*.*?\*/", " ", SCRIPT, flags=re.S)

REGIONS = ("NAC", "LCN", "ECS", "MEA", "SSF", "SAS", "EAS")


def client():
    return app.test_client()


# -- offline, and provably so ---------------------------------------------

def test_the_map_fetches_nothing_from_the_internet():
    """No tile service, no CDN, no external SVG."""
    i = CODE.index("function worldMap(")
    j = CODE.index("async function regionPanel", i)
    body = CODE[i:j]
    for banned in ("http://", "https://", "//tile", "cdn", "openstreetmap",
                   "mapbox", "leaflet", "d3", "<img", "url("):
        assert banned not in body.lower(), (
            "the map reaches outside this machine: %r" % banned)


def test_the_outlines_live_in_this_file():
    """Hand-written points, not a fetched asset."""
    assert "const REGION_SHAPES" in CODE
    for r in REGIONS:
        assert re.search(r"\b%s:\s*\"" % r, CODE), (
            "%s has no outline, so its shape cannot be drawn" % r)


def test_the_page_still_has_no_external_reference_at_all():
    """The whole page, not only the map — the map is the thing most likely to
    have introduced one."""
    for banned in ("http://", "https://"):
        for m in re.finditer(re.escape(banned), PAGE):
            line = PAGE[:m.start()].count("\n") + 1
            ctx = PAGE.splitlines()[line - 1]
            assert ctx.strip().startswith(("*", "/*", "//")) or "w3.org" in ctx, (
                "line %d reaches outside this machine: %s" % (line, ctx.strip()))


def test_the_cockpit_still_binds_to_localhost_only():
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    assert 'HOST = "127.0.0.1"' in src
    # The bind, not the word. server.py explains "never 0.0.0.0" in a comment,
    # and a test that greps the raw file forbids documenting the rule it
    # enforces.
    code = re.sub(r"(?m)#.*$", "", src)
    assert "0.0.0.0" not in code, "something binds to every interface"


# -- seven regions, and they are the ones the data is bucketed by ---------

def test_the_shapes_are_the_regions_the_snapshot_actually_uses():
    """Not continents. Russia is in ECS and Egypt is in MEA because that is how
    the wellbeing snapshot aggregates, and re-bucketing here would mean the
    panel and the snapshot could disagree."""
    from core import continents as C
    live = {r["region_id"] for r in C.load()}
    drawn = set(re.findall(r"^\s*(\w{3}):\s*\"",
                           CODE[CODE.index("const REGION_SHAPES"):
                                CODE.index("const REGION_LABEL_AT")], re.M))
    assert drawn == live, (
        "the map draws %s and the snapshot has %s" % (sorted(drawn), sorted(live)))


def test_every_shape_is_labelled():
    block = CODE[CODE.index("const REGION_LABEL_AT"):]
    block = block[:block.index("}")]
    for r in REGIONS:
        assert r in block, "%s is drawn with no label on it" % r


def test_every_shape_has_at_least_a_dozen_points():
    """A rectangle is not an outline. These are rough and the legend says so,
    but a box would be a claim the shape carries no information at all."""
    block = CODE[CODE.index("const REGION_SHAPES"):CODE.index("const REGION_LABEL_AT")]
    for r in REGIONS:
        m = re.search(r"\b%s:\s*((?:\"[^\"]*\"\s*\+?\s*)+)" % r, block)
        assert m, r
        pts = re.findall(r"\d+,\d+", m.group(1))
        assert len(pts) >= 11, (
            "%s is drawn with %d points — that is a box, not an outline"
            % (r, len(pts)))


def test_the_legend_says_it_is_a_schematic():
    """Accuracy nobody computed must not be implied."""
    i = CODE.index("maplegend")
    block = CODE[i:i + 900]
    assert "schematic" in block and "not a survey" in block, (
        "the map presents hand-drawn outlines without saying so")
    assert "Nothing is fetched" in block


# -- clicking a region answers from the sealed snapshot -------------------

def test_a_region_returns_its_sealed_aggregate():
    d = client().get("/api/region/SAS").get_json()
    assert d["found"] is True
    a = d["aggregate"]
    assert a["region_id"] == "SAS"
    for k in ("dep", "str", "flo", "zone", "countries", "population"):
        assert k in a, "the aggregate is missing %r" % k
    assert d["computed_at"], "the panel cannot say when this was sealed"


def test_the_aggregate_is_the_snapshot_and_not_a_recomputation():
    """A panel that recomputed could disagree with what the rest of the system
    reasons about."""
    from core import continents as C
    live = {r["region_id"]: r for r in C.load()}["SAS"]
    assert client().get("/api/region/SAS").get_json()["aggregate"] == live


def test_it_clicks_through_to_country_rows():
    d = client().get("/api/region/SAS").get_json()
    assert d["country_count"] == d["aggregate"]["countries"], (
        "the region says it has %s countries and hands back %s rows"
        % (d["aggregate"]["countries"], d["country_count"]))
    names = [c["name"] for c in d["countries"]]
    assert "India" in names and "Nepal" in names


def test_the_worst_come_first():
    rows = client().get("/api/region/SSF").get_json()["countries"]
    deps = [c["deprivation"] or 0 for c in rows]
    assert deps == sorted(deps, reverse=True), (
        "58 countries in alphabetical order is a list nobody reads past the "
        "A's, and the question this panel answers is which are in trouble")


def test_every_country_row_carries_its_confidence():
    for c in client().get("/api/region/ECS").get_json()["countries"]:
        assert "confidence" in c and "completeness" in c, (
            "a score is shown without saying how much of it is real; 11 of 17 "
            "axes is not the same claim as 17 of 17")


def test_all_seven_regions_answer():
    for r in REGIONS:
        d = client().get("/api/region/%s" % r).get_json()
        assert d["found"] is True, "%s has a shape on the map and no data" % r
        assert d["country_count"] > 0


def test_the_regions_partition_the_countries():
    total = sum(client().get("/api/region/%s" % r).get_json()["country_count"]
                for r in REGIONS)
    blob = json.loads((REPO / "output" / "wellbeing_all_countries.json")
                      .read_text(encoding="utf-8"))
    assert total == blob["total"] == 217, (
        "the seven shapes reach %d of %d countries; some are unreachable from "
        "the map" % (total, blob["total"]))


def test_an_unknown_region_says_so_rather_than_erroring():
    d = client().get("/api/region/XXX").get_json()
    assert d["found"] is False
    assert "no region with id" in d["why_not"]
    assert d["countries"] == []


# -- history, stated rather than faked ------------------------------------

def test_no_sparkline_is_drawn_where_no_history_exists():
    """There is no per-country series anywhere in this repo. A flat line would
    be a trend nobody measured."""
    d = client().get("/api/region/SAS").get_json()
    assert d["history"] == {}
    assert "no per-country history exists" in d["history_why"]
    i = CODE.index("async function regionPanel")
    body = CODE[i:CODE.index("async function tabWorld", i)]
    assert "sparkline(" not in body, (
        "the region panel draws a sparkline from data that does not exist")
    assert "history_why" in body, "the panel does not say why there is no chart"


# -- the endpoint reads and never writes ----------------------------------

def test_the_endpoint_only_reads():
    src = (REPO / "cockpit" / "server.py").read_text(encoding="utf-8-sig")
    i = src.index("def api_region")
    body = src[i:src.index("@app.get", i + 10)]
    for banned in ("write_text", "open(", "dump(", "unlink", "mkdir"):
        assert banned not in body, "the region endpoint writes: %r" % banned


def test_the_route_is_registered_once():
    rules = [r for r, _m, _f in surf.routes() if r.startswith("/api/region")]
    assert rules == ["/api/region/<rid>"], rules


# -- it is a control like any other ---------------------------------------

def test_the_new_controls_are_in_the_parsed_inventory():
    names = {name for _kind, name, _where in surf.controls()}
    assert "rg" in names and "regionclose" in names


def test_the_map_is_wired_where_every_other_control_is_wired():
    i = CODE.index("function wirePanel(")
    body = CODE[i:i + 4000]
    assert "'.rg'" in body and "#regionclose" in body, (
        "the map's handlers are bound outside wirePanel, so a re-render leaves "
        "shapes that look alive and do nothing")


def test_escape_closes_the_region_panel():
    """Part 14: what opens must close by its own control AND by Escape."""
    assert re.search(r"Escape'\s*&&\s*openRegion", CODE), (
        "Escape does not close the region panel")
    i = CODE.index("function wirePanel(")
    assert "openRegion = null" in CODE[i:i + 4000], (
        "there is no close button handler")


def test_clicking_the_open_region_closes_it():
    i = CODE.index("'.rg'")
    body = CODE[i:i + 400]
    assert "openRegion === sh.dataset.region" in body, (
        "the control that opens is not the control that closes")


# -- the designed half is untouched ---------------------------------------

def test_the_designed_not_wired_half_is_exactly_as_it_was():
    i = PAGE.index("DESIGNED, NOT WIRED")
    block = PAGE[i:i + 1200]
    assert "nothing below is running" in block
    assert "memory/columns/" in block
    assert "class=\"cols dim\"" in block, "the greying was disturbed"
    assert "worldmap" not in block, "the map leaked into the designed half"


def test_the_map_is_in_the_live_half():
    """Where it is USED, not where the variable is declared.

    The first `mapSvg` in the file is its assignment near the top of tabWorld,
    which sits before both headings and made this check pass or fail for
    reasons that had nothing to do with the layout.
    """
    live = PAGE.index("LIVE — what flows tonight")
    designed = PAGE.index("DESIGNED, NOT WIRED")
    m = PAGE.index("mapSvg", live)
    assert live < m < designed, "the map is not rendered in the LIVE half"
    assert PAGE.index("regionHtml", live) < designed, (
        "the region panel opens outside the LIVE half")

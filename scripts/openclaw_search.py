# -*- coding: utf-8 -*-
"""scripts/openclaw_search.py — OpenClaw is the searcher (C-TURN-1 Part 4; Emil R32:
"We want ONLY OpenClaw to search").

Every search and every page read goes through OpenClaw's own browser (real
Chrome, profile per category, driven through the gateway with `openclaw browser`
— a direct tool call, no model turn). `requests` is not used here.

Per need: the query (for a brain need, the brain's own question) is typed into a
search page in OpenClaw's browser; the result links come back from the browser
tool; the top results are opened one by one and their text is taken FROM THE
BROWSER TOOL'S OWN RESULT (`evaluate` -> document.body.innerText), never from a
model's prose. Each page is stored (memory/openclaw_pages/<sha256>.json: url,
sha256 of that text, need id, the raw tool result) and ingested whole by
core.knowledge. A page named with no tool text behind it is UNBACKED and ingests
nothing. A page that shows a CAPTCHA is recorded with its host and skipped —
never solved, never worked around.

The agents' turn (scripts/turn_agents.py) calls serve() for every open brain
need, then every open engine need, then the maintenance cells.

    venv\\Scripts\\python.exe scripts\\openclaw_search.py --query "..."   # one search, printed
    venv\\Scripts\\python.exe scripts\\openclaw_search.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PAGES = REPO / "memory" / "openclaw_pages"
SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"
RESULTS_PER_NEED = 3
CAPTCHA = re.compile(r"captcha|are you a robot|unusual traffic|verify you are (a )?human|"
                     r"checking your browser|ddos-guard|attention required|anomaly-modal|bots use duckduckgo", re.I)
_LINKS_JS = ("() => JSON.stringify(Array.from(document.querySelectorAll('a.result__a'))"
             ".map(a => ({url: a.href, title: a.innerText})))")
_PDF_JS = ("async () => { const r = await fetch(location.href); const b = new Uint8Array(await r.arrayBuffer()); "
           "let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768)); "
           "return JSON.stringify({status: r.status, type: r.headers.get('content-type'), b64: btoa(s)}); }")
_TEXT_JS = ("() => JSON.stringify({title: document.title, url: location.href, "
            "text: document.body ? document.body.innerText : '', "
            "html: document.documentElement ? document.documentElement.outerHTML : ''})")
HTML_CAP = 5 * 1024 * 1024


class OpenClawFailed(RuntimeError):
    pass


def openclaw_cmd() -> list:
    """`node <npm root>/openclaw/openclaw.mjs` — called directly, NOT through the
    openclaw.cmd shim: cmd.exe would read the `>` of a JS arrow function as a
    redirect."""
    import shutil
    shim = shutil.which("openclaw")
    if shim:
        mjs = Path(shim).resolve().parent / "node_modules" / "openclaw" / "openclaw.mjs"
        node = shutil.which("node")
        if mjs.exists() and node:
            return [node, str(mjs)]
    raise OpenClawFailed("the openclaw CLI (node + openclaw.mjs) was not found")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class OpenClawBrowser:
    """The live driver: `openclaw browser <cmd> --json` through the gateway."""

    def __init__(self, profile: str = "openclaw", timeout_s: int = 60):
        self.profile, self.timeout_s, self.tab = profile, timeout_s, None

    def _call(self, *args) -> dict:
        if any(a is None for a in args):
            # 1 Oct 2026 20:20: a tab id of None reached subprocess and the agents turn died
            # with a TypeError (TURN_STUCK). A missing argument is a failed call, by name.
            raise OpenClawFailed(f"openclaw browser {args[0] if args else '?'}: a None argument {list(args)!r}")
        cmd = [*openclaw_cmd(), "browser", "--browser-profile", self.profile, "--json", *args]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise OpenClawFailed(f"openclaw browser {args[0]} timed out after {self.timeout_s}s") from exc
        out = p.stdout.strip()
        i = out.find("{")
        try:
            d = json.loads(out[i:]) if i >= 0 else {}
        except ValueError:
            d = {}
        if p.returncode != 0 or not d.get("ok", True):
            raise OpenClawFailed(f"openclaw browser {args[0]} failed: {(d.get('error') or p.stderr or out)!s:.300}")
        return d

    def _goto(self, url: str) -> None:
        """Open `url` in this driver's tab. If OpenClaw's browser has gone away
        (first real agents turn, 1 Oct 2026: "Browser profile ... is not running",
        and every later call failed on the dead tab) it is started again ONCE and a
        new tab opened; a second failure is raised."""
        if self.tab is not None:
            try:
                self._call("navigate", url, "--target-id", self.tab)
            except OpenClawFailed:
                self.tab = None                         # the browser or the tab is gone: start again below
        if self.tab is None:
            self._call("start")
            self.tab = self._call("open", url).get("tabId")
            if not self.tab:
                raise OpenClawFailed(f"openclaw browser open {url}: no tab id came back")
        try:
            self._call("wait", "--load", "domcontentloaded", "--target-id", self.tab)
        except OpenClawFailed:
            time.sleep(2.5)

    def alive(self) -> bool:
        """OpenClaw's own status for this profile: running or not. A failed status call is not alive."""
        try:
            return bool(self._call("status").get("running"))
        except OpenClawFailed:
            return False

    def start(self) -> None:
        self.tab = None
        self._call("start")

    def stop(self) -> None:
        self.tab = None
        self._call("stop")

    def _eval(self, js: str) -> dict:
        d = self._call("evaluate", "--target-id", self.tab, "--fn", js)
        return {"raw": d, "value": json.loads(d.get("result") or "null")}

    def search(self, query: str) -> dict:
        self._goto(SEARCH_URL.format(q=urllib.parse.quote_plus(query)))
        page = self._eval(_TEXT_JS)
        links = self._eval(_LINKS_JS)
        return {"page": page["value"] or {}, "links": links["value"] or [], "raw": links["raw"]}

    def read_pdf(self, url: str) -> dict:
        """The PDF's bytes, fetched by OpenClaw's browser inside the PDF's own page."""
        self._goto(url)
        d = self._call("evaluate", "--target-id", self.tab, "--fn", _PDF_JS, "--timeout-ms", "60000")
        v = json.loads(d.get("result") or "null") or {}
        import base64
        return {"bytes": base64.b64decode(v.get("b64") or ""), "status": v.get("status"), "type": v.get("type"),
                "raw": {"ok": d.get("ok", True), "status": v.get("status"), "type": v.get("type")}}

    def read(self, url: str) -> dict:
        self._goto(url)
        r = self._eval(_TEXT_JS)
        return {"page": r["value"] or {}, "raw": r["raw"]}


def unwrap(url: str) -> str:
    """DuckDuckGo's redirect link -> the result's own url."""
    q = urllib.parse.urlparse(url)
    if q.netloc.endswith("duckduckgo.com") and q.path.startswith("/l/"):
        return urllib.parse.parse_qs(q.query).get("uddg", [url])[0]
    return url


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def is_captcha(page: dict) -> bool:
    return bool(CAPTCHA.search(f"{page.get('title') or ''}\n{(page.get('text') or '')[:3000]}"))


def store_page(url: str, text: str, need_id: str, tool_raw: dict, pages_dir=None, html: Optional[str] = None,
               ledger=None) -> dict:
    """The page as the browser tool returned it: text (what statements come from)
    and, beside it, the HTML (used only to label regions). HTML over HTML_CAP is
    not stored and HTML_TOO_LARGE is logged."""
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    d = Path(pages_dir or PAGES)
    d.mkdir(parents=True, exist_ok=True)
    doc = {"url": url, "sha256": sha, "need_id": need_id, "stored_utc": _now(), "text": text, "tool_result": tool_raw}
    if html is not None:
        if len(html.encode("utf-8")) <= HTML_CAP:
            doc["html"] = html
        elif ledger is not None:
            ledger({"event": "HTML_TOO_LARGE", "need_id": need_id, "url": url, "bytes": len(html.encode("utf-8"))})
    (d / f"{sha}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return {"url": url, "sha256": sha, "html": "html" in doc}


def serve(need_id: str, query: str, browser, ingest, ledger, pages_dir=None, results: int = RESULTS_PER_NEED,
          category: Optional[str] = None) -> dict:
    """One attempt for one need. -> {pages, captcha, unbacked, statements_added, hosts_gained, hosts_captcha, ...}.
    `ingest(source_id, text, url, origin, extra)` is core.knowledge.ingest; `ledger(row)` appends a ledger row."""
    out = {"need_id": need_id, "query": query, "pages": 0, "captcha": 0, "unbacked": 0, "statements_added": 0,
           "hosts_gained": [], "hosts_captcha": [], "errors": []}
    ledger({"event": "SEARCHED", "need_id": need_id, "query": query, "searcher": "openclaw-browser",
            "category": category})
    try:
        s = browser.search(query)
    except OpenClawFailed as exc:
        out["errors"].append(str(exc))
        ledger({"event": "SEARCHER_ERROR", "need_id": need_id, "why": str(exc)[:300]})
        return out
    if is_captcha(s.get("page") or {}):
        out["captcha"] += 1
        out["hosts_captcha"].append(_host((s.get("page") or {}).get("url") or SEARCH_URL))
        ledger({"event": "CAPTCHA", "need_id": need_id, "host": out["hosts_captcha"][-1], "at": "search page"})
        return out
    links = [unwrap(l.get("url", "")) for l in (s.get("links") or []) if l.get("url")]
    if not links:
        ledger({"event": "NO_RESULTS", "need_id": need_id, "query": query})
        return out
    for url in links[:results]:
        if urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
            out.setdefault("pdfs", []).append(url)
            got = serve_pdf(need_id, url, browser, ingest, ledger, pages_dir)
            if got:
                out["pages"] += 1
                out["statements_added"] += got
                out["hosts_gained"].append(_host(url))
            continue
        try:
            r = browser.read(url)
        except OpenClawFailed as exc:
            out["errors"].append(str(exc))
            ledger({"event": "UNREACHABLE", "need_id": need_id, "url": url, "why": str(exc)[:200]})
            continue
        page, raw = r.get("page") or {}, r.get("raw")
        text = page.get("text") if isinstance(raw, dict) and raw.get("ok", True) else None
        if not isinstance(text, str) or not text.strip():
            out["unbacked"] += 1
            ledger({"event": "UNBACKED", "need_id": need_id, "url": url,
                    "why": "no page text in the browser tool's own result"})
            continue
        if is_captcha(page):
            out["captcha"] += 1
            out["hosts_captcha"].append(_host(url))
            ledger({"event": "CAPTCHA", "need_id": need_id, "host": _host(url), "url": url})
            continue
        html = page.get("html") if isinstance(page.get("html"), str) else None
        st = store_page(url, text, need_id, {k: v for k, v in (raw or {}).items() if k != "result"}, pages_dir,
                        html=html, ledger=ledger)
        extra = {"need_id": need_id, "page_sha256": st["sha256"]}
        if st["html"]:
            from core import knowledge as kn
            extra["main_text"] = kn.main_text(html)
        res = ingest(f"url:{url}", text, url=url, origin="openclaw", extra=extra)
        if res.get("main_unknown"):
            ledger({"event": "MAIN_UNKNOWN", "need_id": need_id, "url": url})
        out["pages"] += 1
        out["statements_added"] += res.get("added", 0)
        if res.get("added"):
            out["hosts_gained"].append(_host(url))
        ledger({"event": "FETCHED", "need_id": need_id, "url": url, "sha256": st["sha256"],
                "statements": res.get("added", 0)})
    ledger({"event": "GAINED", "need_id": need_id, "statements": out["statements_added"], "pages": out["pages"],
            "captcha": out["captcha"], "measurements": 0})
    return out


def imported_modules(path=None) -> set:
    import ast
    tree = ast.parse(Path(path or __file__).read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    return mods | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}


def serve_pdf(need_id: str, url: str, browser, ingest, ledger, pages_dir=None) -> int:
    """A PDF result: its bytes from OpenClaw's browser, its text from pypdf (C-TURN-1
    7b). -> statements added. A PDF the browser cannot fetch, or with no text
    layer, is recorded PDF_NEED with the reason and ingests nothing."""
    from core import knowledge as kn
    if not hasattr(browser, "read_pdf"):
        ledger({"event": "PDF_NEED", "need_id": need_id, "url": url, "why": "this browser cannot fetch a PDF"})
        return 0
    try:
        r = browser.read_pdf(url)
    except OpenClawFailed as exc:
        ledger({"event": "PDF_NEED", "need_id": need_id, "url": url, "why": str(exc)[:200]})
        return 0
    try:
        text = kn.pdf_text(r.get("bytes") or b"")
    except kn.PdfUnreadable as exc:
        ledger({"event": "PDF_NEED", "need_id": need_id, "url": url, "why": f"pdf unreadable: {exc}"[:200]})
        return 0
    st = store_page(url, text, need_id, {**(r.get("raw") or {}), "pdf_bytes": len(r.get("bytes") or b"")}, pages_dir)
    res = ingest(f"url:{url}", text, url=url, origin="openclaw-pdf", extra={"need_id": need_id, "page_sha256": st["sha256"]})
    ledger({"event": "FETCHED", "need_id": need_id, "url": url, "sha256": st["sha256"], "statements": res.get("added", 0),
            "form": "pdf"})
    return res.get("added", 0)


def pending_pdf_needs(ledger_rows: list) -> list:
    """PDF_NEED rows (url, need) that no later FETCHED row of the same url answered."""
    done = {r.get("url") for r in ledger_rows if r.get("event") == "FETCHED"}
    seen, out = set(), []
    for r in ledger_rows:
        if r.get("event") == "PDF_NEED" and r.get("url") not in done and r.get("url") not in seen:
            seen.add(r.get("url"))
            out.append({"need_id": r.get("need_id"), "url": r.get("url")})
    return out


GATEWAY_PORT = 18789


class Gateway:
    """OpenClaw's gateway, the one thing every browser call goes through (C-GW-1).

    healthy(): `openclaw gateway health --json` answers {"ok": true}.
    restart(): what worked on 2 Oct 2026 (C-GW-1 0b) — `openclaw gateway stop --force`
    failed ("port 18789 is still busy after stop"), so the process listening on the
    port is ended (only if its command line is an openclaw gateway), then the service
    is started with `openclaw gateway start` (the scheduled task "OpenClaw Gateway"),
    and health is polled for up to `wait_s`."""

    def __init__(self, timeout_s: int = 60, wait_s: int = 90):
        self.timeout_s, self.wait_s = timeout_s, wait_s

    @staticmethod
    def parse_health(out: str) -> bool:
        i = (out or "").find("{")
        try:
            return bool(json.loads(out[i:]).get("ok") is True) if i >= 0 else False
        except ValueError:
            return False

    def _cli(self, *args, timeout=None) -> subprocess.CompletedProcess:
        return subprocess.run([*openclaw_cmd(), "gateway", *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout or self.timeout_s)

    def healthy(self) -> bool:
        try:
            p = self._cli("health", "--json")
        except subprocess.TimeoutExpired:
            return False
        return p.returncode == 0 and self.parse_health(p.stdout)

    def restart(self) -> None:
        import psutil
        for c in psutil.net_connections("tcp"):
            if c.laddr and c.laddr.port == GATEWAY_PORT and c.status == "LISTEN" and c.pid:
                try:
                    proc = psutil.Process(c.pid)
                    if "openclaw" in " ".join(proc.cmdline()) and "gateway" in " ".join(proc.cmdline()):
                        proc.terminate()
                        psutil.wait_procs([proc], timeout=15)
                except psutil.Error:
                    pass
        try:
            self._cli("start", timeout=180)
        except subprocess.TimeoutExpired:
            pass
        t0 = time.time()
        while time.time() - t0 < self.wait_s and not self.healthy():
            time.sleep(5)


def _on_page(sentence: str, text: str) -> bool:
    from core import knowledge as kn
    return kn._squash(sentence) in kn._squash(text)


def relabel_pages(need_ids: list, browser, store=None, out=None, pages_dir=None) -> dict:
    """C-BRAIN-1 3c: the pages a need's statements came from, re-opened through the
    browser, and each statement labelled main / furniture from the page's HTML now.
    Written to the region index (core.knowledge.REGIONS), never into the store.
    "unknown" stays when: the page is a PDF (no HTML), it did not open, it has no
    HTML, or the sentence is no longer on the page — a label is never guessed."""
    from core import knowledge as kn
    ids = set(need_ids)
    by_url: dict = {}
    for r in kn.statements(store):
        if r.get("need_id") in ids:
            by_url.setdefault(r.get("url"), []).append(r)
    labels, pages = {}, {}
    for url, recs in by_url.items():
        row = {"need_id": recs[0].get("need_id"), "statements": len(recs)}
        pages[url] = row
        if str(url).lower().endswith(".pdf") or any(r.get("origin") == "openclaw-pdf" for r in recs):
            row["why"] = "a PDF: no HTML"
            continue
        try:
            page = (browser.read(url) or {}).get("page") or {}
        except Exception as exc:                                         # noqa: BLE001
            page, row["error"] = {}, f"{type(exc).__name__}: {exc}"[:200]
        html, text = page.get("html"), page.get("text") or ""
        if not page:
            row["why"] = "the page did not open"
            continue
        if not isinstance(html, str) or not html:
            row["why"] = "no HTML returned"
            continue
        st = store_page(url, text, row["need_id"], {"relabel": True}, pages_dir, html=html,
                        ledger=lambda r: row.update(html_too_large=r.get("bytes")))
        row["page_sha256"], row["html_stored"] = st["sha256"], st["html"]
        main = kn.main_text(html)
        here = [dict(r) for r in recs if _on_page(r["sentence"], text)]
        row["main_unknown"] = kn.label_regions(here, main)
        row["not_on_page_now"] = len(recs) - len(here)
        for r in here:
            labels[r["id"]] = r["region"]
        row.update({k: sum(1 for r in here if r["region"] == k) for k in ("main", "furniture")})
    p = Path(out or kn.REGIONS)
    doc = kn._read_json(p, {}) if p.exists() else {}
    doc.setdefault("regions", {}).update(labels)
    doc.setdefault("pages", {}).update(pages)
    doc["utc"] = _now()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    n = sum(len(v) for v in by_url.values())
    counts = {k: sum(1 for v in labels.values() if v == k) for k in ("main", "furniture")}
    counts["unknown"] = n - counts["main"] - counts["furniture"]
    return {"counts": counts, "pages": pages}


def selftest() -> dict:
    res = {"integrations": {}}
    try:
        p = subprocess.run([*openclaw_cmd(), "browser", "--json", "status"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        st = json.loads(p.stdout[p.stdout.find("{"):])
        res["integrations"]["openclaw browser (gateway)"] = (
            f"LIVE ({st.get('detectedBrowser')}, profile {st.get('profile')}, headless {st.get('headless')}, "
            f"running {st.get('running')})")
    except Exception as exc:                                         # noqa: BLE001
        res["integrations"]["openclaw browser (gateway)"] = f"INERT ({type(exc).__name__})"
    res["integrations"]["no requests in the searcher"] = "LIVE" if "requests" not in imported_modules() else "VIOLATED"
    res["ok"] = True
    return res


def main() -> int:
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        return 0
    if "--query" in sys.argv:
        q = sys.argv[sys.argv.index("--query") + 1]
        b = OpenClawBrowser()
        t0 = time.time()
        s = b.search(q)
        print(json.dumps({"seconds": round(time.time() - t0, 1), "captcha": is_captcha(s["page"]),
                          "links": [unwrap(l["url"]) for l in s["links"][:5]]}, indent=1))
        return 0
    if "--relabel" in sys.argv:                  # --relabel BN-1,BN-2: re-open their pages, label regions
        b = OpenClawBrowser()
        t0 = time.time()
        r = relabel_pages(sys.argv[sys.argv.index("--relabel") + 1].split(","), b)
        print(json.dumps({"seconds": round(time.time() - t0, 1), **r}, indent=1, ensure_ascii=False))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())

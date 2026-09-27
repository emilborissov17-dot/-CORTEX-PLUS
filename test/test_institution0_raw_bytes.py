"""Institution 0 rows are published as their exact sealed bytes, and a publish
counts as delivered only when every file read back from GitHub verifies.

Added 27 Sep 2026. Until then institution0/F-00x.json was a {seal, row} envelope:
nobody could sha256 the published file and get the seal's row_sha256, and nothing
read a file back after pushing it, so "delivered" meant "the PUT returned 2xx".

REFUSAL / NO-OUTPUT SUCCESS: when the bytes GitHub returns do not hash to the seal,
the correct result is a ledger row `failed` plus an alarm-class alarm - and NO
`delivered` row. The forbidden fallback is recording `delivered` because the PUT
succeeded.

No network, no live state: requests.put/get are replaced by an in-memory store,
the ledger and forward dir live in tmp_path, the notary and the page are stubbed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import github_publisher as gp  # noqa: E402
from experiments.institution import forward_rows as fr  # noqa: E402
from experiments.institution import register_forward_row as reg  # noqa: E402

ROW_BYTES = ('{\n  "id": "F-009",\n  "commitment": {"title": "Test — ceasefire"}\n}\n').encode("utf-8")


class _Resp:
    def __init__(self, status, body=b"", js=None):
        self.status_code, self.content, self._js = status, body, js

    def json(self):
        return self._js or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeGitHub:
    """PUT stores the decoded bytes under the path; GET returns them (raw) or,
    when `tamper` names the path, returns different bytes."""

    def __init__(self, tamper: str | None = None, fail_get: bool = False):
        self.store, self.tamper, self.fail_get, self.n = {}, tamper, fail_get, 0

    def put(self, url, headers=None, json=None, timeout=None):
        import base64
        path = url.split("/contents/", 1)[1]
        self.store[path] = base64.b64decode(json["content"])
        self.n += 1
        return _Resp(201, js={"commit": {"sha": f"c{self.n:039d}"}})

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.split("/contents/", 1)[1]
        if params is None:                      # _get_sha: file does not exist yet
            return _Resp(404)
        if self.fail_get:
            return _Resp(500)
        body = self.store[path]
        if path == self.tamper:
            body = body.replace(b"\n", b"\r\n")  # what a CRLF rewrite would publish
        return _Resp(200, body)


@pytest.fixture
def world(tmp_path, monkeypatch):
    fdir = tmp_path / "forward"
    fdir.mkdir()
    (fdir / "F-009.json").write_bytes(ROW_BYTES)
    s = fr.seal(fdir / "F-009.json", "prev", {"process": "test"})
    s.update({"row_id": "F-009"})
    (fdir / "F-009.seal.json").write_bytes((json.dumps(s, indent=2) + "\n").encode("utf-8"))
    monkeypatch.setattr(fr, "FORWARD_DIR", fdir)
    monkeypatch.setattr(fr, "PUBLISH_LEDGER", tmp_path / "publish_ledger.jsonl")
    monkeypatch.setattr(reg, "page_all", lambda: "# page\n")
    from core import notary
    monkeypatch.setattr(notary, "may_act", lambda *a, **k: (True, "test gate"))
    monkeypatch.setattr(gp, "_load_token", lambda: "no-token")
    alarms = []
    import supervisor
    monkeypatch.setattr(supervisor, "alarm_human",
                        lambda subject, detail, dedup_key=None, trigger=None, **kw:
                        alarms.append({"subject": subject, "detail": detail, **kw}) or "delivered")
    return {"fdir": fdir, "seal": s, "ledger": tmp_path / "publish_ledger.jsonl", "alarms": alarms}


def _ledger(p: Path) -> list:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _install(monkeypatch, gh: FakeGitHub):
    monkeypatch.setattr(gp.requests, "put", gh.put)
    monkeypatch.setattr(gp.requests, "get", gh.get)


def test_published_row_verifies_from_raw_bytes(world, monkeypatch):
    gh = FakeGitHub()
    _install(monkeypatch, gh)
    assert reg.publish("F-009") == 0
    published = gh.store["institution0/F-009.json"]
    # the published row IS the sealed file, not an envelope around it
    assert published == ROW_BYTES
    assert hashlib.sha256(published).hexdigest() == world["seal"]["row_sha256"]
    # the seal is published beside it (as LF text, what git holds)
    assert gh.store["institution0/F-009.seal.json"] == (world["fdir"] / "F-009.seal.json").read_text(encoding="utf-8").encode("utf-8")
    rows = _ledger(world["ledger"])
    assert [r["outcome"] for r in rows] == ["delivered"]
    assert rows[0]["fetched_sha256"]["institution0/F-009.json"] == world["seal"]["row_sha256"]
    assert world["alarms"] == []


def test_publish_mismatch_is_failed_not_delivered(world, monkeypatch):
    gh = FakeGitHub(tamper="institution0/F-009.json")
    _install(monkeypatch, gh)
    assert reg.publish("F-009") == 6
    rows = _ledger(world["ledger"])
    assert [r["outcome"] for r in rows] == ["failed"], rows
    assert "delivered" not in {r["outcome"] for r in rows}
    assert rows[0]["mismatches"][0]["path"] == "institution0/F-009.json"
    assert rows[0]["mismatches"][0]["expected_sha256"] == world["seal"]["row_sha256"]
    assert len(world["alarms"]) == 1 and world["alarms"][0]["cls"] == "alarm"
    assert "F-009" in world["alarms"][0]["subject"]


def test_fetch_back_error_is_failed_not_delivered(world, monkeypatch):
    """An unread file is not a verified one."""
    _install(monkeypatch, FakeGitHub(fail_get=True))
    assert reg.publish("F-009") == 6
    assert [r["outcome"] for r in _ledger(world["ledger"])] == ["failed"]
    assert world["alarms"] and world["alarms"][0]["cls"] == "alarm"


def test_a_local_row_off_its_seal_is_never_pushed(world, monkeypatch):
    """publish_institution0 refuses before the first PUT when a sealed file's local
    bytes do not hash to its expected sha."""
    gh = FakeGitHub()
    _install(monkeypatch, gh)
    with pytest.raises(ValueError, match="nothing pushed"):
        gp.publish_institution0({"institution0/F-009.json": "changed\n"}, "m",
                                expected={"institution0/F-009.json": world["seal"]["row_sha256"]})
    assert gh.store == {}

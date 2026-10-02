"""
test/test_ucdp_api_client.py — the authenticated UCDP client, against a fake server.

A refusal looks like: UcdpTokenMissing (no token - nothing is sent), or
UcdpCapReached (today's count is at the cap - nothing is sent). The forbidden
fallbacks are an anonymous request and a quiet switch to the files.
No network: the server is a thread on 127.0.0.1.
"""
from __future__ import annotations

import http.server
import json
import threading

import pytest

from core import ucdp_client as uc

TOKEN = "test-token-123"


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        _Handler.seen.append({"path": self.path, "token": self.headers.get(uc.TOKEN_HEADER)})
        if "/fail/" in self.path or self.path.split("?")[0].endswith("/99.9"):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        page = int(self.path.split("page=")[1].split("&")[0])
        body = json.dumps({"TotalCount": 2, "TotalPages": 2,
                           "Result": [{"id": str(page), "type_of_violence": 3}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    _Handler.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(uc, "API_BASE", "http://127.0.0.1:%d/api/gedevents" % srv.server_port)
    monkeypatch.setattr(uc, "REQUESTS_FILE", tmp_path / "ucdp_requests.json")
    monkeypatch.setattr(uc, "PROVENANCE_FILE", tmp_path / "ucdp_provenance.jsonl")
    env = tmp_path / ".env"
    env.write_text("OTHER=x\n%s=%s\n" % (uc.TOKEN_ENV, TOKEN), encoding="utf-8")
    monkeypatch.setattr(uc, "ENV_FILE", env)
    monkeypatch.delenv(uc.TOKEN_ENV, raising=False)
    yield tmp_path
    srv.shutdown()


def _prov(tmp_path):
    return [json.loads(l) for l in (tmp_path / "ucdp_provenance.jsonl")
            .read_text(encoding="utf-8").splitlines()]






def test_the_cap_stops_before_sending(server, monkeypatch):
    # the cap guard stays, though the door's credential refusal now comes first (C-FIX-1)
    from core import openclaw_door as _door
    monkeypatch.setattr(_door, "_credential_header", lambda name: False)
    (server / "ucdp_requests.json").write_text(
        json.dumps({"days": {uc._utc_day(): uc.DAILY_CAP}}), encoding="utf-8")
    with pytest.raises(uc.UcdpCapReached):
        uc.api_get("26.0.8", page=0, pagesize=1)
    assert _Handler.seen == [], "a request went out past the cap"
    assert uc.requests_today() == uc.DAILY_CAP




def test_a_missing_token_refuses_by_name_and_sends_nothing(server, monkeypatch):
    (server / ".env").write_text("OTHER=x\n", encoding="utf-8")
    with pytest.raises(uc.UcdpTokenMissing, match=uc.TOKEN_ENV):
        uc.api_get("26.0.8")
    assert _Handler.seen == [] and uc.requests_today() == 0


def test_the_citation_is_read_from_the_file_and_a_missing_one_raises(tmp_path):
    assert uc.citation().startswith("Hegre, Håvard")
    assert "10.1177/2053168020935257" in uc.citation()
    assert uc.citation("ged").startswith("Sundberg, Ralph")
    with pytest.raises(FileNotFoundError):
        uc.citation(path=tmp_path / "none.json")


def test_through_the_openclaw_door_the_token_is_refused_by_name_and_nothing_is_sent(server):
    """C-FIX-1 Part 3 (2 Oct 2026, Emil R43): decided - no credential leaves through the door."""
    from core import fetch_standard as fs
    with pytest.raises(fs.FetchRefused, match="x-ucdp-access-token"):
        uc.load_events_api("26.0.8", pagesize=1)
    assert _Handler.seen == [], "a request reached the server"
    assert uc.requests_today() == 0, "a request that never left was counted as sent"

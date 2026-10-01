# -*- coding: utf-8 -*-
"""test/test_pdf_reader.py — PDFs are read (C-TURN-1 7b): bytes from OpenClaw's
browser, text from pypdf. A hand-built one-page PDF with a real text layer; the
browser is injected."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import knowledge as kn  # noqa: E402
from scripts import openclaw_search as oc  # noqa: E402


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return bytes(out)


PDF = _pdf("UNHCR counted 1.2 million returns in 2026.")


def test_pdf_text_reads_the_text_layer():
    assert "1.2 million returns" in kn.pdf_text(PDF)


def test_bytes_that_are_not_a_pdf_raise_not_return_empty():
    with pytest.raises(kn.PdfUnreadable):
        kn.pdf_text(b"<html>not a pdf</html>")


class PdfBrowser:
    def __init__(self, data):
        self.data = data

    def read_pdf(self, url):
        return {"bytes": self.data, "raw": {"ok": True, "status": 200, "type": "application/pdf"}}


def _serve(tmp_path, browser):
    rows, ingested = [], []
    n = oc.serve_pdf("BN-1", "https://unhcr.example/r.pdf", browser,
                     lambda sid, text, **k: (ingested.append(text) or {"added": 1}), rows.append, tmp_path / "pages")
    return n, rows, ingested


def test_a_pdf_through_the_browser_is_ingested_with_its_need(tmp_path):
    n, rows, ingested = _serve(tmp_path, PdfBrowser(PDF))
    assert n == 1 and "1.2 million" in ingested[0] and rows[-1]["event"] == "FETCHED" and rows[-1]["form"] == "pdf"
    stored = json.loads(next((tmp_path / "pages").glob("*.json")).read_text(encoding="utf-8"))
    assert stored["need_id"] == "BN-1" and stored["tool_result"]["pdf_bytes"] == len(PDF)


def test_an_unreadable_pdf_stays_a_need_and_ingests_nothing(tmp_path):
    n, rows, ingested = _serve(tmp_path, PdfBrowser(b"garbage"))
    assert n == 0 and ingested == [] and rows[-1]["event"] == "PDF_NEED" and "pdf unreadable" in rows[-1]["why"]


def test_mutation_a_reader_that_returned_empty_would_hide_the_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(kn, "pdf_text", lambda data: "")
    n, rows, ingested = _serve(tmp_path, PdfBrowser(b"garbage"))
    assert rows[-1]["event"] == "FETCHED", "an empty text passing as a read PDF is what the raise prevents"


def test_pending_pdf_needs_are_those_not_yet_fetched():
    rows = [{"event": "PDF_NEED", "need_id": "BN-1", "url": "https://a/x.pdf"},
            {"event": "PDF_NEED", "need_id": "BN-2", "url": "https://a/y.pdf"},
            {"event": "FETCHED", "need_id": "BN-1", "url": "https://a/x.pdf"}]
    assert oc.pending_pdf_needs(rows) == [{"need_id": "BN-2", "url": "https://a/y.pdf"}]

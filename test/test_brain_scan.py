"""The interval head's weights, published while it learns.

WHAT WAS MISSING
----------------
core/interval_head.py trained five times and kept the CURVE and the RUNS —
which say how WELL it did — and never the WEIGHTS, which say WHAT IT LEARNED.
A loss number cannot tell you which input dimension the head leaned on, whether
a unit is dead, or what moved between two runs. None of the five runs could be
inspected after the fact, because nothing had been saved to inspect.

WHAT THIS SUITE HOLDS
---------------------
  * the contract out/brain_map.html reads, key by key — that page is written and
    fixed, and this side is the one that must match;
  * that the no-weights case publishes EXACTLY {"meta":{"weights_persisted":
    false}} and nothing else, because a page of plausible zeros is worse than a
    stated absence;
  * that nothing is ever synthesised — an activation comes from a real forward
    pass through real weights or the row is absent;
  * that publishing is ATOMIC, since the page polls once a second and a partial
    file is a parse error it would have to explain away;
  * that a --dry-run leaves memory/ and snapshots/ byte-identical.
"""
import base64
import hashlib
import json
import pathlib
import sys

import numpy as np
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import interval_head as ih          # noqa: E402
from tools import brain_scan as bs            # noqa: E402

META_KEYS = {"ts", "weights_path", "run_ts", "prev_run_ts", "param_count",
             "embedding", "embedding_dim", "architecture", "alpha",
             "beats_flat_baseline_heldout", "weights_persisted"}
LAYER_KEYS = {"name", "shape", "l2", "mean", "std", "dead_fraction",
              "delta_l2_vs_prev", "delta_mean_vs_prev"}
UNIT_KEYS = {"layer", "index", "bias", "incoming_l2", "incoming_delta_l2",
             "top_dims"}
INPUT_KEYS = {"label", "source_file", "ts", "hidden", "centre", "halfwidth",
              "observed", "trace"}
TRACE_KEYS = {"x", "z1", "a1", "z2", "a2", "z3"}
SIM_KEYS = {"units_l1", "order_l1", "units_l2", "order_l2",
            "input_order_note"}
TRAINING_KEYS = {"epoch", "epochs", "loss", "heldout_loss"}


class _Head:
    """A real IntervalHead shape, deterministic, so a forward pass is genuine."""

    # dim AND hidden are 16 on purpose. top_dims is a fixed 10 in the
    # contract, and layer2 reads from W2 which is hidden x hidden — so a
    # fixture with 4 hidden units would test a 4-wide top_dims the page never
    # sees. The real head is 2048 x 256 x 256; 16 is the smallest width that
    # exercises the same shape.
    def __init__(self, dim=16, hidden=16):
        rng = np.random.default_rng(0)
        self.W1, self.b1 = rng.normal(size=(dim, hidden)), np.zeros(hidden)
        self.W2, self.b2 = rng.normal(size=(hidden, hidden)), np.zeros(hidden)
        self.W3, self.b3 = rng.normal(size=(hidden, 2)) * 0.01, np.zeros(2)


# ── the empty case, which must be exactly empty ────────────────────────────

def test_no_weights_publishes_only_the_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "WEIGHTS", tmp_path / "absent.npz")
    monkeypatch.setattr(bs, "WEIGHTS_PREV", tmp_path / "absent_prev.npz")
    blob = bs.build()
    assert blob == {"meta": {"weights_persisted": False}}, (
        "a page of plausible zeros is worse than a stated absence")


# ── the contract ───────────────────────────────────────────────────────────

def _saved(tmp_path, monkeypatch, prev=False):
    w = tmp_path / "w.npz"
    p = tmp_path / "w_prev.npz"
    h = _Head()
    kw = dict(W1=h.W1, b1=h.b1, W2=h.W2, b2=h.b2, W3=h.W3, b3=h.b3,
              mu=np.zeros(16), sd=np.ones(16), run_ts=np.array("2026-08-28T00:00:00"))
    np.savez_compressed(w, **kw)
    if prev:
        np.savez_compressed(p, **{**kw, "run_ts": np.array("2026-08-27T00:00:00")})
    monkeypatch.setattr(bs, "WEIGHTS", w)
    monkeypatch.setattr(bs, "WEIGHTS_PREV", p)
    return w, p


def test_the_contract_has_exactly_the_keys_the_page_reads(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    b = bs.build()
    assert set(b) == {"meta", "layers", "attention", "attention_delta",
                      "units", "inputs", "input_groups", "similarity"}
    assert META_KEYS <= set(b["meta"])
    for layer in b["layers"]:
        assert set(layer) == LAYER_KEYS
    for u in b["units"]:
        assert set(u) == UNIT_KEYS
        assert len(u["top_dims"]) == 10
        assert all(len(pair) == 2 for pair in u["top_dims"])


def test_attention_is_the_column_norms_of_w1(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    b = bs.build()
    w = np.load(bs.WEIGHTS)
    assert b["attention"] == pytest.approx(
        list(np.linalg.norm(w["W1"], axis=1)))
    assert len(b["attention"]) == w["W1"].shape[0]


def test_delta_is_null_without_a_previous_run(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch, prev=False)
    b = bs.build()
    assert b["attention_delta"] is None
    assert all(l["delta_l2_vs_prev"] is None for l in b["layers"])
    assert b["meta"]["prev_run_ts"] is None


def test_delta_appears_once_a_previous_run_exists(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch, prev=True)
    b = bs.build()
    assert b["attention_delta"] is not None
    assert len(b["attention_delta"]) == len(b["attention"])
    assert b["meta"]["prev_run_ts"] == "2026-08-27T00:00:00"


def test_units_cover_both_hidden_layers(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    b = bs.build()
    assert {u["layer"] for u in b["units"]} == {"layer1", "layer2"}


def test_training_block_only_inside_a_run(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    assert "training" not in bs.build(), "absent means idle"
    live = bs.build(head=_Head(), mu=np.zeros(16), sd=np.ones(16),
                    training={"epoch": 5, "epochs": 400,
                              "loss": 1.0, "heldout_loss": 2.0})
    assert set(live["training"]) == TRAINING_KEYS
    assert live["training"]["epoch"] == 5


# ── nothing is invented ────────────────────────────────────────────────────

def test_an_activation_is_a_real_forward_pass(tmp_path, monkeypatch):
    """Either the row is computed from the weights, or it is not there."""
    _saved(tmp_path, monkeypatch)
    h = _Head()
    x = np.array([0.5] * 16)
    a1, a2, centre, hw = bs._forward(h.W1, h.b1, h.W2, h.b2, h.W3, h.b3, x)
    assert a1 == pytest.approx(np.maximum(x @ h.W1 + h.b1, 0.0))
    assert a2 == pytest.approx(np.maximum(a1 @ h.W2 + h.b2, 0.0))
    assert hw == pytest.approx(float(np.exp((a2 @ h.W3 + h.b3)[1])))
    assert hw > 0, "a halfwidth is a width, not a sign"


def test_a_row_without_a_usable_embedding_is_absent_not_padded(tmp_path, monkeypatch):
    """mu of the wrong width must drop the row, never pad it to fit."""
    _saved(tmp_path, monkeypatch)
    rows = bs._real_input_rows(np.zeros((4, 4)), np.zeros(4), np.zeros((4, 4)),
                               np.zeros(4), np.zeros((4, 2)), np.zeros(2),
                               np.zeros(999), np.ones(999))
    assert rows == []


# ── the write itself ───────────────────────────────────────────────────────

def test_publishing_is_atomic(tmp_path, monkeypatch):
    """No partial file may exist for a once-a-second reader to catch."""
    out = tmp_path / "brain_scan.json"
    monkeypatch.setattr(bs, "WEIGHTS", tmp_path / "absent.npz")
    monkeypatch.setattr(bs, "WEIGHTS_PREV", tmp_path / "absent_prev.npz")
    real_replace = ih.os.replace
    seen = {}

    def _watch(src, dst):
        seen["tmp_existed"] = pathlib.Path(src).exists()
        seen["dst_before"] = pathlib.Path(dst).exists()
        return real_replace(src, dst)

    monkeypatch.setattr(ih.os, "replace", _watch)
    ih.publish_scan(path=out)
    assert seen["tmp_existed"] is True, "written to a tmp file first"
    assert seen["dst_before"] is False, "destination appears only via replace"
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "meta": {"weights_persisted": False}}
    assert not list(tmp_path.glob("*.tmp")), "no tmp file left behind"


def test_saving_rotates_exactly_one_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(ih, "WEIGHTS", tmp_path / "w.npz")
    monkeypatch.setattr(ih, "WEIGHTS_PREV", tmp_path / "w_prev.npz")
    h = _Head()
    ih._save_weights(h, np.zeros(16), np.ones(16), "run-1")
    assert ih.WEIGHTS.exists() and not ih.WEIGHTS_PREV.exists()
    ih._save_weights(h, np.zeros(16), np.ones(16), "run-2")
    assert str(np.load(ih.WEIGHTS)["run_ts"]) == "run-2"
    assert str(np.load(ih.WEIGHTS_PREV)["run_ts"]) == "run-1"


def test_mu_and_sd_travel_with_the_weights(tmp_path, monkeypatch):
    """Without them the weights cannot be run forward and `inputs` is fiction."""
    monkeypatch.setattr(ih, "WEIGHTS", tmp_path / "w.npz")
    monkeypatch.setattr(ih, "WEIGHTS_PREV", tmp_path / "w_prev.npz")
    ih._save_weights(_Head(), np.arange(16.0), np.ones(16) * 2, "run-1")
    z = np.load(ih.WEIGHTS)
    assert set(z.files) >= {"W1", "b1", "W2", "b2", "W3", "b3", "mu", "sd",
                            "run_ts"}
    assert z["mu"] == pytest.approx(np.arange(16.0))


# ── live state ─────────────────────────────────────────────────────────────

def _tree_digest(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.name.encode()); h.update(str(p.stat().st_size).encode())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


@pytest.mark.live_state
def test_a_dry_run_leaves_memory_and_snapshots_byte_identical(tmp_path, monkeypatch):
    """write=False must touch neither tree. Checked around this test alone."""
    mem, snap = REPO / "memory", REPO / "snapshots"
    before = (_tree_digest(mem), _tree_digest(snap))
    monkeypatch.setattr(ih, "WEIGHTS", tmp_path / "w.npz")
    monkeypatch.setattr(ih, "WEIGHTS_PREV", tmp_path / "w_prev.npz")
    monkeypatch.setattr(ih, "SCAN", tmp_path / "brain_scan.json")
    ih.publish_scan(path=tmp_path / "brain_scan.json")
    assert (_tree_digest(mem), _tree_digest(snap)) == before, (
        "publishing wrote into memory/ or snapshots/ — it must only write out/")


# ── the amendment: groups, trace, similarity, matrices ─────────────────────

def test_similarity_is_int8_with_a_stated_scale(tmp_path, monkeypatch):
    """Lossy on purpose, and the loss is DECLARED so a reader can undo it."""
    _saved(tmp_path, monkeypatch)
    b = bs.build()
    s = b["similarity"]
    assert set(s) == SIM_KEYS
    for k in ("units_l1", "units_l2"):
        blk = s[k]
        assert set(blk) == {"shape", "scale", "data"}
        raw = np.frombuffer(base64.b64decode(blk["data"]), dtype=np.int8)
        assert raw.size == blk["shape"][0] * blk["shape"][1]
        assert blk["scale"] > 0, "a scale of zero cannot recover any value"


def test_the_ordering_only_reorders_and_never_invents(tmp_path, monkeypatch):
    """A permutation, not a layout. Every index exactly once, nothing moved."""
    _saved(tmp_path, monkeypatch)
    s = bs.build()["similarity"]
    for key, blk in (("order_l1", "units_l1"), ("order_l2", "units_l2")):
        n = s[blk]["shape"][0]
        assert sorted(s[key]) == list(range(n)), (
            "the ordering must be a permutation — anything else is a layout "
            "algorithm inventing structure the weights do not have")


def test_the_trace_is_interval_head_forward_not_a_second_implementation():
    """Two forward passes drift, and the one that drifts is the unused one."""
    h = _Head()
    x = np.array([0.25] * 16)
    f = h_forward(h, x)
    a1 = np.maximum(x @ h.W1 + h.b1, 0.0)
    assert f["a1"][0] == pytest.approx(a1)


def h_forward(h, x):
    from core.interval_head import IntervalHead
    live = IntervalHead.__new__(IntervalHead)
    live.W1, live.b1, live.W2, live.b2 = h.W1, h.b1, h.W2, h.b2
    live.W3, live.b3 = h.W3, h.b3
    return live.forward(x.reshape(1, -1))


def test_sensor_dims_are_the_last_columns_not_the_first(tmp_path, monkeypatch):
    """row_features() is hstacked AFTER the embedding. Reading embedding_dim as
    the offset put the sensors past the end of W1 — caught on the real file."""
    _saved(tmp_path, monkeypatch)
    b = bs.build()
    g = b["input_groups"]
    assert len(g["sensor_names"]) == 11
    if g["sensor_dims"]:
        assert max(g["sensor_dims"]) < b["layers"][0]["shape"][0], (
            "a sensor dim past the end of W1 indexes nothing")


def test_matrices_are_int8_with_recoverable_scale(tmp_path, monkeypatch):
    _saved(tmp_path, monkeypatch)
    m = bs.matrices()
    assert set(m) == {"W1", "W2", "W3"}
    for k, blk in m.items():
        raw = np.frombuffer(base64.b64decode(blk["data"]), dtype=np.int8)
        assert raw.size == blk["shape"][0] * blk["shape"][1]
        assert blk["scale"] == pytest.approx(
            float(np.max(np.abs(np.load(bs.WEIGHTS)[k]))) / 127.0)


def test_matrices_absent_weights_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "WEIGHTS", tmp_path / "absent.npz")
    assert bs.matrices() == {"weights_persisted": False}

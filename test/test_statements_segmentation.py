"""Nothing is dropped, and the code proves it on every call rather than promising it.

THE PRINCIPLE (Emil, 30 Jul, restated 17 Sep): criteria decide how a statement is
CHECKED, never whether it is KEPT. core/statements.py keeps every sentence of every
cached text. Its guard is not "we tried not to lose text" but a CONSERVATION CHECK
that runs in production: the concatenation of the output, whitespace removed, must
equal the normalised input, whitespace removed. One character short and it raises.

WHY A CONSERVATION CHECK AND NOT A CORRECTNESS ONE. A segmenter is regexes, and a
regex that eats an abbreviation, a bullet or a line of dialogue is the easiest bug
here to ship and the hardest to see, because the output still looks like sentences.
Splitting differently from a human is arguable after the fact — the text is still
there to argue about. Losing a character is not, because the evidence is gone.

THE PARAPHRASE QUESTION, which this file answers structurally rather than by
assertion: there is no text field anywhere for a model to fill. ingest_text builds
records out of the segmenter's output only, and STEP 2.2's model selects an INDEX.
A paraphrase cannot enter because nothing accepts one.
"""
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import statements as S    # noqa: E402


FIXTURE = """Speaker A: Global emissions rose 1.5% in 2024, according to the IEA.
Speaker B: That is not 5% - it is far less, and the distinction matters.
Speaker A: Dr. Hansen disagrees. He expects 2.0 degrees by 2050.
Speaker B: Will the pledge hold? Nobody claims to know.
"""


# ── conservation: the guard ──────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    FIXTURE,
    "One. Two. Three.",
    "No terminal punctuation at all",
    "Mr. Smith met Dr. Jones at 5 p.m. in St. Louis.",
    "Bullet points:\n- first\n- second\n- third",
    "Ellipsis in the middle\u2026 and then more text.",
    "Quotes: \u201cit rose 5%\u201d, he said. Then it fell.",
    "\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430\u0442\u0430 "
    "\u043f\u043e\u043a\u0430\u0437\u0432\u0430 5%. \u0422\u043e\u0432\u0430 "
    "\u0435 \u0444\u0430\u043a\u0442.",
    "a" * 5000,
    "Numbers 1. 2. 3. in a row.",
])
def test_every_character_survives(text):
    segs, _ = S.segment(text)
    assert S._bare("".join(segs)) == S._bare(S.normalise(text))


def test_the_conservation_check_actually_raises(monkeypatch):
    """MUTATION TEST. Break the segmenter so it drops its last sentence; the guard
    must catch it. If this test passes with the check removed, the check is
    decoration."""
    real_split = S._SPLIT

    class Lossy:
        def split(self, line):
            parts = real_split.split(line)
            return parts[:-1] if len(parts) > 1 else parts

    monkeypatch.setattr(S, "_SPLIT", Lossy())
    with pytest.raises(S.SegmentationLostText) as e:
        S.segment("One sentence here. A second one that will vanish.")
    assert "chars in" in str(e.value), "the refusal does not say how much was lost"


def test_the_refusal_names_where_it_diverged(monkeypatch):
    real_split = S._SPLIT          # captured BEFORE the patch, or Lossy calls itself

    class Lossy:
        def split(self, line):
            return [p[:-1] for p in real_split.split(line)]

    monkeypatch.setattr(S, "_SPLIT", Lossy())
    with pytest.raises(S.SegmentationLostText) as e:
        S.segment("Alpha beta gamma. Delta epsilon zeta.")
    assert "divergence" in str(e.value)


# ── normalisation ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("\uff15%", "5%"),
    ("it\u2019s", "it's"),
    ("a\u2014b", "a-b"),
    ("a\u2013b", "a-b"),
    ("a\u00a0b", "a b"),
    ("a\u200bb", "ab"),
    ("\u201cq\u201d", '"q"'),
    ("a  \t  b", "a b"),
])
def test_normalisation_folds_lookalikes(raw, want):
    assert S.normalise(raw) == want


def test_newlines_survive_because_they_carry_speaker_turns():
    assert len(S.segment("Speaker A: it rose.\nSpeaker B: it did not.")) == 2


def test_normalise_refuses_none_by_name():
    with pytest.raises(S.EmptyText):
        S.normalise(None)


# ── the fixture transcript ───────────────────────────────────────────────────

def test_the_negated_number_keeps_its_negation():
    """THE NAMED CASE. "not 5%" must never become "5%". It cannot, because the
    sentence is stored whole and no component rewrites it — but a segmenter that
    split on the dash would have severed the negation from the number."""
    segs, _ = S.segment(FIXTURE)
    hit = [s for s in segs if "5%" in s and "not" in s]
    assert hit, f"the negated sentence did not survive intact: {segs}"
    assert "not 5%" in hit[0]


def test_an_abbreviation_does_not_end_a_sentence():
    segs, _ = S.segment(FIXTURE)
    assert any(s.startswith("Speaker A: Dr. Hansen disagrees.") or
               "Dr. Hansen disagrees." in s for s in segs)
    assert not any(s.strip() in ("Dr.", "Speaker A: Dr.") for s in segs)


def test_records_carry_their_neighbours_and_their_index():
    rep = S.ingest_text("fixture", FIXTURE, url="u://x", origin="transcript")
    recs = rep["records"]
    assert rep["outcome"] == "SEGMENTED" and rep["sentences"] == len(recs)
    for i, r in enumerate(recs):
        assert r["index"] == i
        assert r["before"] == (recs[i - 1]["sentence"] if i else None)
        assert r["after"] == (recs[i + 1]["sentence"] if i + 1 < len(recs) else None)


def test_origin_is_on_every_record():
    """A number heard in AUDIO is a lead, never an observation. The only thing that
    tells the two apart downstream is this field, so it may not be optional."""
    rep = S.ingest_text("fixture", FIXTURE, origin="transcript")
    assert all(r["origin"] == "transcript" for r in rep["records"])


def test_a_record_carries_no_truth_value_and_no_type():
    """STEP 2.4: a stored statement asserts only that source S said this. Typing is
    a later, separate lane; a type field here would make the store the judge."""
    r = S.ingest_text("fixture", FIXTURE)["records"][0]
    for forbidden in ("type", "verdict", "truth", "true", "confidence", "axis",
                      "narration", "score"):
        assert forbidden not in r, f"{forbidden!r} does not belong in a statement record"


def test_there_is_no_text_field_a_model_could_fill():
    """THE PARAPHRASE GUARD, structural. Every string field of a record is either
    copied from the segmenter's output or is metadata. If a future edit adds a
    free-text field, this fails and the author has to justify it."""
    r = S.ingest_text("fixture", FIXTURE)["records"][2]
    segs, _ = S.segment(FIXTURE)
    assert r["sentence"] in segs
    assert r["before"] in segs and r["after"] in segs
    allowed = {"id", "source_id", "url", "origin", "index", "sentence", "before",
               "after", "chars", "segmentation", "method_version", "ingested_at"}
    assert set(r) <= allowed, f"unexpected field(s): {set(r) - allowed}"


def test_ids_are_stable_across_runs():
    a = S.ingest_text("fixture", FIXTURE)["records"]
    b = S.ingest_text("fixture", FIXTURE)["records"]
    assert [x["id"] for x in a] == [x["id"] for x in b]


def test_a_different_source_gives_a_different_id_for_the_same_sentence():
    assert S.statement_id("s1", 0, "Same words.") != S.statement_id("s2", 0, "Same words.")


# ── empty and degenerate inputs ──────────────────────────────────────────────

def test_empty_text_is_a_named_outcome_not_a_crash():
    rep = S.ingest_text("empty", "   \n\n  ")
    assert rep["outcome"] == "NO_SENTENCES" and rep["records"] == []


def test_a_text_of_only_punctuation_is_still_conserved():
    assert S._bare("".join(S.segment("... !!! ???")[0])) == S._bare(S.normalise("... !!! ???"))


# ── embedding provenance ─────────────────────────────────────────────────────

def test_a_hashed_fallback_is_recorded_not_hidden():
    """interval_head.embed re-hashes EVERY text when Ollama is unreachable, so the
    space stays coherent. The caller must store that fact: a neighbour list built on
    hashes is not semantic, and a later reader cannot tell without this field."""
    recs = S.ingest_text("fixture", FIXTURE)["records"]

    def fake_embed(texts):
        import numpy as np
        return np.zeros((len(texts), 4)), "hashed_fallback"

    vecs, source = S.embed_records(recs, embed=fake_embed)
    assert source == "hashed_fallback"
    assert set(vecs) == {r["id"] for r in recs}


def test_embedding_no_records_is_not_an_error():
    assert S.embed_records([]) == ({}, "none")


# ── window fallback: the unpunctuated transcript ─────────────────────────────
#
# Measured on the corpus 17 Sep 2026: data/media_transcripts/.../
# This_Country_will_be_Gone_in_25_Years… is 15,047 characters and segments into 13
# "sentences" — about 190 words each — because the auto-transcript carries almost no
# terminal punctuation. Restoring punctuation with a model was rejected: it CHANGES
# THE TEXT, and every guard in this layer rests on the stored sentence being what the
# source said. A window is an arbitrary boundary that admits it is one.

MEASURED_UNPUNCTUATED = REPO / "data" / "media_transcripts"


def _long_unpunctuated(words=600):
    return " ".join(f"word{i}" for i in range(words))


def test_an_unpunctuated_text_falls_back_to_windows():
    segs, mode = S.segment(_long_unpunctuated())
    assert mode == "window"
    assert all(len(x.split()) <= S.WINDOW_WORDS for x in segs)


def test_windows_do_not_overlap_and_lose_nothing():
    text = _long_unpunctuated(250)
    segs, mode = S.segment(text)
    assert mode == "window"
    assert " ".join(segs).split() == S.normalise(text).split(), "windows overlap or drop"
    assert S._bare("".join(segs)) == S._bare(S.normalise(text))


def test_a_normally_punctuated_text_does_not_use_windows():
    """The trigger must not fire on ordinary prose, or every transcript becomes
    windowed and the sentence boundaries a source really gave us are thrown away."""
    _, mode = S.segment(FIXTURE)
    assert mode == "sentence"


def test_the_trigger_is_mean_sentence_length_not_total_length():
    """A long text of short sentences stays sentence-mode. Only the ABSENCE of
    punctuation — measured as mean words per sentence — switches the mode."""
    long_but_punctuated = " ".join(f"Sentence number {i} is short." for i in range(400))
    _, mode = S.segment(long_but_punctuated)
    assert mode == "sentence"


def test_the_conservation_check_still_applies_in_window_mode(monkeypatch):
    """MUTATION TEST for the window path. The guard must not be bypassed by the
    fallback — that is exactly where a silent loss would hide."""
    monkeypatch.setattr(S, "_window_segments",
                        lambda norm, size=S.WINDOW_WORDS: norm.split()[:3])
    with pytest.raises(S.SegmentationLostText):
        S.segment(_long_unpunctuated())


def test_the_mode_is_recorded_on_every_record():
    rep = S.ingest_text("u", _long_unpunctuated(), origin="transcript")
    assert rep["segmentation"] == "window"
    assert all(r["segmentation"] == "window" for r in rep["records"])


@pytest.mark.skipif(not MEASURED_UNPUNCTUATED.exists(), reason="corpus not present")
def test_the_measured_file_now_segments_by_window():
    """The real file that motivated this, by name. 15,047 chars / 13 sentences
    under the old rule; it must now be windowed and still conserve every character."""
    hits = [f for f in MEASURED_UNPUNCTUATED.rglob("This_Country_will_be_Gone*")
            if f.is_file()]
    if not hits:
        pytest.skip("the measured file is not in this checkout")
    raw = hits[0].read_text(encoding="utf-8", errors="replace")
    segs, mode = S.segment(raw)
    assert mode == "window", "the file that forced this rule is not using it"
    # 13 "sentences" under the old rule. The claim is that windowing replaces
    # a handful of 190-word blocks with many bounded ones, not a magic number.
    assert len(segs) > 50, f"expected many windows, got {len(segs)}"
    assert S._bare("".join(segs)) == S._bare(S.normalise(raw))


# ── shard ceiling ────────────────────────────────────────────────────────────

def test_a_shard_at_the_ceiling_refuses_and_does_not_grow(tmp_path, monkeypatch):
    """embed_index is exhaustive numpy over an mmap'd matrix; its own selftest puts
    50,000 vectors at ~410 MB, and this machine has already killed a cycle at 99%
    RAM. A shard that grew past the ceiling would turn a design choice into an
    out-of-memory night with nothing pointing back here."""
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)
    vecs = {f"id{i}": [0.1, 0.2, 0.3] for i in range(6)}
    with pytest.raises(S.ShardFull) as e:
        S.build_index(vecs, "2026-09", ceiling=5)
    assert "2026-09" in str(e.value) and "ceiling 5" in str(e.value)


def test_under_the_ceiling_the_shard_builds(tmp_path, monkeypatch):
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)
    meta = S.build_index({f"id{i}": [0.1, 0.2, 0.3] for i in range(4)},
                         "2026-09", ceiling=50)
    assert meta["shard"] == "2026-09" and meta["vectors"] == 4
    assert meta["bytes"] > 0, "the index size must be reported — it is a number to watch"


def test_the_shard_is_the_month_of_the_source_not_of_the_ingest():
    """A re-ingest must land in the shard the TEXT belongs to. Sharding by ingest
    month would put the same sentence in two shards and return it twice."""
    import datetime as _dt
    ts = _dt.datetime(2026, 6, 17, 12, 0, tzinfo=_dt.timezone.utc).timestamp()
    assert S.shard_for(ts) == "2026-06"
    assert S.shard_for("2026-06-17T00:00:00+00:00") == "2026-06"


# ── a shard accumulates ──────────────────────────────────────────────────────
#
# CAUGHT BEFORE COMMIT, on the real partial ingest: shard 2026-07 held 1041
# statements and 433 vectors. embed_index.build() writes keys.json and vectors.npy
# FRESH from what it is handed, so handing it one batch replaced the shard with that
# batch. Nothing failed, nothing logged — the index was simply the last batch, and a
# neighbour search would have quietly missed everything ingested before it.

def test_a_second_batch_does_not_replace_the_first(tmp_path, monkeypatch):
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)

    first = {f"a{i}": [1.0, 0.0, float(i)] for i in range(3)}
    second = {f"b{i}": [0.0, 1.0, float(i)] for i in range(4)}
    S.build_index(first, "2026-07")
    meta = S.build_index(second, "2026-07")

    assert meta["vectors"] == 7, f"the shard holds {meta['vectors']}, not 3+4"
    assert meta["kept"] == 3 and meta["added"] == 4
    keys = json.loads((tmp_path / "2026-07" / "keys.json").read_text(encoding="utf-8"))
    assert set(keys) == set(first) | set(second)


def test_re_ingesting_the_same_ids_overwrites_only_those(tmp_path, monkeypatch):
    """Statement ids are stable, so a re-ingest must update its own rows and leave
    every other row in the month alone."""
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)

    S.build_index({"keep": [1.0, 0.0, 0.0], "redo": [0.0, 1.0, 0.0]}, "2026-07")
    meta = S.build_index({"redo": [0.0, 0.0, 1.0]}, "2026-07")
    assert meta["vectors"] == 2 and meta["added"] == 0 and meta["kept"] == 2


def test_the_ceiling_counts_the_union_not_just_the_batch(tmp_path, monkeypatch):
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)
    S.build_index({f"a{i}": [1.0, 0.0, 0.0] for i in range(4)}, "2026-07", ceiling=6)
    with pytest.raises(S.ShardFull):
        S.build_index({f"b{i}": [0.0, 1.0, 0.0] for i in range(4)}, "2026-07", ceiling=6)


def test_an_unreadable_shard_refuses_rather_than_overwriting(tmp_path, monkeypatch):
    """MUTATION-SHAPED GUARD. If the shard cannot be read back, rebuilding it from
    this batch alone would DELETE every vector already in it. Refuse instead."""
    from core import embed_index
    monkeypatch.setattr(embed_index, "INDEX_DIR", tmp_path)
    S.build_index({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]}, "2026-07")
    # keys and vectors disagree — a truncated write, which is what a killed run risks
    (tmp_path / "2026-07" / "keys.json").write_text('["a"]', encoding="utf-8")
    with pytest.raises(S.ShardUnreadable) as e:
        S.build_index({"c": [0.0, 0.0, 1.0]}, "2026-07")
    assert "would delete" in str(e.value)

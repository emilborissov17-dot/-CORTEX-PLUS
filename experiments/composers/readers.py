#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/composers/readers.py — deterministic readers for the three payload families
that carry the world's official statistics.

PURE PARSERS. Nothing here fetches; composer.py does the HTTP and hands the payload in.
That keeps every one of these testable against a captured response with no network, and it
keeps the fetch policy (throttle, backoff, cache) in exactly one place.

ZERO MODEL IN THE READ PATH. Each reader resolves a value by a DECLARED address —
a row key, a dimension code, a series key. None of them infers, ranks, or picks "the most
relevant" anything. Where an address matches nothing, the reader RAISES with the address
named and a sample of what was actually present. It never substitutes a neighbouring value.
That rule is the whole reason these exist: a wrong-but-plausible number passes every
downstream guard we have, because grounding, Merkle and smoke-fetch all verify that we read
correctly — none of them can notice that we read the wrong cell.

THE THREE FAMILIES, and why each earns its own reader (probed live 2026-08-03):

  json_rows  Row-shaped JSON APIs. The UN SDG API answers
             {data: [ {geoAreaCode, timePeriodStart, value, dimensions:{...}}, ... ] }.
             713 series in its catalog, every one addressable the same way. This is the
             JSON twin of the CSV row_key selection: same contract, same loud failure.

  jsonstat   JSON-stat 2.0, which is how Eurostat answers. {id:[dims], size:[...],
             value:{flatIndex: number}, dimension:{d:{category:{index:{code:pos}}}}}.
             The value map is a FLAT row-major index over `size`, so a cell is addressed by
             giving a code per dimension and computing the offset. Eurostat is the only
             route to MONTHLY and QUARTERLY official series in this portfolio; the annual
             aggregators structurally cannot fill a monthly slot.

  sdmx       SDMX-JSON, which is how ECB, OECD and a large share of national institutes
             answer. ONE reader, not one adapter per country. It handles both shapes the
             standard permits, because providers really do differ:
               series-major  (ECB)  dataSets[0].series["0:0:0"].observations["0"] = [v,..]
               flat          (OECD, with dimensionAtObservation=AllDimensions)
                                    dataSets[0].observations["36:0:0:..."] = [v,..]

WHAT DID NOT WORK, recorded rather than quietly dropped (probed 2026-08-03):
  Eurostat SDMX 2.1 answers 406 to every SDMX-JSON request, with and without an Accept
  header — so Eurostat is reached through JSON-stat, not through the SDMX reader.
  IMF's SDMX endpoint answers XML only (api.imf.org) and its older JSON host does not
  resolve. IMF is therefore SKIPPED, not blacklisted: nothing is wrong with IMF, we simply
  cannot read that dialect yet, and those are different facts.
"""
from __future__ import annotations


class RowNotFound(ValueError):
    """An address was declared and the payload does not contain it.

    Deliberately a ValueError: composer.classify_failure reads that as
    `unparseable_payload`, a FETCH-class failure — the source answered and the answer did
    not contain what we asked for. That is a fact about the response, not about our record.
    """


def dotted(d, path):
    """Walk a dotted path. An integer part indexes a LIST ('daily.time.-1'), so the
    array-shaped APIs most open feeds return are reachable without a bespoke parser."""
    cur = d
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _num(x):
    """A number, or None. UN SDG returns its values as STRINGS ('8.535747528'), so a
    reader that only accepted floats would report an empty world."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _sample(values, n=6):
    out = []
    for v in values:
        if v not in out:
            out.append(v)
        if len(out) >= n:
            break
    return out


# ── row-shaped JSON (UN SDG and friends) ─────────────────────────────────────

def read_json_rows(payload, src: dict) -> tuple:
    """(value, data_date) from a JSON array of records.

      extract           dotted path to the array          e.g. "data"
      row_key_column    field selecting the entity        e.g. "geoAreaCode"
      row_key           the value it must equal           e.g. "1"  (M49: World)
      where             {dotted field: value} extra filters, ALL of which must match
                        e.g. {"dimensions.Location": "ALLAREA"}
      column_name       field holding the measurement     e.g. "value"
      data_date_column  field holding the period          e.g. "timePeriodStart"

    Among matching rows the LATEST by data_date wins. A panel is a panel: without an
    explicit key the newest row of an arbitrary entity would be returned, which is the
    same failure as reading the last row of a 195-country CSV.
    """
    rows = dotted(payload, src["extract"]) if src.get("extract") else payload
    if not isinstance(rows, list):
        raise RowNotFound(f"json_rows: {src.get('extract')!r} is not an array "
                          f"(got {type(rows).__name__})")
    if not rows:
        raise RowNotFound("json_rows: the array is empty")

    col = src.get("column_name") or "value"
    date_col = src.get("data_date_column")
    key_col, key = src.get("row_key_column"), src.get("row_key")
    where = src.get("where") or {}

    hits = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if key is not None and str(dotted(r, key_col) if key_col else None) != str(key):
            continue
        if any(str(dotted(r, f)) != str(v) for f, v in where.items()):
            continue
        v = _num(dotted(r, col))
        if v is None:
            continue
        hits.append((str(dotted(r, date_col)) if date_col else "", v))

    if not hits:
        present = _sample([str(dotted(r, key_col)) for r in rows if isinstance(r, dict)]) \
            if key_col else []
        dims = _sample([str(dotted(r, f)) for r in rows if isinstance(r, dict)]
                       for f in where) if where else []
        raise RowNotFound(
            f"json_rows: no row over {len(rows)} where "
            f"{key_col}=={key!r}" + (f" and {where}" if where else "")
            + f" carries a numeric {col!r}."
            + (f" Present {key_col}: {present}." if present else "")
            + (f" Present filter values: {list(dims)}." if dims else "")
            + " Refusing to read a different row — a fallback here would answer a "
              "question nobody asked")

    hits.sort(key=lambda dv: dv[0])
    date, value = hits[-1]
    return value, (date or None)


# ── JSON-stat 2.0 (Eurostat) ─────────────────────────────────────────────────

def read_jsonstat(payload, src: dict) -> tuple:
    """(value, data_date) from a JSON-stat 2.0 dataset.

      cell   {dimension_id: category_code} for every dimension you wish to pin,
             e.g. {"geo": "EU27_2020", "unit": "PC_ACT"}. Dimensions left unpinned must
             have exactly one category, or the address is ambiguous and this raises.

    The time dimension is special-cased: left unpinned it resolves to the LATEST period
    present, which is what a live indicator wants, and that period is returned as the
    data date so the composer's staleness refusal has something to work with.
    """
    if not isinstance(payload, dict) or "value" not in payload:
        raise RowNotFound("jsonstat: payload has no 'value' map — not a JSON-stat dataset")
    ids = payload.get("id") or []
    size = payload.get("size") or []
    dim = payload.get("dimension") or {}
    if len(ids) != len(size):
        raise RowNotFound(f"jsonstat: id/size disagree ({len(ids)} vs {len(size)})")

    cell = dict(src.get("cell") or {})
    unknown = [d for d in cell if d not in ids]
    if unknown:
        raise RowNotFound(f"jsonstat: cell names dimension(s) {unknown} that are not in "
                          f"this dataset {ids}")

    pos, chosen, time_period = [], {}, None
    for i, dname in enumerate(ids):
        index = ((dim.get(dname) or {}).get("category") or {}).get("index") or {}
        # JSON-stat allows either {code: pos} or an ordered [code, ...]
        if isinstance(index, list):
            index = {c: n for n, c in enumerate(index)}
        if dname in cell:
            code = str(cell[dname])
            if code not in index:
                raise RowNotFound(
                    f"jsonstat: dimension {dname!r} has no category {code!r}. "
                    f"Present: {_sample(list(index))}. Refusing to read a different "
                    f"category — a fallback here would answer a question nobody asked")
            p = index[code]
        elif size[i] == 1:
            code, p = (list(index) or ["?"])[0], 0
        elif dname.lower() in ("time", "time_period"):
            code = sorted(index, key=lambda c: str(c))[-1]     # the latest period
            p = index[code]
        else:
            raise RowNotFound(
                f"jsonstat: dimension {dname!r} has {size[i]} categories and the cell does "
                f"not pin it — the address is ambiguous. Present: {_sample(list(index))}")
        pos.append(p)
        chosen[dname] = code
        if dname.lower() in ("time", "time_period"):
            time_period = code

    stride, flat = 1, 0
    for i in range(len(size) - 1, -1, -1):
        flat += pos[i] * stride
        stride *= int(size[i])

    values = payload["value"]
    raw = values.get(str(flat)) if isinstance(values, dict) else (
        values[flat] if flat < len(values) else None)
    v = _num(raw)
    if v is None:
        raise RowNotFound(f"jsonstat: cell {chosen} resolves to flat index {flat}, which "
                          f"holds {raw!r} — the provider published no value there")
    return v, time_period


# ── SDMX-JSON (ECB, OECD, national institutes) ───────────────────────────────

def _sdmx_structure(data: dict, ds: dict) -> dict:
    if "structure" in data and isinstance(data["structure"], dict):
        return data["structure"]
    structs = data.get("structures") or []
    if structs:
        i = ds.get("structure", 0)
        return structs[i if isinstance(i, int) and i < len(structs) else 0]
    return {}


def _sdmx_observations(data: dict):
    """Yield ({dimension_id: code}, value) for every observation, in either shape.

    SDMX-JSON permits series-major (ECB) and fully flat (OECD with
    dimensionAtObservation=AllDimensions). One reader handles both rather than one adapter
    per provider, which was the whole point: the same reader is what unlocks the national
    institutes without a file each."""
    root = data.get("data") if isinstance(data.get("data"), dict) else data
    sets = root.get("dataSets") or []
    if not sets:
        raise RowNotFound("sdmx: no dataSets in the payload")
    ds = sets[0]
    struct = _sdmx_structure(root, ds)
    dims = struct.get("dimensions") or {}
    sdims = dims.get("series") or []
    odims = dims.get("observation") or []

    def codes(dlist, key):
        out = {}
        for i, p in enumerate(str(key).split(":")):
            if i >= len(dlist):
                break
            vals = dlist[i].get("values") or []
            try:
                out[dlist[i].get("id")] = vals[int(p)].get("id")
            except (ValueError, IndexError):
                out[dlist[i].get("id")] = None
        return out

    if ds.get("series"):
        for skey, sobj in ds["series"].items():
            base = codes(sdims, skey)
            for okey, oval in (sobj.get("observations") or {}).items():
                full = dict(base)
                full.update(codes(odims, okey))
                yield full, (oval or [None])[0]
    else:
        for okey, oval in (ds.get("observations") or {}).items():
            yield codes(odims, okey), (oval or [None])[0]


def read_sdmx(payload, src: dict) -> tuple:
    """(value, data_date) from an SDMX-JSON response.

      series_key   {DIMENSION_ID: code} — every pair must match, e.g.
                   {"REF_AREA": "EU27_2020", "SEX": "_T", "AGE": "Y_GE15", "FREQ": "M"}

    The latest TIME_PERIOD among matching observations wins, and is returned as the data
    date. An empty match set raises with the key named and the codes that WERE present per
    dimension — so a provider renaming a code produces a diagnosis, not a silent gap.
    """
    key = {str(k): str(v) for k, v in (src.get("series_key") or {}).items()}
    obs, seen = [], {}
    for dims, value in _sdmx_observations(payload):
        for k, v in dims.items():
            seen.setdefault(k, [])
            if v not in seen[k]:
                seen[k].append(v)
        if any(str(dims.get(k)) != v for k, v in key.items()):
            continue
        num = _num(value)
        if num is None:
            continue
        obs.append((str(dims.get("TIME_PERIOD") or dims.get("TIME") or ""), num))

    if not obs:
        mismatched = {k: _sample(seen.get(k, [])) for k, v in key.items()
                      if v not in seen.get(k, [])}
        raise RowNotFound(
            f"sdmx: no observation matches {key}. "
            + (f"These dimensions do not carry the code asked for: {mismatched}. "
               if mismatched else "")
            + f"Dimensions present: { {k: len(v) for k, v in seen.items()} }. "
              "Refusing to read a different series — a fallback here would answer a "
              "question nobody asked")

    obs.sort(key=lambda dv: dv[0])
    date, value = obs[-1]
    return value, (date or None)

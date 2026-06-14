"""
self_observer.py — сензорен слой за устойчива цивилизация
Категории: ЗАПЛАХИ | ЗДРАВЕ НА ЧОВЕЧЕСТВОТО | ПРОГРЕС | ЗДРАВЕ НА ЗЕМЯТА
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

import aiohttp

log = logging.getLogger("SelfObserver")

NASA_API_KEY = "YqLuYCSD6iN2XXYWj4z9fhOe9CrAeIFtSnUgamDR"  # замени с реален ключ от api.nasa.gov

_cache: dict = {}
CACHE_TTL = 3600  # 1 час за бавно-променящи се данни


@dataclass
class Signal:
    source: str
    category: str   # THREATS | HUMAN_HEALTH | PROGRESS | EARTH_HEALTH
    domain: str     # по-детайлна подкатегория
    metric: str
    value: Any
    delta: float | None
    timestamp: str
    raw: dict


class SelfObserver:
    def __init__(self):
        self.last_values: dict = self._load_last_values()
        self.sources = [
            # ── ЗАПЛАХИ ──────────────────────────────────────────
            self._observe_usgs_earthquakes,
            self._observe_nasa_asteroids,
            self._observe_who_outbreaks,
            self._observe_noaa_climate,
            # ── ЗДРАВЕ НА ЧОВЕЧЕСТВОТО ───────────────────────────
            self._observe_unhcr_refugees,
            self._observe_world_bank,
            self._observe_fews_famine,
            # ── ПРОГРЕС ──────────────────────────────────────────
            self._observe_arxiv,
            self._observe_github_trending,
            # ── ЗДРАВЕ НА ЗЕМЯТА ─────────────────────────────────
            self._observe_noaa_co2,
            self._observe_solar_activity,
            self._observe_gbif_occurrences,
        ]

    # ── persistence ──────────────────────────────────────────────────────────

    def _load_last_values(self) -> dict:
        try:
            with open("data/last_observations.json") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _save_last_values(self):
        with open("data/last_observations.json", "w") as f:
            json.dump(self.last_values, f, indent=2, ensure_ascii=False)

    def _delta(self, key: str, value: float) -> float | None:
        prev = self.last_values.get(key)
        self.last_values[key] = value
        return round(value - prev, 4) if prev is not None else None

    # ── main entry ───────────────────────────────────────────────────────────

    async def observe(self) -> list[Signal]:
        tasks = [src() for src in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: list[Signal] = []
        for result in results:
            if isinstance(result, Exception):
                log.warning(f"Грешка: {result}")
                continue
            if isinstance(result, list):
                signals.extend(result)

        self._save_last_values()
        log.info(f"Събрани {len(signals)} сигнала")
        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # ЗАПЛАХИ
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_usgs_earthquakes(self) -> list[Signal]:
        """USGS real-time — земетресения M≥5.0 от последния час."""
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5.0&limit=10&orderby=time"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(url) as r:
                    text = await r.text(encoding="latin-1")
            import json as _json
            # USGS понякога връща ")]}'" преди JSON — изчистваме го
            text = text.strip()
            if text.startswith(")]}"):
                text = text[text.index("{"):]
            data = _json.loads(text)

            signals = []
            for feat in data.get("features", [])[:10]:
                props = feat["properties"]
                coords = feat["geometry"]["coordinates"]
                mag = props.get("mag", 0)
                signals.append(Signal(
                    source="USGS Earthquake Feed",
                    category="THREATS",
                    domain="geological",
                    metric="earthquake_magnitude",
                    value=mag,
                    delta=None,
                    timestamp=datetime.utcfromtimestamp(props["time"] / 1000).isoformat(),
                    raw={
                        "place": props.get("place"),
                        "mag": mag,
                        "lon": coords[0],
                        "lat": coords[1],
                        "depth_km": coords[2],
                        "url": props.get("url"),
                    },
                ))
            log.info(f"USGS: {len(signals)} земетресения M≥5.0")
            return signals
        except Exception as e:
            log.warning(f"usgs_earthquakes failed: {e}")
            return []

    async def _observe_nasa_asteroids(self) -> list[Signal]:
        """NASA NeoWs — близки астероиди за днес."""
        cache_key = "nasa_neows"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < CACHE_TTL:
                return cd

        today = datetime.utcnow().strftime("%Y-%m-%d")
        url = "https://api.nasa.gov/neo/rest/v1/feed"
        params = {"start_date": today, "end_date": today, "api_key": NASA_API_KEY}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(url, params=params) as r:
                    if r.status == 429:
                        log.warning("NASA NeoWs: 429 rate limit")
                        return _cache.get(cache_key, (None, []))[1]
                    data = await r.json(content_type=None)

            signals = []
            neos = data.get("near_earth_objects", {}).get(today, [])
            # Сортирай по близост
            neos.sort(key=lambda x: float(
                x.get("close_approach_data", [{}])[0]
                 .get("miss_distance", {}).get("lunar", "999")
            ))
            for neo in neos[:5]:
                approach = neo.get("close_approach_data", [{}])[0]
                miss_lunar = float(approach.get("miss_distance", {}).get("lunar", "0"))
                diameter_max = neo.get("estimated_diameter", {}).get("kilometers", {}).get("estimated_diameter_max", "0")
                hazardous = neo.get("is_potentially_hazardous_asteroid", False)
                signals.append(Signal(
                    source="NASA NeoWs",
                    category="THREATS",
                    domain="space",
                    metric="asteroid_miss_distance_lunar",
                    value=round(float(miss_lunar), 2),
                    delta=None,
                    timestamp=datetime.utcnow().isoformat(),
                    raw={
                        "name": neo.get("name"),
                        "diameter_km_max": round(float(diameter_max), 3),
                        "miss_distance_lunar": round(float(miss_lunar), 2),
                        "velocity_kmh": approach.get("relative_velocity", {}).get("kilometers_per_hour"),
                        "hazardous": hazardous,
                    },
                ))

            _cache[cache_key] = (time.time(), signals)
            log.info(f"NASA NeoWs: {len(signals)} астероида")
            return signals
        except Exception as e:
            log.warning(f"nasa_asteroids failed: {e}")
            return []

    async def _observe_who_outbreaks(self) -> list[Signal]:
        """WHO Disease Outbreak News RSS — uses urllib to bypass aiohttp header limit."""
        import urllib.request
        url = "https://www.who.int/rss-feeds/news-english.xml"
        try:
            loop = asyncio.get_event_loop()

            def _fetch():
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (CORTEX++ planetary monitor)"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read().decode("utf-8", errors="replace")

            text = await loop.run_in_executor(None, _fetch)

            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text)
            keywords = ["outbreak", "disease", "virus", "epidemic", "pandemic",
                        "cholera", "ebola", "mpox", "dengue", "flu", "measles"]
            outbreak_titles = [t.strip() for t in titles if any(k in t.lower() for k in keywords)][:5]

            signals = [
                Signal(
                    source="WHO RSS",
                    category="THREATS",
                    domain="pandemic",
                    metric="outbreak_headline",
                    value=title,
                    delta=None,
                    timestamp=datetime.utcnow().isoformat(),
                    raw={"title": title},
                )
                for title in outbreak_titles
            ]
            log.info(f"WHO: {len(signals)} outbreak новини")
            return signals
        except Exception as e:
            log.warning(f"who_outbreaks failed: {e}")
            return []


    async def _observe_noaa_climate(self) -> list[Signal]:
        """NOAA Climate.gov — текуща глобална температурна аномалия (RSS)."""
        url = "https://www.climate.gov/news-features/feed"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as s:
                async with s.get(url) as r:
                    text = await r.text(encoding="latin-1")

            titles = re.findall(r"<title>(.*?)</title>", text)
            # Вземи само климатични заглавия (не RSS заглавие)
            climate_titles = [t for t in titles[1:6] if len(t) > 10]

            signals = [
                Signal(
                    source="NOAA Climate.gov RSS",
                    category="THREATS",
                    domain="climate",
                    metric="climate_headline",
                    value=title,
                    delta=None,
                    timestamp=datetime.utcnow().isoformat(),
                    raw={"title": title},
                )
                for title in climate_titles
            ]
            log.info(f"NOAA Climate: {len(signals)} сигнала")
            return signals
        except Exception as e:
            log.warning(f"noaa_climate failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # ЗДРАВЕ НА ЧОВЕЧЕСТВОТО
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_unhcr_refugees(self) -> list[Signal]:
        """UNHCR API — глобален брой бежанци (последна година)."""
        cache_key = "unhcr_refugees"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < CACHE_TTL:
                return cd

        url = "https://api.unhcr.org/population/v1/population/"
        params = {"limit": 1, "yearFrom": 2022, "yearTo": 2022}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(url, params=params) as r:
                    text = await r.text(encoding="latin-1", errors="replace")
            import json as _j; data = _j.loads(text)

            total_obj = data.get("total", {}) or {}
            raw_refugees  = total_obj.get("refugees", 0)
            raw_displaced = total_obj.get("forcibly_displaced", 0)

            # Guard against bool/None from API (Invalid variable type bug)
            def _safe_num(v):
                return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

            total_refugees  = _safe_num(raw_refugees)
            total_displaced = _safe_num(raw_displaced)

            signals = [
                Signal(
                    source="UNHCR API",
                    category="HUMAN_HEALTH",
                    domain="refugees",
                    metric="total_refugees",
                    value=total_refugees,
                    delta=self._delta("unhcr_refugees", total_refugees),
                    timestamp=datetime.utcnow().isoformat(),
                    raw=total_obj,
                ),
                Signal(
                    source="UNHCR API",
                    category="HUMAN_HEALTH",
                    domain="refugees",
                    metric="total_forcibly_displaced",
                    value=total_displaced,
                    delta=self._delta("unhcr_displaced", total_displaced),
                    timestamp=datetime.utcnow().isoformat(),
                    raw=total_obj,
                ),
            ]
            _cache[cache_key] = (time.time(), signals)
            log.info(f"UNHCR: бежанци={total_refugees:,.0f}, разселени={total_displaced:,.0f}")
            return signals
        except Exception as e:
            log.warning(f"unhcr_refugees failed: {e}")
            return []

    async def _observe_world_bank(self) -> list[Signal]:
        """World Bank API — ключови глобални показатели."""
        cache_key = "world_bank_indicators"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < CACHE_TTL:
                return cd

        indicators = {
            "SP.POP.TOTL": ("world_population", "demography"),
            "SI.POV.DDAY": ("extreme_poverty_rate_pct", "inequality"),
            "SH.DYN.MORT": ("child_mortality_per_1000", "health"),
            "SH.H2O.SMDW.ZS": ("safe_water_access_pct", "health"),
        }

        signals = []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            for code, (metric, domain) in indicators.items():
                url = f"https://api.worldbank.org/v2/country/WLD/indicator/{code}"
                params = {"format": "json", "mrv": "1", "per_page": "1"}
                try:
                    async with s.get(url, params=params) as r:
                        data = await r.json(content_type=None)
                    records = data[1] if isinstance(data, list) and len(data) > 1 else []
                    for rec in records:
                        val = rec.get("value")
                        if val is None:
                            continue
                        signals.append(Signal(
                            source="World Bank API",
                            category="HUMAN_HEALTH",
                            domain=domain,
                            metric=metric,
                            value=float(val),
                            delta=self._delta(f"wb_{code}", float(val)),
                            timestamp=datetime.utcnow().isoformat(),
                            raw={"indicator": code, "year": rec.get("date"), "value": val},
                        ))
                except Exception as e:
                    log.warning(f"world_bank {code} failed: {e}")

        _cache[cache_key] = (time.time(), signals)
        log.info(f"World Bank: {len(signals)} индикатора")
        return signals

    async def _observe_fews_famine(self) -> list[Signal]:
        """FEWS NET RSS — предупреждения за глад."""
        import aiohttp
        import re
        from datetime import datetime

        url = "https://fews.net/rss.xml"
        fallback_url = "https://reliefweb.int/updates/rss.xml?primary_country=0&source=1275"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                    else:
                        async with session.get(fallback_url, timeout=10) as fallback_resp:
                            text = await fallback_resp.text()
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", text)[1:6]
            signals = [
                Signal(
                    source="FEWS NET",
                    category="HUMAN_HEALTH",
                    domain="famine",
                    metric="famine_alert",
                    value=title.strip(),
                    delta=None,
                    timestamp=datetime.utcnow().isoformat(),
                    raw={"title": title.strip()},
                )
                for title in titles if title.strip()
            ]
            log.info(f"FEWS NET: {len(signals)} предупреждения")
            return signals
        except Exception as e:
            log.warning(f"fews_famine failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # ПРОГРЕС
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_arxiv(self) -> list[Signal]:
        """arXiv API — нови публикации по AI, енергетика, медицина."""
        categories = {
            "cs.AI": ("artificial_intelligence", "ai"),
            "eess.SY": ("energy_systems", "energy"),
            "q-bio.QM": ("quantitative_biology", "medicine"),
        }
        signals = []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            for cat, (label, domain) in categories.items():
                url = "http://export.arxiv.org/api/query"
                params = {
                    "search_query": f"cat:{cat}",
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": 3,
                }
                try:
                    async with s.get(url, params=params) as r:
                        text = await r.text(encoding="latin-1")
                    titles = re.findall(r"<title>(.*?)</title>", text, re.DOTALL)
                    # Пропусни първото — то е заглавието на feed-а
                    for title in titles[1:4]:
                        clean = re.sub(r"\s+", " ", title).strip()
                        signals.append(Signal(
                            source="arXiv API",
                            category="PROGRESS",
                            domain=domain,
                            metric=f"arxiv_{label}_paper",
                            value=clean,
                            delta=None,
                            timestamp=datetime.utcnow().isoformat(),
                            raw={"category": cat, "title": clean},
                        ))
                except Exception as e:
                    log.warning(f"arxiv {cat} failed: {e}")

        log.info(f"arXiv: {len(signals)} публикации")
        return signals

    async def _observe_github_trending(self) -> list[Signal]:
        """GitHub Trending — само AI/climate репозитории."""
        url = "https://github.com/trending"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as s:
                async with s.get(url) as r:
                    text = await r.text(encoding="latin-1")

            repos = re.findall(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)"', text)
            skip = {"sponsors", "apps", "trending", "about", "features", "pricing", "anthropics", "orgs", "settings"}
            repos = [r for r in repos if r.split("/")[0] not in skip]
            unique = list(dict.fromkeys(repos))

            # Приоритизирай AI/climate
            priority_keywords = ["ai", "llm", "climate", "energy", "solar", "model",
                                  "ml", "neural", "carbon", "bio", "med"]
            priority = [r for r in unique if any(k in r.lower() for k in priority_keywords)]
            selected = (priority + [r for r in unique if r not in priority])[:5]

            signals = [
                Signal(
                    source="GitHub Trending",
                    category="PROGRESS",
                    domain="technology",
                    metric="trending_repo",
                    value=repo,
                    delta=None,
                    timestamp=datetime.utcnow().isoformat(),
                    raw={"repo": repo},
                )
                for repo in selected
            ]
            log.info(f"GitHub: {len(signals)} репозитории")
            return signals
        except Exception as e:
            log.warning(f"github_trending failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # ЗДРАВЕ НА ЗЕМЯТА
    # ─────────────────────────────────────────────────────────────────────────

    async def _observe_noaa_co2(self) -> list[Signal]:
        """NOAA GML — CO₂ ppm от Mauna Loa (последни измервания)."""
        cache_key = "noaa_co2"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < CACHE_TTL:
                return cd

        # NOAA публичен CSV с последни sedmichni измервания
        url = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.get(url) as r:
                    text = await r.text(encoding="latin-1")

            lines = [l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()]
            # Последния ред е най-новото измерване — филтрирай невалидни (-999.99) и нечислови редове
            def _valid_co2(l):
                try: return float(l.split(",")[4].strip()) > 0
                except: return False
            lines = [l for l in lines if _valid_co2(l)]
            last = lines[-1].split(",")
            # Колони: year,month,day,decimal_date,co2_ppm,...
            year, month, day = last[0].strip(), last[1].strip(), last[2].strip()
            co2_ppm = float(last[4].strip())

            signals = [Signal(
                source="NOAA Mauna Loa",
                category="EARTH_HEALTH",
                domain="atmosphere",
                metric="co2_ppm",
                value=co2_ppm,
                delta=self._delta("noaa_co2_ppm", co2_ppm),
                timestamp=f"{year}-{int(month):02d}-{int(day):02d}",
                raw={"year": year, "month": month, "day": day, "co2_ppm": co2_ppm},
            )]

            _cache[cache_key] = (time.time(), signals)
            log.info(f"NOAA CO₂: {co2_ppm} ppm")
            return signals
        except Exception as e:
            log.warning(f"noaa_co2 failed: {e}")
            return _cache.get(cache_key, (None, []))[1]

    async def _observe_solar_activity(self) -> list[Signal]:
        """NOAA SWPC — слънчева активност (геомагнитна буря / X-ray flux)."""
        cache_key = "solar_activity"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < 900:  # 15 мин кеш
                return cd

        url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(url) as r:
                    data = await r.json(content_type=None)

            # API връща или [[timestamp, kp], ...] или [{"time_tag":..., "Kp":...}, ...]
            recent = data[-3:] if len(data) >= 3 else data
            signals = []
            for row in recent:
                if isinstance(row, dict):
                    ts_val = row.get("time_tag", "")
                    kp_raw = row.get("Kp")
                else:
                    ts_val = row[0]
                    kp_raw = row[1]
                kp = float(kp_raw) if kp_raw not in (None, "") else None
                if kp is None:
                    continue
                storm_level = (
                    "G0-quiet" if kp < 5 else
                    f"G{min(int(kp - 4), 5)}-storm"
                )
                signals.append(Signal(
                    source="NOAA SWPC",
                    category="EARTH_HEALTH",
                    domain="solar",
                    metric="kp_index",
                    value=kp,
                    delta=self._delta("kp_index", kp),
                    timestamp=str(ts_val),
                    raw={"timestamp": ts_val, "kp": kp, "storm_level": storm_level},
                ))

            _cache[cache_key] = (time.time(), signals)
            log.info(f"Solar: Kp={signals[-1].value if signals else 'N/A'}")
            return signals
        except Exception as e:
            log.warning(f"solar_activity failed: {e}")
            return _cache.get(cache_key, (None, []))[1]

    async def _observe_gbif_occurrences(self) -> list[Signal]:
        """GBIF API — брой записани биологични видове наблюдения (прокси за биоразнообразие)."""
        cache_key = "gbif_occurrences"
        if cache_key in _cache:
            ct, cd = _cache[cache_key]
            if time.time() - ct < CACHE_TTL:
                return cd

        url = "https://api.gbif.org/v1/occurrence/search"
        # Брой записи от последния месец като прокси за активност на наблюдения
        from datetime import timedelta
        month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        today = datetime.utcnow().strftime("%Y-%m-%d")
        params = {
            "eventDate": f"{month_ago},{today}",
            "limit": 0,  # Само count
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(url, params=params) as r:
                    data = await r.json(content_type=None)

            count = data.get("count", 0)
            signals = [Signal(
                source="GBIF API",
                category="EARTH_HEALTH",
                domain="biodiversity",
                metric="species_observations_30d",
                value=count,
                delta=self._delta("gbif_count", float(count)),
                timestamp=datetime.utcnow().isoformat(),
                raw={"count": count, "period": f"{month_ago}/{today}"},
            )]
            _cache[cache_key] = (time.time(), signals)
            log.info(f"GBIF: {count:,} наблюдения (30 дни)")
            return signals
        except Exception as e:
            log.warning(f"gbif_occurrences failed: {e}")
            return _cache.get(cache_key, (None, []))[1]

    # ── utilities ────────────────────────────────────────────────────────────

    def to_dict(self, signals: list[Signal]) -> list[dict]:
        return [asdict(s) for s in signals]

    def summary(self, signals: list[Signal]) -> dict:
        """Кратко резюме по категории за логване/репортиране."""
        by_cat: dict[str, list] = {}
        for s in signals:
            by_cat.setdefault(s.category, []).append(s)
        return {
            cat: {
                "count": len(items),
                "metrics": [f"{s.metric}={s.value}" for s in items[:3]],
            }
            for cat, items in by_cat.items()
        }


# ── standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    async def main():
        observer = SelfObserver()
        signals = await observer.observe()
        print(f"\n{'='*60}")
        print(f"TOTAL SIGNALS: {len(signals)}")
        print(f"{'='*60}")
        summary = observer.summary(signals)
        for cat, info in summary.items():
            print(f"\n[{cat}] — {info['count']} сигнала")
            for m in info["metrics"]:
                print(f"  • {m}")

    asyncio.run(main())
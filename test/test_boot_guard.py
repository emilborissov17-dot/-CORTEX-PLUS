#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_boot_guard.py — ПАЗАЧЪТ СЕ ПУСКА, НЕ СЕ ЧЕТЕ.

ПОВОДЪТ (16 август 2026, измерено, не предположено)
---------------------------------------------------
В нощта на 16 август цикълът тръгна ТРИ ПЪТИ и три пъти се самоуби:

    03:04:02  BOOT ABORT: вече тече цикъл 03:04:02.435030 (pid 59108, жив)
    03:14:02  BOOT ABORT: ... (pid 72992, жив)
    03:24:02  BOOT ABORT: ... (pid 86528, жив)

И трите лога са по 398 байта. Нула цикъла, нула данни, цяло денонощие мълчание.

Причината: `venv\\Scripts\\python.exe` е ЛАУНЧЕР. Измерено на машината два пъти:

    Popen.pid = 85400 | child os.getpid() = 97752  -> MISMATCH
    Popen.pid = 92624 | child 94152, psutil НЕ намира жив родител

Супервайзорът записва в ключалката pid-а, който Popen му е върнал — пид на стъпка,
която умира веднага. Цикълът чете тази ключалка, вижда СВОЯ cycle_id, но ЧУЖД pid,
и се самоубива. Всеки път. Детерминистично.

ЗАЩО ТОЗИ ТЕСТ, А НЕ ОЩЕ ЕДНА AST ПРОВЕРКА
-------------------------------------------
Пазач, който при неопределеност избира смърт, изглежда безупречно в кода. Той се
чете като предпазливост. Единственият начин да разбереш какво прави е ДА ГО ПУСНЕШ
срещу случаите, които ще срещне в 03:00 без свидетели.

    Kimi, 16 август: „При система без надзор fail-deadly е по-лошо от fail-unsafe.
    Ако не си сигурен дали да спреш, продължи с ясен запис на неопределеността.
    Смъртта е необратима; логът може да се поправи на сутринта."

Затова тестът проверява ПОВЕДЕНИЕ, не форма: вика истинския `_classify_cycle_id`
върху истински ключалки във временна папка и гледа кога вдига SystemExit.

    venv\\Scripts\\python.exe test\\test_boot_guard.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import fast_cycle_runner as R          # noqa: E402  (само 2 реда на ниво модул)


def _iso(delta_sec: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_sec)).isoformat()


def _sandbox(tmp: Path) -> None:
    """Пренасочва ВСИЧКИ пътища, които boot-ът пипа, към временна папка.
    Тестът не бива да докосва живата памет на системата."""
    R.LOCK_PATH = tmp / "cycle.lock"
    R.LAST_CYCLE_ID = tmp / "last_cycle_id.txt"
    R.LAST_ATTEMPT = tmp / "last_attempt.txt"
    R.CYCLE_ORIGIN = tmp / "cycle_origin.json"
    # нощният дневник също е файл — да не пише в истинския
    R.BASE = tmp


def _write_lock(tmp: Path, cycle_id: str, pid: int) -> None:
    (tmp / "cycle.lock").write_text(json.dumps(
        {"pid": pid, "cycle_id": cycle_id, "started_utc": _iso()},
        ensure_ascii=False), encoding="utf-8")


def _run(env_id: str) -> tuple:
    """(изход, код). 'ok' = пуснат; 'abort:N' = SystemExit N."""
    try:
        cid = R._classify_cycle_id(env_id)
        return "ok", cid
    except SystemExit as e:
        return f"abort:{e.code}", None


def main() -> int:
    fails = []

    def check(name: str, got: str, want: str, why: str):
        ok = got.startswith(want)
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name}\n"
              f"         очаквано: {want:<8} получено: {got}\n"
              f"         защо е важно: {why}")
        if not ok:
            fails.append(name)

    # ── 1. НОЩТА НА 16 АВГУСТ: своя ключалка с чужд (launcher) pid ──────────
    # Това е случаят, който уби системата три пъти. Ако този тест падне,
    # значи сме върнали дефекта.
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        cid = _iso()
        _write_lock(tmp, cid, os.getpid() + 1)   # жив, но НЕ моят pid
        got, _ = _run(cid)
        check("своя ключалка + чужд жив pid (launcher)", got, "ok",
              "точно това уби цикъла на 16 август; трябва да ПРОДЪЛЖИ")

    # ── 2. ИСТИНСКО ЗАСТЪПВАНЕ: друг cycle_id, жив ЧУЖД pid ────────────────
    # ВНИМАНИЕ към бъдещия читател: тук НЕ бива да се слага os.getpid().
    # Първата версия на този тест го направи и случаят мина за „ok", защото
    # пазачът правилно позна pid-а за СВОЙ. Тестът щеше да обяви дупка, каквато
    # няма — а по-лошото: щеше да ме подмами да „поправя" здрав код.
    # Нужен е pid, който е ЖИВ и НЕ Е наш: родителският процес върши работа.
    foreign_pid = os.getppid()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        _write_lock(tmp, _iso(-600), foreign_pid)
        got, _ = _run(_iso())
        check("ЧУЖД цикъл, жив", got, "abort:3",
              "два цикъла върху едни файлове наистина са по-лошо от един")

    # ── 3. МЪРТВА чужда ключалка ───────────────────────────────────────────
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        _write_lock(tmp, _iso(-3600), 999_999)      # pid, който не съществува
        got, _ = _run(_iso())
        check("чужда МЪРТВА ключалка", got, "ok",
              "умрял вчерашен цикъл не бива да блокира днешния")

    # ── 4. НЕЧЕТИМА ключалка ───────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        (tmp / "cycle.lock").write_text("{счупен json", encoding="utf-8")
        got, _ = _run(_iso())
        check("нечетима ключалка", got, "ok",
              "повредата е неопределеност, а неопределеността не е повод за смърт")

    # ── 5. БЕЗ ключалка ────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        got, _ = _run(_iso())
        check("няма ключалка", got, "ok", "нормалният старт")

    # ── 6. STALE cycle_id — тук смъртта Е правилна ─────────────────────────
    # Този случай НЕ се разхлабва: цикъл с id по-стар от последния запечатан
    # би се представил за жив, докато е мъртъв. Тук ABORT е верният избор,
    # защото алтернативата е ЛЪЖА, не липса.
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        (tmp / "last_cycle_id.txt").write_text(_iso(), encoding="utf-8")
        got, _ = _run(_iso(-600))
        check("stale cycle_id (по-стар от запечатания)", got, "abort:2",
              "тук ABORT е правилен: алтернативата е цикъл, който лъже, че е жив")

    # ── 7. cycle_id от БЪДЕЩЕТО ────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d); _sandbox(tmp)
        got, _ = _run(_iso(3600))
        check("cycle_id от бъдещето (часовников скок)", got, "abort:2",
              "бъдещ id трови всяко следващо сравнение по време")

    print()
    if fails:
        print(f"FAIL: {len(fails)} случая се държат грешно: {', '.join(fails)}")
        print("Пазачът трябва да ПРЕКЪСВА само при ЯСЕН чужд цикъл или при "
              "цикъл, който би излъгал, че е жив. Всичко неясно -> запиши и "
              "продължи.")
        return 1
    print("OK: пазачът прекъсва при ясна опасност и оцелява при неопределеност "
          f"({7 - len(fails)}/7 случая)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

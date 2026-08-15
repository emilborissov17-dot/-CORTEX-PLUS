КОДЪТ ДОСЛОВНО (част 2 от 2) — сърцевината: съпоставката.

--- core/metta_check.py, функция compare (дословно) ---
def compare(step: str, prev_step: str | None, brain_says: dict | None,
            since_ts: float | None = None) -> dict:
    """Слага мнението на мозъка до извода от фактите и записва РАЗМИНАВАНЕТО.

    Мозъкът твърди `prev_ok` за предишната стъпка. Таблицата знае какъв файл е
    обещала тя. Ако мозъкът казва „добре", а файлът не е пипнат — това е точно
    невидимият досега случай, и тук получава ред в дневника."""
    v = verdict(step, since_ts)
    rec = {"ts": _now(), "step": step, "facts": v}
    if prev_step:
        try:
            from core import cycle_map as cm
            if since_ts is None:
                try:
                    hb = json.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
                    since_ts = datetime.fromisoformat(hb["cycle_id"]).timestamp()
                except Exception:
                    since_ts = datetime.now(timezone.utc).timestamp() - 86400
            kept, detail = cm.kept_promise(prev_step, since_ts)
            rec["prev_step"] = prev_step
            rec["prev_promise"] = kept
            rec["prev_detail"] = detail[:120]
            if brain_says is not None:
                said_ok = str(brain_says.get("prev_ok")).lower() in ("true", "1", "yes")
                rec["brain_prev_ok"] = said_ok
                rec["brain_note"] = str(brain_says.get("prev_note", ""))[:200]
                if said_ok and kept == "НЕ ПИПНА":
                    rec["divergence"] = (f"мозъкът каза, че {prev_step} е минала добре, "
                                         f"а обещаният ѝ файл не е пипнат")
                elif (not said_ok) and kept == "ОБНОВИ":
                    rec["divergence"] = (f"мозъкът се усъмни в {prev_step}, а тя "
                                         f"е обновила обещаното")
        except Exception:
            pass

    if rec.get("divergence") or v.get("needs_missing"):
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            if LOG.exists() and LOG.stat().st_size > 5_000_000:
                LOG.replace(LOG.with_suffix(".jsonl.1"))
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return rec

Макс 5 реда, по номера:
1) Има ли начин мозъкът да се научи да твърди така, че divergence никога да не се
   задейства (напр. никога да не казва prev_ok=true)? Как се лови това?
2) Записва се само при divergence ИЛИ липсващ вход. Съгласието не се записва —
   значи не можем да измерим точността на мозъка в проценти. Грешка ли е?
3) СТЪПКА 2 от 53 — brain_briefing (планът за деня). Сега е втора: pulse ->
   brain_briefing -> body_scan. Моята позиция: планът се пише СЛЯП ЗА ТЯЛОТО.
   Нов ред: pulse -> body_scan -> human_approvals -> brain_briefing. Съгласен ли си,
   или има причина планът да предхожда тялото и човешката дума?

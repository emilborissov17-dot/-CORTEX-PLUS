ДОСЛОВЕН КОД (1 от 2). Дупка, хваната преди да ти я дам: цикълът върви с venv, а
hyperon е само в venv312_metta — слоят щеше да е МЪЛЧАЛИВО мъртъв на 53 стъпки, а
нула разминавания изглежда като „няма разминавания". Поправката, дословно:

def _consumers_via_subprocess(since_ts: float) -> tuple:
    """Пуска същото изчисление в venv312_metta и връща изводa му."""
    py = _metta_python()
    if not py:
        raise RuntimeError("venv312_metta липсва — няма къде да живее MeTTa")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(BASE))
    r = subprocess.run([str(py), "-m", "core.metta_check", "--export", str(since_ts)],
                       cwd=str(BASE), env=env, capture_output=True, timeout=180)
    txt = r.stdout.decode("utf-8", "replace")
    i = txt.find("{")
    if r.returncode != 0 or i < 0:
        raise RuntimeError(f"exit={r.returncode} {r.stderr.decode('utf-8','replace')[-200:]}")
    d = json.loads(txt[i:])
    return (d["consumers"],
            {k: set(v) for k, v in d["prod"].items()},
            d["req"], d["order"])

def _note_absence(why: str) -> None:
    """MeTTa не е на линия. Това се ЧУВА, а не се преглъща: слой, който мълчи,
    иначе изглежда като слой, който не намира разминавания."""
    global _NOTED
    if _NOTED:
        return
    _NOTED = True
    for path in (NIGHT, LOG):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": _now(), "subject": "MeTTa НЕ Е НА ЛИНИЯ",
                                     "detail": why, "engine": None,
                                     "consequence": "второто мнение отсъства този цикъл — "
                                                    "нула разминавания НЕ значи съгласие"},
                                    ensure_ascii=False) + "\n")
        except Exception:
            pass

def _build(since_ts: float) -> bool:
    """Строи веднъж на процес. True, ако MeTTa е проговорила."""
    global _CONSUMERS, _ORDER, _PROD, _REQ, _ENGINE
    if _CONSUMERS is not None:
        return _ENGINE is not None
    tried = []
    for name, fn in (("hyperon/MeTTa (in-process)", _consumers_via_hyperon),
                     ("hyperon/MeTTa (venv312_metta)", _consumers_via_subprocess)):
        try:
            cons, prod, req, order = fn(since_ts)
            _CONSUMERS, _PROD, _REQ, _ORDER, _ENGINE = cons, prod, req, order, name
            return True
        except Exception as e:
            tried.append(f"{name}: {type(e).__name__}: {e}")
    # Дори без MeTTa таблицата и скенерът работят — но това НЕ е второ мнение и
    # тук се казва точно така.
    try:
        from core.cycle_graph import _atoms
        _program, prod, req, order, _fresh = _atoms(since_ts)
        _PROD, _REQ, _ORDER = prod, req, order
    except Exception as e:
        tried.append(f"atoms: {type(e).__name__}: {e}")
    _CONSUMERS, _ENGINE = {}, None
    _note_absence(" | ".join(tried)[:400])
    return False

Мерено: 0.095 s строене, 0.0001 s кеш.

Макс 5 реда:
1) Графът се строи в началото, цикълът пише файлове после — къде лъже кешът?
2) Стига ли мълчанието да се ОБЯВИ, или липсата на свидетел трябва да СПИРА нещо?
3) Независим свидетел ли е, или прикрит втори мозък?

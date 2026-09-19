# -*- coding: utf-8 -*-
"""
test/test_consult_free_only.py — консултът е БЕЗПЛАТЕН и НЕЗАВИСИМ, или го няма.

Защо съществува (10 септ. 2026): безплатният Kimi изчезна от OpenRouter (HTTP 404
„This model is unavailable for free"), и роустърът на consult.py остана с нула живи
опонента. Докато го оправяхме, два провала станаха възможни и двата са точно
пороците, които този проект лови:

  ПОРОК 1 (полезност на всяка цена): да се мине тихо на ПЛАТЕНИЯ Kimi, защото
  „нали трябва консулт". Емил, 15 авг: „НЕ ПОЛЗВАМЕ ПЛАТЕНИТЕ МУ ВЕРСИИ."
  УСПЕХ БЕЗ ИЗХОД: ако всички безплатни откажат, правилният резултат е
  ok=False и файл, който казва „консултът НЕ се състоя" — НЕ отговор.

  ПОРОК 2 (пътят на най-малкото съпротивление): чужд безплатен модел да бъде
  цитиран като „Kimi каза", защото файлът се казва kimi_duel/consults/*.

ЗАБРАНЕНИЯТ FALLBACK: платен слъг в роустъра; приемане на отговор, обслужен от
не-:free модел; ok=True при нула отговорили.

Тестовете са структурни (гледат поведение и идентификатори, не проза) и всеки
МУТАЦИОНЕН тест пада, ако пазачът, който описва, бъде махнат.
"""
from __future__ import annotations

import json
import sys
import pytest
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from experiments.kimi_duel import consult  # noqa: E402


@pytest.fixture(autouse=True)
def _consult_provenance_to_tmp(tmp_path, monkeypatch):
    """Refusals are RECORDED, and a test must not record into the live file.

    consult._record_refusal appends to memory/llm_provenance.jsonl. The suite's
    _no_live_writes fixture fails any test that writes there, correctly, so every
    test in this module gets its own copy and can still assert the row.
    """
    monkeypatch.setattr(consult, "PROVENANCE", tmp_path / "llm_provenance.jsonl")


class _Resp:
    """Минимален двойник на requests.Response."""

    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _served(model_id, text="мнение"):
    return {"model": model_id, "choices": [{"message": {"content": text}}],
            "usage": {"total_tokens": 10}}


class RosterIsFreeOnly(unittest.TestCase):
    def test_every_slug_in_the_roster_is_free(self):
        self.assertTrue(consult.OPPONENTS, "роустърът е празен — нула опонента")
        for slug in consult.OPPONENTS:
            self.assertTrue(slug.endswith(":free"),
                            f"{slug} не е :free — платен слъг в роустъра")

    def test_kimi_is_still_tried_first(self):
        # Нормата назовава Kimi. Чуждите модели са РЕЗЕРВА, не замяна: ако
        # Moonshot пусне отново безплатен вариант, той трябва да се вика пръв.
        self.assertEqual(consult.OPPONENTS[:len(consult.KIMI_FREE)],
                         consult.KIMI_FREE)

    def test_the_roster_has_a_live_fallback_beyond_kimi(self):
        self.assertTrue(len(consult.OPPONENTS) > len(consult.KIMI_FREE),
                        "само мъртвите Kimi слъгове — консулт е невъзможен")


class PaidSubstitutionIsRefused(unittest.TestCase):
    """МУТАЦИОНЕН: махни проверката в който и да е от ТРИТЕ пътя и това пада.

    19 септ. 2026 — ОБНОВЕН ЗА ТРЕТИЯ ПЪТ. Когато този клас беше написан, пътищата
    бяха два: Groq, после роустърът. На 11 септ. _ask_nvidia_kimi беше добавен
    НАД тях и се пробва ПРЪВ — без никакъв пазач. Затова:

      * заявките вече са NVIDIA + Groq + всички слъгове, не Groq + слъгове;
      * calls[0] е моделът на NVIDIA, не GROQ_KIMI;
      * платеният двойник вече НЕ Е moonshotai/kimi-k2.6. Прочетено от живия
        NIM каталог на 19 септ.: акаунтът сервира moonshotai/kimi-k3 и
        moonshotai/kimi-k2.6 на безплатния developer tier. Същият слъг е ПЛАТЕН
        в OpenRouter и БЕЗПЛАТЕН тук — затова свободата се декларира ПО ПЪТ, а
        един и същ модел не може да служи за „платения" навсякъде.
    """

    PAID = "moonshotai/kimi-k2-0711-preview"   # в ничия декларация, никъде :free

    def test_a_paid_model_serving_the_request_is_not_an_answer(self):
        calls = []

        def fake_post(url, **kw):
            calls.append(kw["json"]["model"])
            # Всеки endpoint приема заявката, но я обслужва с ПЛАТЕН вариант.
            return _Resp(200, _served(self.PAID))

        res = self._run_with(fake_post)
        self.assertFalse(res["ok"],
                         "отговор от платен модел беше приет — пазачът го няма")
        self.assertEqual(res["backend"], "none")
        self.assertTrue(any("НЕ е безплатният" in t or "nothing declares" in t
                            for t in res["tried"]),
                        f"причината не е записана: {res['tried']}")
        # ТРИТЕ ПЪТЯ, всеки отказал поотделно.
        self.assertEqual(len(calls), len(consult.OPPONENTS) + 2,
                         f"не всички пътища са пробвани: {calls}")
        self.assertEqual(calls[0], self.NVIDIA_MODEL,
                         "NVIDIA трябва да е ПЪРВИЯТ опит")
        self.assertEqual(calls[1], consult.GROQ_KIMI,
                         "Groq трябва да е ВТОРИЯТ опит")
        self.assertTrue(any("GROQ_FREE_MODELS" in t for t in res["tried"]),
                        f"Groq пътят не е отказал по декларация: {res['tried']}")
        self.assertTrue(any(t.startswith("nvidia:") for t in res["tried"]),
                        f"NVIDIA пътят не е отказал: {res['tried']}")

    def test_a_free_model_serving_the_request_is_an_answer(self):
        # Негативен контрол: пазачът не трябва да блокира ЛЕГИТИМЕН безплатен
        # отговор — иначе „всичко е отказано" щеше да минава за коректност.
        free = consult.OPPONENTS[-1]

        def fake_post(url, **kw):
            return _Resp(200, _served(free, "ето къде грешиш"))

        res = self._run_with(fake_post)
        self.assertTrue(res["ok"], res)
        # Етикетът се гради ВЕДНЪЖ: преди поправката това беше
        # 'nvidia:nvidia/nemotron-...', защото served вече започва с 'nvidia/'.
        self.assertEqual(res["backend"], free)
        self.assertEqual(res["cost_usd"], 0.0)

    NVIDIA_MODEL = "moonshotai/kimi-k3"

    def _run_with(self, fake_post):
        import requests
        import core.groq_backend as gb
        real_post, real_model = requests.post, gb._nvidia_model
        requests.post = fake_post
        # ХЕРМЕТИЧНО: _nvidia_model прави истински GET към NIM и кешира в
        # глобална. Без този дубъл тестът зависи от мрежата и от реда, в който
        # тестовете са се изпълнили.
        gb._nvidia_model = lambda key: self.NVIDIA_MODEL
        try:
            return consult.ask_kimi("бриф", max_tokens=10)
        finally:
            requests.post, gb._nvidia_model = real_post, real_model


class ForeignOpponentIsNotLabelledKimi(unittest.TestCase):
    """МУТАЦИОНЕН: махни `note`/`is_kimi` и този тест пада."""

    def test_md_says_the_opponent_is_not_kimi(self):
        free = next(s for s in consult.FREE_INDEPENDENT)

        def fake_post(url, **kw):
            return _Resp(200, _served(free, "несъгласен съм по Б"))

        out = self._consult_with(fake_post, "2026-01-01_probe_foreign")
        md = Path(out).with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("НЕ Е KIMI", md,
                      "чужд опонент минава за Kimi — бележката липсва")
        self.assertIn(free, md, "кой е отговорил не се вижда в .md")

    def test_md_does_not_shout_when_kimi_itself_answers(self):
        # Негативен контрол: бележката е за ЧУЖД опонент. Ако я пише винаги,
        # тя става шум и спира да значи нещо.
        def fake_post(url, **kw):
            return _Resp(200, _served(consult.KIMI_FREE[0], "съгласен, но..."))

        out = self._consult_with(fake_post, "2026-01-01_probe_kimi")
        md = Path(out).with_suffix(".md").read_text(encoding="utf-8")
        self.assertNotIn("НЕ Е KIMI", md)

    def test_total_failure_is_not_written_as_an_answer(self):
        def fake_post(url, **kw):
            return _Resp(404, {"error": {"message": "unavailable for free"}})

        out = self._consult_with(fake_post, "2026-01-01_probe_dead")
        md = Path(out).with_suffix(".md").read_text(encoding="utf-8")
        self.assertIn("НЕ се е състоял", md)
        self.assertNotIn("## Отговор", md,
                         "провал, написан под заглавие 'Отговор'")
        self.assertFalse(json.loads(Path(out).read_text(encoding="utf-8"))
                         ["response"]["ok"])

    def _consult_with(self, fake_post, stem):
        import requests
        brief = BASE / "test" / f"{stem}.brief.md"
        brief.write_text("суров вход\n", encoding="utf-8")
        real = requests.post
        requests.post = fake_post
        try:
            out = consult.run(str(brief), max_tokens=10)
        finally:
            requests.post = real
            brief.unlink(missing_ok=True)
            self.addCleanup(Path(out).unlink, missing_ok=True)
            self.addCleanup(Path(out).with_suffix(".md").unlink, missing_ok=True)
        return out


if __name__ == "__main__":
    unittest.main(verbosity=2)

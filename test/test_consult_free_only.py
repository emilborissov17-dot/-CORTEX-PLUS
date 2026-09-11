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
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from experiments.kimi_duel import consult  # noqa: E402


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
    """МУТАЦИОНЕН: махни проверката `if ':free' not in served` и този тест пада."""

    def test_a_paid_model_serving_the_request_is_not_an_answer(self):
        calls = []

        def fake_post(url, **kw):
            calls.append(kw["json"]["model"])
            # OpenRouter приема заявката, но я обслужва с ПЛАТЕНИЯ вариант.
            return _Resp(200, _served("moonshotai/kimi-k2.6"))

        res = self._run_with(fake_post)
        self.assertFalse(res["ok"],
                         "отговор от платен модел беше приет — пазачът го няма")
        self.assertEqual(res["backend"], "none")
        self.assertTrue(any("НЕ е безплатният" in t for t in res["tried"]),
                        f"причината не е записана: {res['tried']}")
        self.assertEqual(len(calls), len(consult.OPPONENTS),
                         "не всички безплатни варианти са пробвани")

    def test_a_free_model_serving_the_request_is_an_answer(self):
        # Негативен контрол: пазачът не трябва да блокира ЛЕГИТИМЕН безплатен
        # отговор — иначе „всичко е отказано" щеше да минава за коректност.
        free = consult.OPPONENTS[-1]

        def fake_post(url, **kw):
            return _Resp(200, _served(free, "ето къде грешиш"))

        res = self._run_with(fake_post)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["backend"], free)
        self.assertEqual(res["cost_usd"], 0.0)

    def _run_with(self, fake_post):
        import requests
        real = requests.post
        requests.post = fake_post
        try:
            return consult.ask_kimi("бриф", max_tokens=10)
        finally:
            requests.post = real


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

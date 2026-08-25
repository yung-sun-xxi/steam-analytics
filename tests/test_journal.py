"""The answer/feedback log. Writes into a temp dir, never into data/."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


PICKS = [{"appid": 294100, "name": "RimWorld", "role": "прямое попадание", "why": "..."}]


class Roundtrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def answer(self, mood="хочу подумать", picks=None):
        path = os.path.join(self.dir, "picks.json")
        with open(path, "w") as f:
            json.dump(picks if picks is not None else PICKS, f)
        with contextlib.redirect_stdout(io.StringIO()):
            journal.cmd_answer(Args(outdir=self.dir, mood=mood, tags="strategy",
                                    candidates=None, picks=path))

    def test_answer_is_appended_as_one_json_line(self):
        self.answer()
        with open(os.path.join(self.dir, "journal.jsonl")) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["kind"], "answer")
        self.assertEqual(rec["mood_tags"], ["strategy"])
        self.assertEqual(rec["picks"], PICKS)

    def test_non_ascii_survives(self):
        self.answer()
        rec = journal.read(self.dir)[0]
        self.assertEqual(rec["picks"][0]["role"], "прямое попадание")

    def test_feedback_attaches_to_the_last_answer(self):
        self.answer(mood="первое")
        self.answer(mood="второе")
        with contextlib.redirect_stdout(io.StringIO()):
            journal.cmd_feedback(Args(outdir=self.dir, text="зашло", appid=294100,
                                      answer=None))
        records = journal.read(self.dir)
        answers = [r for r in records if r["kind"] == "answer"]
        self.assertEqual(records[-1]["about_answer"], answers[-1]["id"])
        self.assertEqual(records[-1]["appid"], 294100)

    def test_feedback_without_any_answer_still_records(self):
        with contextlib.redirect_stdout(io.StringIO()):
            journal.cmd_feedback(Args(outdir=self.dir, text="просто мысль", appid=None,
                                      answer=None))
        rec = journal.read(self.dir)[0]
        self.assertIsNone(rec["about_answer"])
        self.assertEqual(rec["text"], "просто мысль")

    def test_nothing_is_overwritten(self):
        self.answer()
        self.answer()
        self.assertEqual(len(journal.read(self.dir)), 2)

    def test_two_answers_in_one_second_get_distinct_ids(self):
        self.answer()
        self.answer()
        ids = [r["id"] for r in journal.read(self.dir)]
        self.assertEqual(len(set(ids)), 2)

    def test_reading_a_missing_journal_is_empty_not_an_error(self):
        self.assertEqual(journal.read(os.path.join(self.dir, "nope")), [])

    def test_corrupt_line_is_skipped(self):
        self.answer()
        with open(os.path.join(self.dir, "journal.jsonl"), "a") as f:
            f.write("{not json\n")
        self.assertEqual(len(journal.read(self.dir)), 1)


if __name__ == "__main__":
    unittest.main()

"""Games played outside Steam: records, model-written tags, and the merge. No network."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import manual_games
import taste

TAGDICT = [{"tagid": 699, "name": "Racing"},
           {"tagid": 3859, "name": "Multiplayer"},
           {"tagid": 1773, "name": "Arcade"}]


class Args:
    def __init__(self, **kw):
        for k, v in dict(outdir=None, cc="es", name=None, hours=1.0, year=None,
                         last="2020", appid=None, tags=None, platform=None,
                         note=None).items():
            kw.setdefault(k, v)
        self.__dict__.update(kw)


class LastPlayed(unittest.TestCase):
    def test_a_year_becomes_its_middle(self):
        """Anchoring at January would systematically overstate how long ago it was."""
        self.assertTrue(manual_games.played_at(2018).startswith("2018-07-01"))

    def test_a_month_becomes_its_middle(self):
        self.assertTrue(manual_games.played_at(2026, 2).startswith("2026-02-15"))

    def test_both_precisions_are_accepted(self):
        self.assertEqual(manual_games.parse_last_played("2018"), (2018, None))
        self.assertEqual(manual_games.parse_last_played("2026-02"), (2026, 2))
        self.assertEqual(manual_games.parse_last_played(" 2026-2 "), (2026, 2))

    def test_a_month_is_worth_about_a_tenth_of_the_weight(self):
        """Which is why a year is enough to ask for and a month is only a bonus."""
        now = datetime(2026, 8, 25, tzinfo=timezone.utc).timestamp()
        g = lambda iso: taste.game_weight({"playtime_forever_min": 18000,
                                           "last_played": iso}, now)
        february = g(manual_games.played_at(2026, 2))
        midyear = g(manual_games.played_at(2026))
        self.assertLess(february, midyear)
        self.assertGreater(february / midyear, 0.9)

    def test_day_precision_is_refused(self):
        with self.assertRaises(SystemExit):
            manual_games.parse_last_played("2026-02-14")

    def test_nonsense_and_impossible_dates_are_refused(self):
        for bad in ("вчера", "1970", "3000", "2026-13"):
            with self.assertRaises(SystemExit, msg=bad):
                manual_games.parse_last_played(bad)

    def test_a_future_month_in_the_current_year_is_refused(self):
        future = datetime.now(timezone.utc)
        if future.month < 12:
            with self.assertRaises(SystemExit):
                manual_games.parse_last_played(f"{future.year}-12")

    def test_it_parses_back_into_the_weight_formula(self):
        now = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
        w = taste.game_weight({"playtime_forever_min": 6000,
                               "last_played": manual_games.played_at(2020)}, now)
        self.assertAlmostEqual(w, 10.0 * 0.5 ** 2, places=2)


class ModelTags(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "cache"))
        with open(os.path.join(self.dir, "cache", "tagdict.json"), "w") as f:
            json.dump(TAGDICT, f)

    def test_counts_fall_with_rank(self):
        tags = manual_games.model_tags(["Racing", "Multiplayer", "Arcade"], self.dir)
        counts = [t["count"] for t in tags]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(counts[0], manual_games.MODEL_TAG_TOP)

    def test_names_resolve_to_real_tagids(self):
        tags = manual_games.model_tags(["racing"], self.dir)
        self.assertEqual(tags[0]["tagid"], 699)
        self.assertEqual(tags[0]["name"], "Racing")

    def test_an_invented_tag_is_refused(self):
        """A made-up tag would sit outside the vector space and silently do nothing."""
        with self.assertRaises(SystemExit):
            manual_games.model_tags(["Racing", "Definitely Not A Tag"], self.dir)


class Records(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "cache"))
        with open(os.path.join(self.dir, "cache", "tagdict.json"), "w") as f:
            json.dump(TAGDICT, f)
        stack = contextlib.ExitStack()
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.addCleanup(stack.close)

    def add(self, **kw):
        kw.setdefault("outdir", self.dir)
        kw.setdefault("tags", "Racing,Multiplayer")
        manual_games.cmd_add(Args(**kw))

    def test_month_precision_is_kept_on_the_record(self):
        self.add(name="Fortnite", hours=300, last="2026-02")
        g = manual_games.load(self.dir)[0]
        self.assertEqual((g["year"], g["month"], g["date_precision"]),
                         (2026, 2, "month"))

    def test_year_only_records_say_so(self):
        self.add(name="Halo", hours=40, last="2022")
        g = manual_games.load(self.dir)[0]
        self.assertIsNone(g["month"])
        self.assertEqual(g["date_precision"], "year")

    def test_a_date_is_required(self):
        with self.assertRaises(SystemExit):
            manual_games.cmd_add(Args(outdir=self.dir, name="X", hours=5,
                                      tags="Racing", last=None, year=None))

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(manual_games.load(self.dir), [])

    def test_a_record_keeps_what_the_vector_needs(self):
        self.add(name="Mario Kart 8", hours=200, last="2018", platform="switch")
        g = manual_games.load(self.dir)[0]
        self.assertEqual((g["name"], g["hours"], g["year"]), ("Mario Kart 8", 200.0, 2018))
        self.assertEqual(g["tags_source"], "model")
        self.assertIsNone(g["appid"])

    def test_the_same_game_twice_is_refused(self):
        self.add(name="Mario Kart 8", hours=200, last="2018")
        with self.assertRaises(SystemExit):
            self.add(name="mario kart 8", hours=10, last="2019")

    def test_appid_zero_is_refused(self):
        with self.assertRaises(SystemExit):
            self.add(name="X", hours=5, last="2020", appid=0)

    def test_zero_hours_is_refused(self):
        with self.assertRaises(SystemExit):
            self.add(name="X", hours=0, last="2020")

    def test_a_future_year_is_refused(self):
        with self.assertRaises(SystemExit):
            self.add(name="X", hours=5, last="3000")

    def test_neither_appid_nor_tags_is_refused(self):
        with self.assertRaises(SystemExit):
            manual_games.cmd_add(Args(outdir=self.dir, name="X", hours=5, last="2020",
                                      tags=None))

    def test_remove_by_name(self):
        self.add(name="Mario Kart 8", hours=200, last="2018")
        manual_games.cmd_remove(Args(outdir=self.dir, name="mario"))
        self.assertEqual(manual_games.load(self.dir), [])


class Merge(unittest.TestCase):
    def steam(self, appid, minutes, last):
        return {"appid": appid, "name": f"game{appid}",
                "playtime_forever_min": minutes, "last_played": last}

    def manual(self, appid, hours, iso, name="manual"):
        return {"appid": appid, "name": name, "hours": hours, "last_played": iso,
                "tags": [{"tagid": 699, "name": "Racing", "count": 1000}],
                "tags_source": "model"}

    def merge(self, games, manual):
        return taste.merge_manual(games, manual)

    def test_a_console_game_he_also_owns_adds_its_hours(self):
        games = [self.steam(1, 2880, "2024-01-01T00:00:00+00:00")]      # 48 h
        entries, merged = self.merge(games, [self.manual(1, 80, "2020-07-01T00:00:00+00:00")])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["hours"], 128.0)
        self.assertEqual(entries[0]["source"], "steam+manual")
        self.assertEqual(list(merged), [1])

    def test_the_more_recent_date_wins(self):
        games = [self.steam(1, 60, "2019-01-01T00:00:00+00:00")]
        entries, _ = self.merge(games, [self.manual(1, 10, "2023-07-01T00:00:00+00:00")])
        self.assertEqual(entries[0]["last_played"], "2023-07-01T00:00:00+00:00")

    def test_an_older_console_session_does_not_rewind_the_date(self):
        games = [self.steam(1, 60, "2025-01-01T00:00:00+00:00")]
        entries, _ = self.merge(games, [self.manual(1, 10, "2010-07-01T00:00:00+00:00")])
        self.assertEqual(entries[0]["last_played"], "2025-01-01T00:00:00+00:00")

    def test_a_game_not_on_steam_stands_alone_with_its_own_tags(self):
        entries, merged = self.merge([], [self.manual(None, 200, "2018-07-01T00:00:00+00:00",
                                                      name="Mario Kart 8")])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["name"], "Mario Kart 8")
        self.assertEqual(entries[0]["source"], "manual/model")
        self.assertEqual(entries[0]["tags"][0]["name"], "Racing")
        self.assertEqual(merged, {})

    def test_steam_only_games_are_untouched(self):
        games = [self.steam(1, 600, "2025-01-01T00:00:00+00:00")]
        entries, _ = self.merge(games, [])
        self.assertEqual(entries[0]["source"], "steam")
        self.assertEqual(entries[0]["hours"], 10.0)
        self.assertIsNone(entries[0]["tags"])


if __name__ == "__main__":
    unittest.main()

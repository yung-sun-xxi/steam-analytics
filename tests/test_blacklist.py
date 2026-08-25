"""The blacklist: storage, name resolution, and the drop rule. No network."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blacklist
import candidates


class Args:
    def __init__(self, **kw):
        kw.setdefault("outdir", None)
        kw.setdefault("cc", "es")
        kw.setdefault("appid", None)
        kw.setdefault("tagid", None)
        kw.setdefault("name", None)
        kw.setdefault("reason", None)
        kw.setdefault("first", False)
        self.__dict__.update(kw)


TAGDICT = [{"tagid": 1659, "name": "Zombies"},
           {"tagid": 1667, "name": "Horror"},
           {"tagid": 1721, "name": "Psychological Horror"}]


def quiet(test):
    """The commands print by design; tests should not."""
    stack = contextlib.ExitStack()
    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    test.addCleanup(stack.close)


class Storage(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        quiet(self)

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(blacklist.load(self.dir), {"games": [], "tags": []})
        self.assertEqual(blacklist.sets(self.dir), (set(), set()))

    def test_corrupt_file_stops_instead_of_silently_emptying(self):
        """Treating a broken blacklist as empty would quietly start recommending
        everything he banned."""
        with open(blacklist.path_for(self.dir), "w") as f:
            f.write("{oops")
        with self.assertRaises(SystemExit):
            blacklist.load(self.dir)

    def test_add_game_then_sets(self):
        blacklist.cmd_add_game(Args(outdir=self.dir, appid=381210,
                                    name="Dead by Daylight"))
        games, tags = blacklist.sets(self.dir)
        self.assertEqual(games, {381210})
        self.assertEqual(tags, set())

    def test_adding_twice_does_not_duplicate(self):
        for _ in range(2):
            blacklist.cmd_add_game(Args(outdir=self.dir, appid=1, name="X"))
        self.assertEqual(len(blacklist.load(self.dir)["games"]), 1)

    def test_reason_and_timestamp_are_kept(self):
        blacklist.cmd_add_game(Args(outdir=self.dir, appid=1, name="X",
                                    reason="надоел"))
        entry = blacklist.load(self.dir)["games"][0]
        self.assertEqual(entry["reason"], "надоел")
        self.assertTrue(entry["at"].startswith("20"))

    def test_appid_only_still_gets_a_name_from_the_library(self):
        """A blacklist of bare numbers is unreadable when he later runs `show`."""
        with open(os.path.join(self.dir, "steam_library.json"), "w") as f:
            json.dump({"games": [{"appid": 730, "name": "Counter-Strike 2"}]}, f)
        appid, name = blacklist.resolve_game(
            Args(outdir=self.dir, appid=730))
        self.assertEqual((appid, name), (730, "Counter-Strike 2"))

    def test_explicit_name_wins_over_lookup(self):
        with open(os.path.join(self.dir, "steam_library.json"), "w") as f:
            json.dump({"games": [{"appid": 730, "name": "Counter-Strike 2"}]}, f)
        self.assertEqual(
            blacklist.resolve_game(Args(outdir=self.dir, appid=730, name="CS"))[1], "CS")

    def test_remove_by_appid_and_by_name(self):
        blacklist.cmd_add_game(Args(outdir=self.dir, appid=1, name="Alpha"))
        blacklist.cmd_add_game(Args(outdir=self.dir, appid=2, name="Beta"))
        blacklist.cmd_remove(Args(outdir=self.dir, appid=1))
        self.assertEqual(blacklist.sets(self.dir)[0], {2})
        blacklist.cmd_remove(Args(outdir=self.dir, name="beta"))
        self.assertEqual(blacklist.sets(self.dir)[0], set())


class TagResolution(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "cache"))
        with open(os.path.join(self.dir, "cache", "tagdict.json"), "w") as f:
            json.dump(TAGDICT, f)

    def test_exact_name_resolves(self):
        self.assertEqual(blacklist.resolve_tag(Args(outdir=self.dir, name="zombies")),
                         (1659, "Zombies"))

    def test_unique_substring_resolves(self):
        self.assertEqual(blacklist.resolve_tag(Args(outdir=self.dir, name="zomb")),
                         (1659, "Zombies"))

    def test_ambiguous_substring_refuses_to_guess(self):
        with self.assertRaises(SystemExit):
            blacklist.resolve_tag(Args(outdir=self.dir, name="horr"))

    def test_unknown_tagid_is_rejected(self):
        with self.assertRaises(SystemExit):
            blacklist.resolve_tag(Args(outdir=self.dir, tagid=999999))


class DropRule(unittest.TestCase):
    def row(self, appid=1, tagids=(1659, 1667)):
        return {"appid": appid, "search_tagids": list(tagids)}

    def test_banned_game_is_dropped(self):
        self.assertTrue(candidates.is_blacklisted(self.row(appid=7), {7}, set()))

    def test_banned_tag_anywhere_on_the_card_drops_it(self):
        self.assertTrue(candidates.is_blacklisted(self.row(), set(), {1667}))

    def test_untouched_candidate_survives(self):
        self.assertFalse(candidates.is_blacklisted(self.row(), {999}, {1721}))

    def test_empty_blacklist_drops_nothing(self):
        self.assertFalse(candidates.is_blacklisted(self.row(), set(), set()))

    def test_candidate_without_tags_survives_a_tag_ban(self):
        self.assertFalse(candidates.is_blacklisted({"appid": 1}, set(), {1667}))


if __name__ == "__main__":
    unittest.main()

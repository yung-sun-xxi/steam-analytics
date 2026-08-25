"""Parsing the store front. No network: everything here runs off a saved fixture."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import steamweb

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                       "search_rows.html")


class ParseSearchRow(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE) as f:
            self.html = f.read()
        self.rows = [steamweb.parse_search_row(r)
                     for r in steamweb.ROW_RE.findall(self.html)]

    def test_both_rows_parse(self):
        self.assertEqual(len(self.rows), 2)
        self.assertTrue(all(r is not None for r in self.rows))

    def test_identity_fields(self):
        r = self.rows[0]
        self.assertEqual(r["appid"], 1059990)
        self.assertEqual(r["name"], "Trombone Champ")
        self.assertEqual(r["release_date"], "15 Sep, 2022")
        self.assertEqual(r["store_url"], "https://store.steampowered.com/app/1059990/")

    def test_review_tooltip_is_split_into_numbers(self):
        r = self.rows[0]
        self.assertEqual(r["review_pct"], 98)
        self.assertEqual(r["review_count"], 7161)
        self.assertEqual(r["review_summary"], "Overwhelmingly Positive")

    def test_price_is_euros_not_cents(self):
        r = self.rows[0]
        self.assertAlmostEqual(r["price_final"], 4.99)
        self.assertEqual(r["discount_pct"], 60)

    def test_tagids_are_ints(self):
        r = self.rows[0]
        self.assertTrue(r["search_tagids"])
        self.assertTrue(all(isinstance(t, int) for t in r["search_tagids"]))

    def test_row_without_appid_is_dropped(self):
        self.assertIsNone(steamweb.parse_search_row('<a class="search_result_row"></a>'))


class TagDictionary(unittest.TestCase):
    def test_reads_the_cache_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache"))
            with open(os.path.join(d, "cache", "tagdict.json"), "w") as f:
                json.dump([{"tagid": 19, "name": "Action"},
                           {"tagid": 29482, "name": "Souls-like"}], f)
            by_name, by_id = steamweb.tag_dictionary(d)
        self.assertEqual(by_name["souls-like"], 29482)
        self.assertEqual(by_id[19], "Action")


class GameTagsCache(unittest.TestCase):
    def test_cached_tags_are_returned_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache", "tags"))
            payload = [{"tagid": 1662, "name": "Survival", "count": 100}]
            with open(os.path.join(d, "cache", "tags", "42.json"), "w") as f:
                json.dump(payload, f)
            self.assertEqual(steamweb.game_tags(42, d), payload)

    def test_empty_cache_is_kept_when_there_is_no_alias(self):
        """An aliased build falls through to the canonical edition; a plain app does not,
        otherwise every genuinely untagged game would be refetched on every run."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache", "tags"))
            with open(os.path.join(d, "cache", "tags", "42.json"), "w") as f:
                json.dump([], f)
            self.assertEqual(steamweb.game_tags(42, d), [])


if __name__ == "__main__":
    unittest.main()

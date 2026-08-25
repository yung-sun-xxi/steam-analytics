"""Scoring and tag resolution. Pure functions, no network."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import candidates

MOOD = [1721]          # Psychological Horror
TASTE = {1662: 0.04,   # Survival, rare -> a search tag
         1695: 0.03,   # Open World, rare
         4: 0.05,      # a common tag
         1721: 0.02}
ROLES = {1662: "search", 1695: "search", 4: "filter", 1721: "search"}


def row(appid=1, tagids=(1662, 1721), pct=95, count=10000):
    return {"appid": appid, "search_tagids": list(tagids),
            "review_pct": pct, "review_count": count}


def score(r, wishlist=(), not_tried=()):
    return candidates.score(r, TASTE, ROLES, set(wishlist), set(not_tried), MOOD)


class ResolveTags(unittest.TestCase):
    def setUp(self):
        self.by_name = {"horror": 1667, "survival": 1662}

    def test_names_and_ids_both_work(self):
        self.assertEqual(candidates.resolve_tags(["horror", "1662"], self.by_name),
                         [1667, 1662])

    def test_case_and_spacing_are_forgiven(self):
        self.assertEqual(candidates.resolve_tags([" Horror "], self.by_name), [1667])

    def test_duplicates_collapse(self):
        self.assertEqual(candidates.resolve_tags(["horror", "1667"], self.by_name), [1667])

    def test_unknown_tag_stops_the_run(self):
        with self.assertRaises(SystemExit):
            candidates.resolve_tags(["definitely-not-a-tag"], self.by_name)


class Score(unittest.TestCase):
    def test_rare_tags_count_twice_over(self):
        """A rare tag lands in taste_fit and again in rare_fit; a common one does not."""
        rare = score(row(tagids=(1662, 1721)))
        common = score(row(tagids=(4, 1721)))
        self.assertGreater(rare["rare_fit"], 0)
        self.assertEqual(common["rare_fit"], TASTE[1721])
        self.assertAlmostEqual(common["common_fit"], TASTE[4])

    def test_off_mood_is_damped_not_dropped(self):
        on = score(row(tagids=(1662, 1721)))
        off = score(row(tagids=(1662,)))
        self.assertFalse(off["mood_tag_on_card"])
        self.assertGreater(off["score"], 0)
        self.assertLess(off["score"], on["score"])

    def test_damping_uses_the_declared_factor(self):
        """Compare two candidates that differ only by the mood flag.

        The mood tag here carries no taste weight, so dropping it from the card leaves
        taste_fit untouched and the whole difference is the damping factor.
        """
        weightless_mood = [999]
        on = candidates.score(row(tagids=(1662, 999)), TASTE, ROLES, set(), set(),
                              weightless_mood)
        off = candidates.score(row(tagids=(1662,)), TASTE, ROLES, set(), set(),
                               weightless_mood)
        self.assertEqual(on["taste_fit"], off["taste_fit"])
        self.assertAlmostEqual(off["score"], on["score"] * candidates.OFF_MOOD_FACTOR,
                               places=6)

    def test_wishlist_boosts(self):
        plain = score(row())
        wished = score(row(), wishlist=[1])
        self.assertTrue(wished["wishlisted"])
        self.assertAlmostEqual(wished["score"],
                               plain["score"] * candidates.WISHLIST_BOOST, places=2)

    def test_owned_but_untried_is_flagged_not_boosted(self):
        plain = score(row())
        untried = score(row(), not_tried=[1])
        self.assertTrue(untried["owned_not_tried"])
        self.assertAlmostEqual(untried["score"], plain["score"])

    def test_review_quality_needs_both_score_and_volume(self):
        great = score(row(pct=95, count=100000))["review_quality"]
        mediocre = score(row(pct=72, count=100000))["review_quality"]
        obscure = score(row(pct=95, count=600))["review_quality"]
        self.assertGreater(great, mediocre)
        self.assertGreater(great, obscure)

    def test_review_quality_floors_at_zero(self):
        self.assertEqual(score(row(pct=40, count=10000))["review_quality"], 0.0)

    def test_no_tag_overlap_scores_no_taste(self):
        self.assertEqual(score(row(tagids=(999999,)))["taste_fit"], 0.0)


if __name__ == "__main__":
    unittest.main()

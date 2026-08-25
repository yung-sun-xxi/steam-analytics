"""The weighting formula. Pure arithmetic, no network."""

import math
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import taste

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


def game(hours, years_ago=0.0, last=True):
    minutes = int(round(hours * 60))
    played_at = NOW - years_ago * 365.25 * 86400
    return {
        "playtime_forever_min": minutes,
        "last_played": (datetime.fromtimestamp(played_at, tz=timezone.utc).isoformat()
                        if last else None),
    }


class GameWeight(unittest.TestCase):
    def test_never_played_weighs_nothing(self):
        self.assertEqual(taste.game_weight(game(0), NOW), 0.0)

    def test_fresh_game_is_the_square_root_of_hours(self):
        self.assertAlmostEqual(taste.game_weight(game(100, 0), NOW), 10.0, places=2)

    def test_one_half_life_halves_the_weight(self):
        fresh = taste.game_weight(game(100, 0), NOW)
        aged = taste.game_weight(game(100, taste.HALF_LIFE_YEARS), NOW)
        self.assertAlmostEqual(aged, fresh / 2, places=2)

    def test_sqrt_keeps_a_huge_game_from_burying_a_small_one(self):
        """364 h beats 100 h, but by under 2x - that is the whole point of the root."""
        big = taste.game_weight(game(364, 0), NOW)
        small = taste.game_weight(game(100, 0), NOW)
        self.assertGreater(big, small)
        self.assertLess(big / small, 2.0)

    def test_recency_can_outrank_raw_hours(self):
        """100 h played this month should outweigh 364 h left alone for six years."""
        recent = taste.game_weight(game(100, 0), NOW)
        stale = taste.game_weight(game(364, 6), NOW)
        self.assertGreater(recent, stale)

    def test_missing_date_is_treated_as_long_ago(self):
        known_old = taste.game_weight(game(100, 10), NOW)
        undated = taste.game_weight(game(100, last=False), NOW)
        self.assertAlmostEqual(undated, known_old, places=2)

    def test_future_timestamp_does_not_amplify(self):
        """A clock skew must not turn decay into growth."""
        self.assertLessEqual(taste.game_weight(game(100, -2), NOW), math.sqrt(100) + 1e-9)


class NotTriedCohort(unittest.TestCase):
    def test_threshold_is_an_hour(self):
        self.assertEqual(taste.NOT_TRIED_MAX_MIN, 60)


if __name__ == "__main__":
    unittest.main()

import unittest

from fngameanalyzer import model, rules, service, strategy

STATS = {"PLACEMENT_STAT_INDEX": 0, "TEAM_ELIMS_STAT_INDEX": 0, "VICTORY_ROYALE_STAT": 0}
# 6 points for 1st, 3 for 2nd to 10th, 1 for 11th to 20th, plus 2 per elimination (up to 10)
RULES = [["PLACEMENT_STAT_INDEX", "lte", [[1, 3, False], [2, 2, False], [10, 1, False], [20, 1, False]]],
         ["TEAM_ELIMS_STAT_INDEX", "gte", [[k, 2, False] for k in range(1, 11)]]]


def w(i, region="NAC", cat="reload zb duo", fmt="f1", end=None):
    return {"window_id": f"S42_Cup_Event{i}_{region}", "event_id": "e", "family": "CASHCUP", "region": region, "begin": i * 100,
            "end": end or i * 100 + 50, "points": [100.0] * 50, "games": [6] * 50, "entrants": 1000, "final": 1,
            "meta": {"category": cat, "format": fmt, "match_cap": 6}}


class HistoryTest(unittest.TestCase):
    def test_same_region_only_when_enough(self):
        target = w(20, "NAC")
        same = [w(i, "NAC") for i in range(1, 6)]
        other = [w(i + 10, "EU") for i in range(1, 6)]
        pool = model.comparable(target, same + other)
        self.assertEqual({x["region"] for x in pool}, {"NAC"})   # five NAC events: no other region needed

    def test_other_regions_fill_in_behind_the_region(self):
        target = w(20, "NAC")
        same = [w(1, "NAC"), w(2, "NAC")]
        other = [w(i + 10, "EU") for i in range(1, 4)]
        pool = model.comparable(target, same + other)
        self.assertEqual([x["region"] for x in pool], ["NAC", "NAC", "EU", "EU", "EU"])   # region first, then the rest
        self.assertEqual(pool[0]["window_id"], same[1]["window_id"])                      # newest first inside a region

    def test_format_and_gamemode_must_match(self):
        target = w(20, "NAC")
        pool = model.comparable(target, [w(1, "NAC", fmt="other"), w(2, "NAC", cat="br solo"), w(3, "NAC")])
        self.assertEqual([x["window_id"] for x in pool], [w(3)["window_id"]])

    def test_peers_previous_events_only(self):
        target = w(20, "NAC")
        rows = [w(5, "NAC"), w(30, "NAC"), w(6, "EU")]   # event 30 happens after the target
        ids = {x["window_id"] for x in strategy.peers(target, rows)}
        self.assertIn(w(5)["window_id"], ids)
        self.assertNotIn(w(30)["window_id"], ids)


class ScoringTest(unittest.TestCase):
    def test_game_points(self):
        self.assertEqual(rules.game_points(RULES, {**STATS, "PLACEMENT_STAT_INDEX": 1, "TEAM_ELIMS_STAT_INDEX": 3}), 3 + 2 + 2 + 2 * 3 + 0 - 0)

    def test_series_key_spans_rounds_and_seasons(self):
        a = service._series_key("S42_ReloadCashCup_DuosZB_Event5Round2_NAC")
        b = service._series_key("S41_ReloadCashCup_DuosZB_Event1Round1_EU")
        self.assertEqual(a, b)
        self.assertEqual(a, "ReloadCashCup_DuosZB")


class CalendarTest(unittest.TestCase):
    def test_text_is_escaped(self):
        self.assertEqual(service._ics_text("a,b;c\nd"), "a\\,b\\;c\\nd")


if __name__ == "__main__":
    unittest.main()

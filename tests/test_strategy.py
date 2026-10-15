import unittest
from unittest import mock

import numpy as np

from fngameanalyzer import drops, model, rules, service, storage, strategy

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


class DropsTest(unittest.TestCase):
    def test_point_in_polygon(self):
        x = np.array([0.5, 0.9, 0.1, 0.45], dtype=np.float32)
        y = np.array([0.5, 0.5, 0.1, 0.9], dtype=np.float32)
        square = [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]]
        self.assertEqual(drops._in_poly(x, y, square).tolist(), [True, False, False, False])
        triangle = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        self.assertEqual(drops._in_poly(np.array([0.2, 0.8], dtype=np.float32), np.array([0.2, 0.8], dtype=np.float32), triangle).tolist(), [True, False])

    def test_stats_and_qualified_share(self):
        a = {"placement": np.array([1, 5, 20, 8]), "points": np.array([60, 30, 2, 40]), "rank": np.array([3, 90, 400, 0]),
             "lobby": np.array([20, 20, 20, 20]), "win": np.array([1, 0, 0, 0])}
        s = drops._stats(a, np.ones(4, dtype=bool), 100)
        self.assertEqual(s["landings"], 4)
        self.assertEqual(s["qualifier_landings"], 2)        # ranks 3 and 90 are inside the top 100; rank 0 means unknown
        self.assertAlmostEqual(s["win_rate"], 0.25)
        self.assertEqual(s["early_exit_rate"], 0.25)        # only the 20th place finish is in the last quarter
        self.assertEqual(drops._stats(a, np.zeros(4, dtype=bool), 100), {"landings": 0})

    def test_ingest_converts_world_coordinates_and_fills_rank_and_points(self):
        acct = "a" * 32
        final = {"window_id": "w", "final": 1, "players": [[acct]], "meta": {"rules": RULES}}
        saved = {}
        body = {"window_id": "w", "coords": "world", "bounds": [-1000, 1000, -1000, 1000], "flip_y": True,
                "map": {"name": "M", "image": "http://insecure/x.png", "pois": [{"name": "P", "x": 0, "y": 0}]},
                "drops": [{"game": 1, "team": acct, "x": 500, "y": 500, "placement": 1, "elims": 3, "win": True},
                          {"game": 1, "team": "t2", "x": 5000, "y": 0, "placement": 4}]}       # the second row is off the map
        with (mock.patch.object(storage, "get_window", return_value=final),
              mock.patch.object(storage, "drops_replace", side_effect=lambda w, rows, append=False: saved.update(rows=rows), create=True),
              mock.patch.object(storage, "drop_map_set", side_effect=lambda w, d: saved.update(map=d), create=True)):
            out = drops.ingest(body)
        self.assertEqual((out["stored"], out["skipped"]), (1, 1))
        game, team, x, y, poi, place, pts, rank, win = saved["rows"][0]
        self.assertAlmostEqual(x, 0.75)
        self.assertAlmostEqual(y, 0.25)                  # flipped
        self.assertEqual(rank, 1)                        # found in the stored final board
        self.assertEqual(pts, 3 + 2 + 2 + 6)             # placement 1 + three elims at 2 points: from the event's scoring rules
        self.assertEqual(saved["map"]["image"], "")      # only https images are kept
        self.assertAlmostEqual(saved["map"]["pois"][0]["x"], 0.5)


class DropsLoaderTest(unittest.TestCase):
    def _load(self, body, rec, kv):
        final = {"window_id": "w", "final": 0, "players": [], "meta": {"rules": RULES}}
        with (mock.patch.object(storage, "get_window", return_value=final),
              mock.patch.object(storage, "drops_replace", create=True),
              mock.patch.object(storage, "drop_map_get", side_effect=lambda w: rec.get("m"), create=True),
              mock.patch.object(storage, "drop_map_set", side_effect=lambda w, d: rec.update(m=d), create=True),
              mock.patch.object(storage, "kv_get", side_effect=kv.get),
              mock.patch.object(storage, "kv_set", side_effect=kv.__setitem__)):
            return drops.ingest(body)

    def test_background_map_adds_up_and_sessions_are_remembered(self):
        rec, kv = {}, {}
        row = {"game": 1, "team": "t1", "x": 0.5, "y": 0.5, "placement": 3, "points": 10}
        self._load({"window_id": "w", "drops": [row], "map": {"name": "M", "base": {"cells": [[5, 2], [7, 1]]}}, "sessions_done": ["s1"]}, rec, kv)
        self._load({"window_id": "w", "drops": [row], "append": True, "map": {"base": {"cells": [[5, 3]]}}, "sessions_done": ["s2"]}, rec, kv)
        self.assertEqual(rec["m"]["base"], {"5": 5, "7": 1})          # counts add up across batches
        self.assertEqual(rec["m"]["name"], "M")                       # a later batch without a name keeps it
        self.assertEqual(kv["drops_done:w"]["sessions"], ["s1", "s2"])

    def test_batch_with_only_finished_sessions_is_accepted(self):
        rec, kv = {}, {}
        out = self._load({"window_id": "w", "drops": [], "sessions_done": ["s9"]}, rec, kv)
        self.assertEqual(out["stored"], 0)
        self.assertEqual(kv["drops_done:w"]["sessions"], ["s9"])


if __name__ == "__main__":
    unittest.main()

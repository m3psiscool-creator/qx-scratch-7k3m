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


class AnyRankTest(unittest.TestCase):
    def test_ranks_inside_the_stored_board_are_read_directly(self):
        pts = [1000 - i for i in range(1000)]
        self.assertEqual(service._interp_deep(pts[999], {}, 800, pts), pts[799])       # rank 800 comes straight from the board

    def test_ranks_between_thresholds_are_interpolated(self):
        pts = [5000 - 4 * i for i in range(1000)]                                       # rank 1000 has 1004 points
        deep = {"1500": {"points": 600}, "2000": {"points": 300}}
        mid = service._interp_deep(pts[999], deep, 1250)
        self.assertTrue(600 < mid < pts[999])                                           # between rank 1000 and rank 1500

    def test_top_x_must_be_in_range(self):
        for bad in (0, -5, 10001):
            with mock.patch.object(storage, "get_window", return_value={"window_id": "w", "final": 0}):
                with self.assertRaises(ValueError):
                    service._run_predict("w", bad)


class EventTypesTest(unittest.TestCase):
    def test_evaluation_cups_are_tracked(self):
        from fngameanalyzer import config
        self.assertEqual(config.TOURNAMENT_TYPES.get("WorkshopCup"), "WORKSHOP")      # Epic's Performance Evaluation cups

    def test_no_map_is_ever_drawn_from_player_movement(self):
        rec = {"image": "", "base": {"1": 5}, "base_size": 128}
        w = {"window_id": "w", "event_id": "e", "region": "NAC", "begin": 1, "end": 2, "final": 1, "meta": {"playlist": "Playlist_X_JumpBear", "game_type": "reload", "mode": "solo"}}
        with (mock.patch.object(storage, "get_window", return_value=w), mock.patch.object(storage, "drop_map_get", return_value=rec, create=True),
              mock.patch.object(storage, "drops_available", return_value={}, create=True), mock.patch.object(drops.service, "pretty", return_value="x"),
              mock.patch.object(drops.service, "goal_of", return_value=None), mock.patch.object(drops.classify, "of", return_value="reload solo")):
            info = drops.map_info("w")
        self.assertNotIn("base", info["map"])
        self.assertEqual(info["map"]["image"], "")
        self.assertIn("No picture of this map", info["note"])


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


class ChestTest(unittest.TestCase):
    W = {"window_id": "w", "meta": {"playlist": "Playlist_ShowdownTournament_SourSpawnDuos_PBM", "mode": "duos"}}

    def setUp(self):
        drops._atlas_cache.clear()

    def _atlas(self, cells, matches=100):
        return {"size": drops.CHEST, "matches": matches, "cells": cells}

    def test_sites_keep_repeated_openings_and_drop_one_offs(self):
        n = drops.CHEST
        # chest A: opened in 60 of 100 matches (its openings landed in two neighbouring cells), chest B in 8, a single drop in 1
        atlas = self._atlas({str(10 * n + 10): 40, str(10 * n + 11): 20, str(50 * n + 50): 8, str(80 * n + 80): 1})
        with mock.patch.object(storage, "kv_get", return_value=atlas):
            sites, M = drops._sites(self.W)
        self.assertEqual(M, 100)
        self.assertEqual(len(sites), 2)                         # the single opening is not a chest
        self.assertAlmostEqual(sites[0]["rate"], 0.6, places=2)  # looted early in 60% of matches
        self.assertAlmostEqual(sites[1]["rate"], 0.08, places=2)

    def test_too_few_matches_gives_no_chests(self):
        with mock.patch.object(storage, "kv_get", return_value=self._atlas({"5": 9}, matches=5)):
            self.assertEqual(drops._sites(self.W)[0], [])

    def test_area_ranking_prefers_many_chests_and_few_players(self):
        n = drops.CHEST
        cells = {}
        for k in range(4):   # crowded spot around (0.2, 0.2): 4 chests
            cells[str(int((0.2 + 0.004 * k) * n) * n + int(0.2 * n))] = 50
        for k in range(4):   # quiet spot around (0.7, 0.7): 4 chests
            cells[str(int((0.7 + 0.004 * k) * n) * n + int(0.7 * n))] = 50
        xs = np.array([0.2] * 30 + [0.7] * 3, dtype=np.float32)   # 30 landings at the first spot, 3 at the second
        a = {"game": np.ones(len(xs), dtype=np.int16), "x": xs, "y": xs.copy(), "placement": np.full(len(xs), 5, dtype=np.int16),
             "points": np.full(len(xs), 20, dtype=np.int32), "rank": np.zeros(len(xs), dtype=np.int32), "lobby": np.full(len(xs), 20, dtype=np.int16),
             "win": np.zeros(len(xs), dtype=np.int8)}
        def kv(k):
            return self._atlas(cells) if k.startswith("chests:") else {"sessions": ["s%d" % i for i in range(10)]}
        with (mock.patch.object(storage, "get_window", return_value=self.W), mock.patch.object(storage, "kv_get", side_effect=kv),
              mock.patch.object(drops, "_arrays", return_value=a)):
            out = drops.areas("w", min_chests=1)
        first, second = out["areas"][0], out["areas"][1]
        self.assertGreater(first["x"], 0.5)                       # the quiet spot comes first
        self.assertLess(first["players_per_game"], second["players_per_game"])
        self.assertGreater(first["chests_per_player"], second["chests_per_player"])
        self.assertAlmostEqual(out["teams_per_match"], 3.3, places=1)


class PictureCheckTest(unittest.TestCase):
    def _arrays(self, xs, ys):
        return {"x": np.array(xs, dtype=np.float32), "y": np.array(ys, dtype=np.float32)}

    def test_landings_on_land_pass_and_landings_in_the_sea_fail(self):
        known = drops.MAPS["SourSpawn"]
        with mock.patch.object(drops, "_arrays", return_value=self._arrays([0.5, 0.45, 0.55, 0.4], [0.5, 0.4, 0.45, 0.55])):
            self.assertGreaterEqual(drops.picture_check("w", known), drops.MIN_ON_LAND)     # the middle of the island is land
        with mock.patch.object(drops, "_arrays", return_value=self._arrays([0.02, 0.03, 0.97, 0.98], [0.02, 0.97, 0.03, 0.98])):
            self.assertLess(drops.picture_check("w", known), 0.2)                           # the four corners are open sea
        with mock.patch.object(drops, "_arrays", side_effect=ValueError("none")):
            self.assertIsNone(drops.picture_check("w", known))                               # no landings: nothing to test with


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


class MapFitTest(unittest.TestCase):
    def test_auto_fit_recovers_a_known_placement(self):
        known = {"mask": "raw-tigerranch"}
        fit = {"k": 3, "L": 1.55, "cx": 0.48, "cy": 0.52}
        m = drops._oriented_mask("raw-tigerranch", 3)
        rng = np.random.default_rng(5)
        xs, ys = [], []
        while len(xs) < 1500:    # landings spread evenly over the land of the picture
            u, v = rng.random(2)
            if m[int(v * m.shape[0]), int(u * m.shape[0])]:
                xs.append((u - 0.5) * fit["L"] + fit["cx"])
                ys.append((v - 0.5) * fit["L"] + fit["cy"])
        got = drops._auto_fit("TigerRanch", known, {"x": np.array(xs, dtype=np.float32), "y": np.array(ys, dtype=np.float32)})
        self.assertIsNotNone(got)
        self.assertEqual(got["k"], 3)
        self.assertLess(abs(got["cx"] - 0.48) + abs(got["cy"] - 0.52), 0.04)

    def test_too_few_landings_give_no_fit(self):
        self.assertIsNone(drops._auto_fit("TigerRanch", {"mask": "raw-tigerranch"}, {"x": np.zeros(50, dtype=np.float32), "y": np.zeros(50, dtype=np.float32)}))

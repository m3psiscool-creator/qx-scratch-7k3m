"""Early-game movement rows: stored for leaderboard players, never replace a full replay, stop when the database is nearly full."""
import unittest
from unittest import mock

from fngameanalyzer import storage, tracks

A = "a" * 32


def body(partial, n=3):
    return {"window_id": "W", "session": "S1", "duration": 120, "partial": partial, "storm": [],
            "teams": [{"accounts": [A], "rank": 7, "game": 2, "placement": 4, "points": 20, "elims": 1}],
            "tracks": [{"epic": A, "team": 1, "placement": 4, "kills": 1, "death": None, "p": [[0, 100, 100, 5], [4, 110, 120, 5]][:n]}]}


class Partial(unittest.TestCase):
    def setUp(self):
        self.put = []
        self.p = [mock.patch.object(storage, "tracks_put", lambda *a, **k: self.put.append((a, k)) or True, create=True),
                  mock.patch.object(storage, "db_mb", lambda: 100.0, create=True)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_batch_stores_partial_flag_and_skips_names(self):
        with mock.patch.object(tracks.insights, "_name_map", side_effect=AssertionError("no Epic lookups for early reads")):
            r = tracks.ingest({"window_id": "W", "partial": True, "matches": [body(True)]})
        self.assertEqual(r["stored"], 1)
        self.assertEqual(self.put[0][0][5], 1)   # partial flag
        self.assertEqual(self.put[0][0][4][0][0], A)   # indexed by account

    def test_nearly_full_database_skips_early_reads_only(self):
        with mock.patch.object(storage, "db_mb", lambda: 450.0, create=True), mock.patch.object(tracks.insights, "_name_map", return_value={}):
            self.assertEqual(tracks.ingest(body(True)).get("skipped"), "database nearly full")
            self.assertEqual(tracks.ingest(body(False)).get("ok"), True)   # full replays still go in
        self.assertEqual(len(self.put), 1)

    def test_full_replay_not_replaced_by_partial(self):
        with mock.patch.object(storage, "tracks_put", lambda *a, **k: False, create=True):
            self.assertIn("full replay", tracks.ingest(body(True)).get("skipped", ""))


if __name__ == "__main__":
    unittest.main()

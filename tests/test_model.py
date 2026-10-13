import math
import unittest

from fngameanalyzer import model


def win(i, scale, entrants=1000, family="FNCS", region="EU"):
    pts = [scale * 100 * math.exp(-0.01 * r) for r in range(1, 501)]
    return {"window_id": f"w{i}", "family": family, "region": region, "end": i, "begin": i - 1,
            "entrants": entrants, "points": pts, "games": [6] * 500}


class ModelTest(unittest.TestCase):
    def test_prior_only(self):
        past = [win(i, 1.0) for i in range(1, 7)]
        target = {"window_id": "t", "family": "FNCS", "region": "EU", "begin": 7, "end": 8}
        r = model.predict(target, past, 50)
        self.assertAlmostEqual(r["likely"], past[0]["points"][49], delta=2)
        self.assertLessEqual(r["low"], r["likely"])
        self.assertLessEqual(r["likely"], r["safe"])

    def test_live_scales_up(self):
        past = [win(i, 1.0) for i in range(1, 7)]
        target = {"window_id": "t", "family": "FNCS", "region": "EU", "begin": 0, "end": 10}
        snap = {"ts": 5, "entrants": 1000, "games": [3] * 500,
                "points": [p / 2 for p in past[0]["points"]]}
        r = model.predict(target, past, 50, snapshot=snap)
        self.assertTrue(r["live"]["basis"] == "games")
        self.assertAlmostEqual(r["live"]["progress"], 0.5, places=2)

    def test_no_data(self):
        target = {"window_id": "t", "family": "FNCS", "region": "EU", "begin": 0, "end": 1}
        self.assertIsNone(model.predict(target, [], 10))


if __name__ == "__main__":
    unittest.main()

import time, unittest
from unittest import mock
from fngameanalyzer import collector

def W(region, begin, end, goal=True, final=0):
    return {"window_id": f"{region}{begin}", "region": region, "begin": begin, "end": end, "final": final,
            "meta": {"goal": {"rank": 100, "kind": "cash"}} if goal else {}}

class QuietTest(unittest.TestCase):
    def act(self, rows, now):
        with mock.patch.object(collector.storage, "window_list", return_value=rows):
            return collector._activity(now)

    def test_active_during_and_after(self):
        n = 100000
        self.assertTrue(self.act([W("EU", n - 100, n + 5000)], n)[0])
        self.assertTrue(self.act([W("EU", n - 7000, n - 1000)], n)[0])          # ended 17 min ago, final not stored
        self.assertFalse(self.act([W("EU", n - 9000, n - 4000)], n)[0])         # ended long ago
        self.assertTrue(self.act([W("EU", n + 200, n + 5000)], n)[0])           # about to start

    def test_ignored(self):
        n = 100000
        self.assertFalse(self.act([W("EU", n - 100, n + 5000, goal=False)], n)[0])   # no prizes
        self.assertFalse(self.act([W("BR", n - 100, n + 5000)], n)[0])               # untracked region

    def test_next_start_and_gate(self):
        n = 100000
        a, nxt = self.act([W("NAC", n + 4000, n + 9000), W("EU", n + 2000, n + 6000)], n)
        self.assertFalse(a); self.assertEqual(nxt, n + 2000)
        collector._IDLE_UNTIL = time.time() + 600
        self.assertFalse(collector.should_run())
        collector._IDLE_UNTIL = 0.0
        self.assertTrue(collector.should_run())

if __name__ == "__main__":
    unittest.main()

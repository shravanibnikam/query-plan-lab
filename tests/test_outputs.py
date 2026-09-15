import tempfile
import unittest
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from qpl.indexes import CONFIGS
from qpl.plot import draw
from qpl.queries import QUERIES
from qpl.validate import checks

def matrix():
    return pd.DataFrame([
        dict(config=c, query=q.name, run_no=r,
             execution_ms=1 if c == "c7_gin_payload" else 100,
             events_scan_node="Index Only Scan" if c == "c5_btree_covering" else "Seq Scan")
        for c in CONFIGS for q in QUERIES for r in range(1, 6)])

class OutputTests(unittest.TestCase):
    def test_chart_log_scale_shared_and_every_bar_labeled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.png"
            fig = draw(matrix(), path)
            self.assertEqual(len(fig.axes), 4)
            for ax in fig.axes:
                self.assertEqual(ax.get_yscale(), "log")
                self.assertEqual(len(ax.patches), 8)
                self.assertEqual(len(ax.texts), 8)
                self.assertTrue(ax.get_shared_y_axes().joined(ax, fig.axes[0]))
            self.assertTrue(path.is_file())
            self.assertEqual(plt.imread(path).shape[:2], (1800, 2700))
            plt.close(fig)

    def test_incomplete_or_duplicate_matrix_fails(self):
        runs = matrix()
        indexes = pd.DataFrame({"config": list(CONFIGS)[1:]})
        stale = {"before": {"metrics": {"normalized_est_ratio": 2000}},
                 "after": {"metrics": {"normalized_est_ratio": 1}}}
        self.assertTrue(all(checks(runs, indexes, stale).values()))
        self.assertFalse(all(checks(runs.iloc[1:], indexes, stale).values()))
        duplicate = pd.concat([runs.iloc[1:], runs.iloc[[1]]], ignore_index=True)
        self.assertFalse(checks(duplicate, indexes, stale)["five unique runs per matrix cell"])

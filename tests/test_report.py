import json
import re
import unittest

from qpl.config import RESULTS
from qpl.stale_stats import compact_join, readme_excerpt


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((RESULTS / "stale_stats.json").read_text())

    def test_excerpt_preserves_output_rows_and_inner_loop_counts(self):
        def node(kind, **fields):
            return {"Node Type": kind, "Plan Rows": 1, "Actual Rows": 1,
                    "Actual Loops": 1, **fields}

        scan = node("Seq Scan", **{"Relation Name": "events", "Parallel Aware": True,
                                  "Actual Rows": 133294, "Actual Loops": 3})
        outer = node("Gather", **{"Actual Rows": 399881, "Plans": [scan]})
        inner = node("Index Scan", **{"Relation Name": "accounts", "Index Name": "accounts_pkey",
                     "Actual Loops": 399881, "Shared Hit Blocks": 1599524, "Shared Read Blocks": 0})
        plan = [{"Plan": node("Nested Loop", **{"Actual Rows": 399881, "Plans": [outer, inner]})}]
        before = compact_join(plan)
        self.assertEqual(len(before.splitlines()), 6)
        self.assertIn("Nested Loop: Plan Rows: 1, Actual Rows: 399881, Actual Loops: 1", before)
        self.assertIn("Plan Rows: 1, Actual Rows: 1, Actual Loops: 399881", before)
        self.assertIn("Shared Hit Blocks: 1599524, Shared Read Blocks: 0", before)

    def test_readme_links_to_the_actual_median_plans(self):
        text = readme_excerpt(self.data)
        self.assertNotIn("```json", text)
        for phase in ["before", "after"]:
            match = re.search(rf"results/plans/(stale__{phase}__run[1-5]\.json)", text)
            self.assertIsNotNone(match)
            name = match.group(1)
            self.assertEqual(json.loads((RESULTS / "plans" / name).read_text()),
                             self.data[phase]["plan"])

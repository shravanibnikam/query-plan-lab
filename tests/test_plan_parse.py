import unittest
from qpl.plan_parse import parse

def document(node):
    return [{"Plan": node, "Planning Time": .2, "Execution Time": 12}]

class PlanParseTests(unittest.TestCase):
    def test_parallel_loops_and_inclusive_buffers(self):
        scan = {"Node Type": "Seq Scan", "Relation Name": "events", "Parallel Aware": True,
                "Plan Rows": 100, "Actual Rows": 80, "Actual Loops": 3, "Shared Read Blocks": 10}
        row = parse(document({"Node Type": "Gather Merge", "Workers Planned": 2, "Workers Launched": 2,
                              "Shared Read Blocks": 10, "Plans": [scan]}))
        self.assertEqual(row["actual_rows"], 240)
        self.assertEqual(row["est_ratio"], 2.4)
        self.assertEqual(row["normalized_est_ratio"], 1)
        self.assertEqual(row["shared_read"], 20)
        self.assertEqual(row["root_shared_read"], 10)
        self.assertTrue(row["parallel"])

    def test_bitmap_index_child_is_not_heap_scan(self):
        row = parse(document({"Node Type": "Bitmap Heap Scan", "Relation Name": "events",
            "Plan Rows": 0, "Actual Rows": 5, "Actual Loops": 2,
            "Plans": [{"Node Type": "Bitmap Index Scan", "Plan Rows": 4, "Actual Rows": 5, "Actual Loops": 1}]}))
        self.assertEqual(row["events_scan_node"], "Bitmap Heap Scan")
        self.assertEqual(row["est_ratio"], 10)
        self.assertFalse(row["parallel"])

    def test_missing_events_fails(self):
        with self.assertRaises(ValueError):
            parse(document({"Node Type": "Result"}))

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch

import numpy as np
from qpl.config import ANCHOR, SEED
from qpl.generate import copy_events, payload_pool, timestamps

class Sink:
    def __init__(self):
        self.blocks = []
    def cursor(self):
        return self
    def copy(self, statement):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def write(self, block):
        self.blocks.append(block)

class GeneratorTests(unittest.TestCase):
    def test_float_rounding_cannot_include_exclusive_endpoint(self):
        class TinyDraw:
            def uniform(self, low, high, count):
                return np.array([0., 1e-12, .5])
        end = ANCHOR + timedelta(days=7)
        values = timestamps(TinyDraw(), 3, ANCHOR, end)
        self.assertLess(values.max(), end.timestamp())

    def test_pool_selectivities_and_uniqueness(self):
        pool = payload_pool()
        docs = [json.loads(p) for p in pool]
        self.assertEqual(len(set(pool)), 5000)
        self.assertEqual(sum(p["source"] == "mobile" for p in docs), 1750)
        self.assertEqual(sum(p.get("beta_cohort", False) for p in docs), 25)

    def test_chunk_boundaries_preserve_order_and_determinism(self):
        def generate():
            rng = np.random.default_rng(SEED)
            times = timestamps(rng, 1003, ANCHOR-timedelta(days=731), ANCHOR)
            sink = Sink()
            with patch("qpl.generate.CHUNK_SIZE", 200), redirect_stdout(io.StringIO()):
                copy_events(sink, rng, times, first_id=31)
            return "".join(sink.blocks)
        data = generate()
        self.assertEqual(data, generate())
        rows = [line.split("\t") for line in data.splitlines()]
        self.assertEqual([int(r[0]) for r in rows], list(range(31, 1034)))
        dates = [r[2] for r in rows]
        self.assertEqual(dates, sorted(dates))
        self.assertLess(dates[-1], ANCHOR.isoformat())
        self.assertTrue(all(len(r) == 7 and 1 <= int(r[1]) <= 200000 for r in rows))
        self.assertTrue(all(r[3] == "\\N" or r[3] > r[2] for r in rows))
        self.assertTrue(all(isinstance(json.loads(r[6]), dict) for r in rows))

    def test_new_window_strictly_after_anchor(self):
        times = timestamps(np.random.default_rng(SEED), 500, ANCHOR+timedelta(days=30), ANCHOR+timedelta(days=37))
        self.assertGreater(times.min(), ANCHOR.timestamp())
        self.assertLess(times.max(), (ANCHOR+timedelta(days=37)).timestamp())

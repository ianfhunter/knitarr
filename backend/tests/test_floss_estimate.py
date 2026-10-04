"""mismatch.co.uk floss-amount formula."""

from __future__ import annotations

import unittest

from knitarr.services.floss_estimate import skeins_needed, skeins_to_buy, stitches_per_skein


class FlossEstimateTests(unittest.TestCase):
    def test_chart_values(self):
        # Published table: 14-count, 2 strands → 1785 stitches/skein
        self.assertEqual(stitches_per_skein(fabric_count=14, strands=2), 1785.0)
        self.assertEqual(stitches_per_skein(fabric_count=14, strands=1), 3570.0)
        self.assertEqual(stitches_per_skein(fabric_count=14, strands=3), 1190.0)
        self.assertEqual(stitches_per_skein(fabric_count=18, strands=2), 2295.0)

    def test_skeins_needed(self):
        self.assertEqual(skeins_needed(0, fabric_count=14, strands=2), 0.0)
        self.assertAlmostEqual(skeins_needed(1785, fabric_count=14, strands=2), 1.0)
        self.assertEqual(skeins_to_buy(1786, fabric_count=14, strands=2), 2)
        self.assertEqual(skeins_to_buy(100, fabric_count=14, strands=2), 1)


if __name__ == "__main__":
    unittest.main()

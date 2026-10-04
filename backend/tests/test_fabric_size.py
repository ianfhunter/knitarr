"""Thread-Bare style fabric size checks."""

from __future__ import annotations

import unittest

from knitarr.services.fabric_size import fabric_inches, stitched_inches


class FabricSizeTests(unittest.TestCase):
    def test_thread_bare_example(self):
        # 24" × 18" on 14ct ⇒ 336 × 252 stitches; suggested fabric 30" × 24" with 3" border.
        self.assertEqual(stitched_inches(336, 14), 24.0)
        self.assertEqual(stitched_inches(252, 14), 18.0)
        self.assertEqual(fabric_inches(336, fabric_count=14, border_inches=3), 30.0)
        self.assertEqual(fabric_inches(252, fabric_count=14, border_inches=3), 24.0)

    def test_eleven_count(self):
        self.assertAlmostEqual(stitched_inches(336, 11), 336 / 11)
        self.assertAlmostEqual(fabric_inches(336, fabric_count=11, border_inches=3), 336 / 11 + 6)


if __name__ == "__main__":
    unittest.main()

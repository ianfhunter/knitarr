"""Chart save + filename helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, parse_oxs, write_oxs
from knitarr.services.catalog import sanitize_filename
from knitarr.services.image_to_oxs import looks_like_dmc_label, nearest_dmc, parse_hex_rgb


class ChartEditTests(unittest.TestCase):
    def test_sanitize_filename_strips_paths(self):
        self.assertEqual(sanitize_filename("  The Kiss.pdf  "), "The Kiss.pdf")
        self.assertEqual(sanitize_filename("../secret.pdf"), "secret.pdf")
        self.assertEqual(sanitize_filename("foo/bar*.oxs"), "bar_.oxs")
        with self.assertRaises(ValueError):
            sanitize_filename("...")

    def test_write_oxs_keeps_backstitches(self):
        norm = NormalizedPattern(
            title="Outline",
            width_stitches=4,
            height_stitches=3,
            palette=[
                PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF"),
                PaletteEntry(index=1, number="DMC 310", name="Black", color="000000"),
            ],
            full_stitches=[{"x": 1, "y": 1, "palindex": 1}],
            backstitches=[{"x1": 0, "y1": 0, "x2": 4, "y2": 0, "palindex": 1}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chart.oxs"
            write_oxs(path, norm)
            loaded = parse_oxs(path)
        self.assertEqual(len(loaded.backstitches), 1)
        self.assertEqual(loaded.backstitches[0]["x2"], 4)
        self.assertEqual(loaded.backstitches[0]["palindex"], 1)
        self.assertEqual(loaded.color_count(), 1)

    def test_nearest_dmc_names_gold(self):
        number, name, color = nearest_dmc(parse_hex_rgb("F0C840"))
        self.assertTrue(number.startswith("DMC "))
        self.assertIn(name.lower(), {"topaz", "topaz medium", "old gold medium", "tangerine light", "yellow dark"})
        self.assertTrue(looks_like_dmc_label(number))
        self.assertFalse(looks_like_dmc_label("Colour 3"))
        self.assertEqual(len(color), 6)


if __name__ == "__main__":
    unittest.main()

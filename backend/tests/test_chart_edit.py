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

    def test_parse_sample_part_stitches_and_knots(self):
        candidates = [
            Path("/app/samples/sample.oxs"),
            Path(__file__).resolve().parent.parent.parent / "samples" / "sample.oxs",
        ]
        samples = next((p for p in candidates if p.is_file()), None)
        if samples is None:
            self.skipTest("sample.oxs not found")
        loaded = parse_oxs(samples)
        self.assertEqual(len(loaded.part_stitches), 2)
        self.assertEqual(loaded.part_stitches[0]["direction"], 1)
        self.assertEqual(loaded.part_stitches[1]["palindex1"], 1)
        knots = [o for o in loaded.ornaments if o["objecttype"] == "knot"]
        self.assertEqual(len(knots), 1)
        self.assertAlmostEqual(float(knots[0]["x"]), 4.5)
        self.assertEqual(loaded.color_count(), 2)

    def test_roundtrip_part_stitches_and_knots(self):
        norm = NormalizedPattern(
            title="Parts",
            width_stitches=6,
            height_stitches=6,
            palette=[
                PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF"),
                PaletteEntry(index=2, number="DMC 666", name="Red", color="E31D42"),
            ],
            full_stitches=[],
            part_stitches=[{"x": 1, "y": 2, "palindex1": 2, "palindex2": 0, "direction": 2}],
            ornaments=[{"x": 3.25, "y": 4.5, "palindex": 2, "objecttype": "knot"}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parts.oxs"
            write_oxs(path, norm)
            loaded = parse_oxs(path)
        self.assertEqual(len(loaded.part_stitches), 1)
        self.assertEqual(loaded.part_stitches[0]["direction"], 2)
        self.assertEqual(len(loaded.ornaments), 1)
        self.assertEqual(loaded.ornaments[0]["objecttype"], "knot")

    def test_expand_implied_peak_companions(self):
        """Ursa stores only the right half of a /\\ peak; left BR is implied by backstitch."""
        from knitarr.parsers.oxs import expand_implied_part_halves, write_oxs

        norm = NormalizedPattern(
            title="Peak",
            width_stitches=4,
            height_stitches=4,
            palette=[
                PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF"),
                PaletteEntry(index=1, number="DMC 310", name="Black", color="000000"),
                PaletteEntry(index=5, number="DMC 3773", name="Flesh", color="B17460"),
            ],
            full_stitches=[
                {"x": 0, "y": 1, "palindex": 5},
                {"x": 1, "y": 1, "palindex": 5},
            ],
            # Right peak cell only (BL), as in piggies fence tops.
            part_stitches=[{"x": 1, "y": 0, "palindex1": 5, "palindex2": 0, "direction": 1}],
            backstitches=[
                {"x1": 0, "y1": 1, "x2": 1, "y2": 0, "palindex": 1},
                {"x1": 1, "y1": 0, "x2": 2, "y2": 1, "palindex": 1},
            ],
        )
        n = expand_implied_part_halves(norm)
        self.assertGreaterEqual(n, 1)
        companions = [p for p in norm.part_stitches if p["x"] == 0 and p["y"] == 0]
        self.assertTrue(any(int(p.get("palindex2") or 0) == 5 and int(p.get("direction") or 0) == 2 for p in companions))
        # Idempotent
        self.assertEqual(expand_implied_part_halves(norm), 0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "peak.oxs"
            # Strip companions and re-parse through OXS to ensure parse path expands.
            slim = NormalizedPattern(
                title="Peak",
                width_stitches=4,
                height_stitches=4,
                palette=norm.palette,
                full_stitches=norm.full_stitches,
                part_stitches=[{"x": 1, "y": 0, "palindex1": 5, "palindex2": 0, "direction": 1}],
                backstitches=norm.backstitches,
            )
            write_oxs(path, slim)
            loaded = parse_oxs(path)
        self.assertTrue(any(p["x"] == 0 and p["y"] == 0 and p["palindex2"] == 5 for p in loaded.part_stitches))

    def test_expand_backstitch_neighbor_half(self):
        """Empty cell cut by a diagonal next to a full stitch gets the touching half."""
        from knitarr.parsers.oxs import expand_implied_part_halves

        norm = NormalizedPattern(
            title="Clip",
            width_stitches=4,
            height_stitches=4,
            palette=[
                PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF"),
                PaletteEntry(index=1, number="DMC 310", name="Black", color="000000"),
                PaletteEntry(index=4, number="DMC 3708", name="Pink", color="FF889F"),
            ],
            full_stitches=[{"x": 2, "y": 1, "palindex": 4}],
            part_stitches=[],
            # / diagonal through cell (1,1): BR should pick up colour from full stitch at (2,1).
            backstitches=[{"x1": 1, "y1": 2, "x2": 2, "y2": 1, "palindex": 1}],
        )
        n = expand_implied_part_halves(norm)
        self.assertGreaterEqual(n, 1)
        hit = [p for p in norm.part_stitches if p["x"] == 1 and p["y"] == 1]
        self.assertTrue(any(int(p.get("palindex2") or 0) == 4 and int(p.get("direction") or 0) == 2 for p in hit))

    def test_nearest_dmc_names_gold(self):
        number, name, color = nearest_dmc(parse_hex_rgb("F0C840"))
        self.assertTrue(number.startswith("DMC "))
        self.assertIn(
            name.lower(),
            {
                "topaz",
                "topaz light",
                "topaz medium",
                "old gold medium",
                "tangerine light",
                "yellow dark",
                "golden yellow",
            },
        )
        self.assertTrue(looks_like_dmc_label(number))
        self.assertFalse(looks_like_dmc_label("Colour 3"))
        self.assertEqual(len(color), 6)


if __name__ == "__main__":
    unittest.main()

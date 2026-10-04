"""A4 Chart Export.pdf generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image

from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, parse_oxs
from knitarr.services.chart_export import (
    CHART_EXPORT_FILENAME,
    CHART_PREVIEW_FILENAME,
    write_chart_export_pdf,
    write_chart_preview_image,
)


def _tiny_norm(*, recognition: dict | None = None) -> NormalizedPattern:
    return NormalizedPattern(
        title="Tiny",
        width_stitches=4,
        height_stitches=3,
        fabric_count=14,
        palette=[
            PaletteEntry(0, "cloth", "cloth", "FFFFFF"),
            PaletteEntry(1, "DMC 310", "Black", "000000", stitch_count=2),
            PaletteEntry(2, "DMC 666", "Red", "E31D42", stitch_count=3),
        ],
        full_stitches=[
            {"x": 1, "y": 1, "palindex": 2},
            {"x": 2, "y": 1, "palindex": 2},
            {"x": 1, "y": 2, "palindex": 1},
        ],
        backstitches=[{"x1": 0, "y1": 0, "x2": 4, "y2": 0, "palindex": 1}],
        recognition=recognition,
    )


class ChartExportTests(unittest.TestCase):
    def test_writes_single_a4_page_without_source(self):
        candidates = [
            Path("/app/samples/sample.oxs"),
            Path(__file__).resolve().parent.parent.parent / "samples" / "sample.oxs",
        ]
        samples = next((p for p in candidates if p.is_file()), None)
        if samples is not None:
            norm = parse_oxs(samples)
        else:
            norm = _tiny_norm()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / CHART_EXPORT_FILENAME
            write_chart_export_pdf(out, norm)
            self.assertTrue(out.is_file())
            self.assertEqual(out.name, "Chart Export.pdf")
            self.assertGreater(out.stat().st_size, 500)
            doc = fitz.open(out)
            try:
                self.assertEqual(doc.page_count, 1)
                page = doc[0]
                # A4 at 72dpi ≈ 595 × 842
                self.assertAlmostEqual(page.rect.width, 595.276, delta=1.0)
                self.assertAlmostEqual(page.rect.height, 841.890, delta=1.0)
            finally:
                doc.close()

    def test_writes_two_pages_with_conversion_source(self):
        norm = _tiny_norm(recognition={"symbol_mode": "alphabet"})
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "conversion_source.jpg"
            Image.new("RGB", (80, 60), (200, 100, 50)).save(src, format="JPEG")
            out = Path(tmp) / CHART_EXPORT_FILENAME
            write_chart_export_pdf(out, norm, source_image=src, symbol_mode="alphabet")
            self.assertTrue(out.is_file())
            doc = fitz.open(out)
            try:
                self.assertEqual(doc.page_count, 2)
                self.assertAlmostEqual(doc[0].rect.width, 595.276, delta=1.0)
                self.assertAlmostEqual(doc[0].rect.height, 841.890, delta=1.0)
                self.assertAlmostEqual(doc[1].rect.width, 595.276, delta=1.0)
                text1 = doc[1].get_text()
                self.assertIn("symbols: alphabet", text1)
            finally:
                doc.close()

    def test_writes_chart_preview_jpeg(self):
        norm = NormalizedPattern(
            title="Tiny",
            width_stitches=4,
            height_stitches=3,
            fabric_count=14,
            palette=[
                PaletteEntry(0, "cloth", "cloth", "FFFFFF"),
                PaletteEntry(1, "DMC 310", "Black", "000000", stitch_count=2),
                PaletteEntry(2, "DMC 666", "Red", "E31D42", stitch_count=3),
            ],
            full_stitches=[
                {"x": 1, "y": 1, "palindex": 2},
                {"x": 2, "y": 1, "palindex": 2},
                {"x": 1, "y": 2, "palindex": 1},
            ],
            part_stitches=[{"x": 0, "y": 0, "palindex1": 1, "palindex2": 0, "direction": 1}],
            ornaments=[{"x": 2.5, "y": 1.5, "palindex": 2, "objecttype": "knot"}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / CHART_PREVIEW_FILENAME
            write_chart_preview_image(out, norm, max_side=240)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 200)

            with Image.open(out) as im:
                self.assertEqual(im.format, "JPEG")
                self.assertLessEqual(max(im.size), 240)


if __name__ == "__main__":
    unittest.main()

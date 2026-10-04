"""Symbol-chart recognition tests (existing charts, not photo-to-pattern)."""

from __future__ import annotations

import unittest
from PIL import Image, ImageDraw

from knitarr.services.chart_recognize import recognize_chart_image
from tests.test_chart_detect import make_block_chart


def _draw_mark(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], kind: str, color=(25, 25, 25)) -> None:
    x0, y0, x1, y1 = box
    m = 3
    if kind == "x":
        draw.line([(x0 + m, y0 + m), (x1 - m, y1 - m)], fill=color, width=2)
        draw.line([(x1 - m, y0 + m), (x0 + m, y1 - m)], fill=color, width=2)
    elif kind == "o":
        draw.ellipse([x0 + m, y0 + m, x1 - m, y1 - m], outline=color, width=2)
    elif kind == "+":
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.line([(cx, y0 + m), (cx, y1 - m)], fill=color, width=2)
        draw.line([(x0 + m, cy), (x1 - m, cy)], fill=color, width=2)


def make_symbol_chart(
    cells: list[list[str]],
    *,
    pitch: int = 18,
    margin: int = 12,
    legend: dict[str, tuple[int, int, int]] | None = None,
    paper: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    gh, gw = len(cells), len(cells[0])
    legend = legend or {}
    legend_h = 28 * max(1, len(legend)) + 16 if legend else 0
    width = margin * 2 + gw * pitch + 1
    height = margin * 2 + gh * pitch + 1 + legend_h
    im = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(im)
    for y in range(gh):
        for x in range(gw):
            x0 = margin + x * pitch
            y0 = margin + y * pitch
            kind = cells[y][x]
            if kind:
                _draw_mark(draw, (x0 + 1, y0 + 1, x0 + pitch - 1, y0 + pitch - 1), kind)
    for i in range(gw + 1):
        x = margin + i * pitch
        wline = 3 if i % 10 == 0 else 1
        draw.line([(x, margin), (x, margin + gh * pitch)], fill=(30, 30, 30), width=wline)
    for j in range(gh + 1):
        y = margin + j * pitch
        wline = 3 if j % 10 == 0 else 1
        draw.line([(margin, y), (margin + gw * pitch, y)], fill=(30, 30, 30), width=wline)
    if legend:
        top = margin + gh * pitch + 14
        for i, (kind, color) in enumerate(legend.items()):
            y = top + i * 28
            _draw_mark(draw, (margin, y, margin + 20, y + 20), kind)
            draw.rectangle([margin + 28, y + 2, margin + 56, y + 18], fill=color)
    return im


class ChartRecognizeTests(unittest.TestCase):
    def test_symbol_chart_keeps_grid_and_groups_marks(self):
        cells = [
            ["x", "o", "", "x", "+"],
            ["o", "x", "x", "", "o"],
            ["+", "", "o", "x", "+"],
            ["x", "+", "o", "o", "x"],
            ["", "x", "+", "x", ""],
            ["o", "o", "x", "", "+"],
        ]
        legend = {"x": (220, 40, 40), "o": (40, 90, 200), "+": (40, 160, 80)}
        im = make_symbol_chart(cells, legend=legend)
        result = recognize_chart_image(im, max_width=80, max_colors=12)
        self.assertEqual(result.mode, "symbols")
        self.assertTrue(abs(result.width - 5) <= 1)
        self.assertTrue(abs(result.height - 6) <= 1)
        filled = {(x, y): kind for y, row in enumerate(cells) for x, kind in enumerate(row) if kind}
        self.assertGreaterEqual(len(result.stitches), len(filled) - 2)
        groups: dict[int, list[str]] = {}
        for st in result.stitches:
            if st.x >= 5 or st.y >= 6:
                continue
            kind = cells[st.y][st.x]
            if not kind:
                continue
            groups.setdefault(st.cluster_id, []).append(kind)
        for kinds in groups.values():
            self.assertEqual(len(set(kinds)), 1, kinds)

    def test_symbol_chart_without_legend_still_separates_marks(self):
        cells = [
            ["x", "x", "o", "o"],
            ["x", "o", "o", "x"],
            ["o", "x", "x", "o"],
            ["+", "+", "x", "+"],
            ["+", "x", "+", "o"],
        ]
        im = make_symbol_chart(cells)
        result = recognize_chart_image(im, max_width=80, max_colors=12)
        self.assertEqual(result.mode, "symbols")
        ids = {st.cluster_id for st in result.stitches}
        self.assertGreaterEqual(len(ids), 2)
        self.assertIsNotNone(result.annotated)

    def test_tinted_paper_symbol_chart_stays_symbolic(self):
        cells = [
            ["x", "o", "", "x", "+"],
            ["o", "x", "x", "", "o"],
            ["+", "", "o", "x", "+"],
            ["x", "+", "o", "o", "x"],
            ["", "x", "+", "x", ""],
            ["o", "o", "x", "", "+"],
        ]
        legend = {"x": (220, 40, 40), "o": (40, 90, 200), "+": (40, 160, 80)}
        im = make_symbol_chart(cells, legend=legend, paper=(248, 214, 72))
        result = recognize_chart_image(im, max_width=80, max_colors=12)
        self.assertEqual(result.mode, "symbols")
        ids = {st.cluster_id for st in result.stitches}
        self.assertGreaterEqual(len(ids), 2)

    def test_coloured_cells_with_marks_use_fill_not_ink(self):
        gw, gh, pitch, margin = 10, 8, 16, 10
        fills = {
            "x": (240, 190, 50),
            "o": (40, 90, 200),
            "+": (200, 40, 50),
        }
        layout = [
            ["x", "x", "o", "o", "x"],
            ["x", "+", "o", "x", "+"],
            ["o", "o", "x", "+", "x"],
            ["+", "x", "x", "o", "o"],
            ["x", "o", "+", "x", "o"],
            ["o", "+", "x", "o", "+"],
            ["x", "x", "o", "+", "x"],
            ["+", "o", "x", "x", "o"],
        ]
        width = margin * 2 + 5 * pitch + 1
        height = margin * 2 + gh * pitch + 1
        im = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(im)
        for y, row in enumerate(layout):
            for x, kind in enumerate(row):
                x0 = margin + x * pitch
                y0 = margin + y * pitch
                draw.rectangle([x0 + 1, y0 + 1, x0 + pitch - 1, y0 + pitch - 1], fill=fills[kind])
                _draw_mark(draw, (x0 + 2, y0 + 2, x0 + pitch - 2, y0 + pitch - 2), kind)
        for i in range(6):
            x = margin + i * pitch
            draw.line([(x, margin), (x, margin + gh * pitch)], fill=(30, 30, 30), width=1)
        for j in range(gh + 1):
            y = margin + j * pitch
            draw.line([(margin, y), (margin + 5 * pitch, y)], fill=(30, 30, 30), width=1)
        result = recognize_chart_image(im, max_width=40, max_colors=8)
        self.assertEqual(result.mode, "color_block")
        gold = [st for st in result.stitches if st.x < 5 and st.y < 8 and layout[st.y][st.x] == "x"]
        self.assertTrue(gold)
        r, g, b = gold[0].rgb
        self.assertGreater(r, 160)
        self.assertGreater(g, 100)
        self.assertGreater(r, b)

    def test_white_mark_on_dark_fill_keeps_fill(self):
        gw, gh, pitch, margin = 8, 6, 16, 8
        fill = (40, 90, 200)
        width = margin * 2 + gw * pitch + 1
        height = margin * 2 + gh * pitch + 1
        im = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(im)
        for y in range(gh):
            for x in range(gw):
                x0 = margin + x * pitch
                y0 = margin + y * pitch
                draw.rectangle([x0 + 1, y0 + 1, x0 + pitch - 1, y0 + pitch - 1], fill=fill)
                _draw_mark(draw, (x0 + 2, y0 + 2, x0 + pitch - 2, y0 + pitch - 2), "x", color=(250, 250, 250))
        for i in range(gw + 1):
            x = margin + i * pitch
            draw.line([(x, margin), (x, margin + gh * pitch)], fill=(20, 20, 20), width=1)
        for j in range(gh + 1):
            y = margin + j * pitch
            draw.line([(margin, y), (margin + gw * pitch, y)], fill=(20, 20, 20), width=1)
        result = recognize_chart_image(im, max_width=40, max_colors=6)
        self.assertEqual(result.mode, "color_block")
        self.assertGreater(len(result.stitches), 20)
        r, g, b = result.stitches[0].rgb
        self.assertGreater(b, r)
        self.assertGreater(b, 120)

    def test_colour_block_chart_stays_on_colour_path(self):
        im, _ = make_block_chart(12, 8, pitch=10)
        result = recognize_chart_image(im, max_width=40, max_colors=12)
        self.assertEqual(result.mode, "color_block")
        self.assertTrue(abs(result.width - 12) <= 1)
        self.assertTrue(abs(result.height - 8) <= 1)
        self.assertGreater(len(result.stitches), 20)

    def test_empty_cells_are_not_stitches(self):
        cells = [
            ["x", "", "", "x"],
            ["", "", "", ""],
            ["x", "", "o", ""],
            ["", "o", "", "x"],
        ]
        im = make_symbol_chart(cells)
        result = recognize_chart_image(im, max_width=40, max_colors=8)
        occupied = {(st.x, st.y) for st in result.stitches}
        self.assertNotIn((1, 1), occupied)

    def test_confidence_is_recorded(self):
        cells = [["x", "o", "x"], ["o", "x", "o"], ["x", "o", "x"], ["+", "x", "+"]]
        im = make_symbol_chart(cells)
        result = recognize_chart_image(im, max_width=40, max_colors=8)
        self.assertTrue(result.stitches)
        self.assertTrue(all(0.0 <= st.confidence <= 1.0 for st in result.stitches))


if __name__ == "__main__":
    unittest.main()

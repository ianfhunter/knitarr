"""Synthetic-chart tests for grid detection."""

from __future__ import annotations

import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from knitarr.services.chart_detect import detect_grid_spec, extract_chart_grid


PALETTE = [
    (220, 40, 40),
    (40, 90, 200),
    (240, 200, 40),
    (40, 160, 80),
    (160, 70, 180),
    (255, 255, 255),
]


def make_block_chart(
    gw: int,
    gh: int,
    *,
    pitch: int = 10,
    line: int = 1,
    bold_every: int = 0,
    margin: int = 0,
    seed: int = 0,
) -> tuple[Image.Image, np.ndarray]:
    rng = np.random.default_rng(seed)
    cells = rng.integers(0, len(PALETTE) - 1, size=(gh, gw))
    cells[rng.random((gh, gw)) < 0.18] = len(PALETTE) - 1
    width = margin * 2 + gw * pitch + line
    height = margin * 2 + gh * pitch + line
    im = Image.new("RGB", (width, height), (255, 255, 255))
    px = im.load()
    for y in range(gh):
        for x in range(gw):
            colour = PALETTE[int(cells[y, x])]
            x0 = margin + x * pitch
            y0 = margin + y * pitch
            for yy in range(y0 + line, y0 + pitch):
                for xx in range(x0 + line, x0 + pitch):
                    px[xx, yy] = colour
    draw = ImageDraw.Draw(im)
    for i in range(gw + 1):
        x = margin + i * pitch
        width_line = 3 if bold_every and i % bold_every == 0 else line
        draw.line([(x, margin), (x, margin + gh * pitch)], fill=(30, 30, 30), width=width_line)
    for j in range(gh + 1):
        y = margin + j * pitch
        width_line = 3 if bold_every and j % bold_every == 0 else line
        draw.line([(margin, y), (margin + gw * pitch, y)], fill=(30, 30, 30), width=width_line)
    return im, cells


def _near(a: int, b: int, tol: int = 1) -> bool:
    return abs(a - b) <= tol


class ChartDetectTests(unittest.TestCase):
    def test_simple_coloured_grid(self):
        im, _ = make_block_chart(12, 8, pitch=10)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 12))
        self.assertTrue(_near(spec.height_stitches, 8))
        grid = extract_chart_grid(im, max_width=120, max_colors=12)
        self.assertEqual(grid.source, "grid")
        self.assertTrue(_near(grid.width_stitches, 12))
        self.assertTrue(_near(grid.height_stitches, 8))

    def test_coloured_ten_count_lines(self):
        gw, gh, pitch, margin = 24, 16, 8, 10
        rng = np.random.default_rng(4)
        cells = rng.integers(0, 4, size=(gh, gw))
        width = margin * 2 + gw * pitch + 1
        height = margin * 2 + gh * pitch + 1
        im = Image.new("RGB", (width, height), (255, 255, 255))
        px = im.load()
        colours = PALETTE[:4]
        for y in range(gh):
            for x in range(gw):
                colour = colours[int(cells[y, x])]
                x0 = margin + x * pitch
                y0 = margin + y * pitch
                for yy in range(y0 + 1, y0 + pitch):
                    for xx in range(x0 + 1, x0 + pitch):
                        px[xx, yy] = colour
        draw = ImageDraw.Draw(im)
        for i in range(gw + 1):
            x = margin + i * pitch
            colour = (200, 30, 30) if i % 10 == 0 else (40, 40, 40)
            draw.line([(x, margin), (x, margin + gh * pitch)], fill=colour, width=2 if i % 10 == 0 else 1)
        for j in range(gh + 1):
            y = margin + j * pitch
            colour = (200, 30, 30) if j % 10 == 0 else (40, 40, 40)
            draw.line([(margin, y), (margin + gw * pitch, y)], fill=colour, width=2 if j % 10 == 0 else 1)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, gw, 2))
        self.assertTrue(_near(spec.height_stitches, gh, 2))

    def test_ten_count_bold_lines_keep_stitch_pitch(self):
        im, _ = make_block_chart(30, 20, pitch=8, bold_every=10)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 30, 2))
        self.assertTrue(_near(spec.height_stitches, 20, 2))
        self.assertGreater(spec.pitch_x, 6.5)
        self.assertLess(spec.pitch_x, 9.5)

    def test_margin_is_not_counted_as_stitches(self):
        im, _ = make_block_chart(30, 20, pitch=8, bold_every=10, margin=20)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 30, 2))
        self.assertTrue(_near(spec.height_stitches, 20, 2))
        self.assertGreater(spec.origin_x, 10)
        self.assertGreater(spec.origin_y, 10)

    def test_small_chart_with_margin(self):
        im, _ = make_block_chart(8, 8, pitch=12, margin=5)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 8, 1))
        self.assertTrue(_near(spec.height_stitches, 8, 1))

    def test_wide_chart_pitch(self):
        im, _ = make_block_chart(40, 12, pitch=6, bold_every=10, margin=8)
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 40, 2))
        self.assertTrue(_near(spec.height_stitches, 12, 2))

    def test_detected_grid_is_not_downscaled(self):
        im, _ = make_block_chart(36, 28, pitch=7)
        grid = extract_chart_grid(im, max_width=20, max_colors=16)
        self.assertEqual(grid.source, "grid")
        self.assertTrue(_near(grid.width_stitches, 36, 2))
        self.assertTrue(_near(grid.height_stitches, 28, 2))

    def test_noisy_scan_still_finds_grid(self):
        im, _ = make_block_chart(16, 12, pitch=9, bold_every=10, margin=6)
        arr = np.asarray(im).astype(np.int16)
        rng = np.random.default_rng(1)
        arr += rng.integers(-12, 13, size=arr.shape)
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 16, 2))
        self.assertTrue(_near(spec.height_stitches, 12, 2))

    def test_slight_blur_still_finds_grid(self):
        im, _ = make_block_chart(18, 14, pitch=10, bold_every=10)
        im = im.filter(ImageFilter.GaussianBlur(radius=0.6))
        spec = detect_grid_spec(np.asarray(im))
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(_near(spec.width_stitches, 18, 2))
        self.assertTrue(_near(spec.height_stitches, 14, 2))

    def test_smooth_gradient_is_not_a_chart_grid(self):
        arr = np.zeros((180, 220, 3), dtype=np.uint8)
        yy, xx = np.mgrid[0:180, 0:220]
        arr[..., 0] = (80 + xx * 0.6).astype(np.uint8)
        arr[..., 1] = (40 + yy * 0.8).astype(np.uint8)
        arr[..., 2] = 120
        spec = detect_grid_spec(arr)
        self.assertIsNone(spec)
        grid = extract_chart_grid(Image.fromarray(arr), max_width=80, max_colors=12)
        self.assertNotEqual(grid.source, "grid")

    def test_pixel_art_uses_block_sampling(self):
        tiles = np.array(
            [
                [[200, 30, 30], [30, 30, 200], [255, 255, 255], [30, 160, 40]],
                [[30, 30, 200], [200, 30, 30], [30, 160, 40], [255, 255, 255]],
                [[30, 160, 40], [255, 255, 255], [200, 30, 30], [30, 30, 200]],
                [[255, 255, 255], [30, 160, 40], [30, 30, 200], [200, 30, 30]],
            ],
            dtype=np.uint8,
        )
        big = np.repeat(np.repeat(tiles, 8, 0), 8, 1)
        grid = extract_chart_grid(Image.fromarray(big), max_width=120, max_colors=8)
        self.assertTrue(_near(grid.width_stitches, 4, 0))
        self.assertTrue(_near(grid.height_stitches, 4, 0))

    def test_sampled_colours_stay_in_family(self):
        im, cells = make_block_chart(10, 8, pitch=11, seed=3)
        grid = extract_chart_grid(im, max_width=40, max_colors=12)
        self.assertEqual(grid.source, "grid")
        # A known red stitch should stay reddish after sampling + quantize.
        red_pos = np.argwhere(cells == 0)
        self.assertGreater(len(red_pos), 0)
        reddish = 0
        checked = 0
        for y, x in red_pos:
            y, x = int(y), int(x)
            if y >= grid.height_stitches or x >= grid.width_stitches:
                continue
            r, g, b = (int(c) for c in grid.cells[y, x])
            if min(r, g, b) >= 248:
                continue
            checked += 1
            if r > g and r > b:
                reddish += 1
        self.assertGreater(checked, 0)
        self.assertGreaterEqual(reddish, max(1, checked // 2))


if __name__ == "__main__":
    unittest.main()

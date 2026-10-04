"""Read an existing chart (grid + symbols/legend), not a photo-to-pattern generator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from knitarr.services.chart_detect import (
    ChartGrid,
    GridSpec,
    _quantize_cell_colors,
    _sample_grid,
    _trim_empty_border,
    extract_chart_grid,
    locate_chart_grid,
)
from knitarr.services.chart_symbols import (
    CellPatch,
    SymbolCluster,
    assign_cells,
    chart_looks_symbolic,
    chroma,
    cluster_symbols,
    extract_cell_patches,
    match_legend_swatches,
)

log = logging.getLogger(__name__)

_LOW_CONF = 0.70
_PLACEHOLDERS = [
    (220, 40, 40),
    (40, 90, 200),
    (240, 200, 40),
    (40, 160, 80),
    (160, 70, 180),
    (30, 160, 180),
    (200, 110, 40),
    (90, 90, 90),
    (180, 60, 120),
    (80, 130, 60),
]


@dataclass
class RecognizedStitch:
    x: int
    y: int
    rgb: tuple[int, int, int]
    confidence: float
    cluster_id: int
    kind: str = "full"


@dataclass
class RecognitionResult:
    width: int
    height: int
    stitches: list[RecognizedStitch]
    source: str
    mode: str
    clusters: int = 0
    low_confidence: int = 0
    annotated: Image.Image | None = None
    labels: dict[int, str] = field(default_factory=dict)


def _color_grid_to_result(grid: ChartGrid) -> RecognitionResult:
    stitches: list[RecognizedStitch] = []
    for y in range(grid.height_stitches):
        for x in range(grid.width_stitches):
            r, g, b = (int(v) for v in grid.cells[y, x])
            if min(r, g, b) >= 248:
                continue
            stitches.append(RecognizedStitch(x=x, y=y, rgb=(r, g, b), confidence=0.85, cluster_id=-1))
    return RecognitionResult(
        width=grid.width_stitches,
        height=grid.height_stitches,
        stitches=stitches,
        source=grid.source,
        mode="color_block" if grid.source == "grid" else grid.source,
    )


def _cluster_color(cl: SymbolCluster, legend: dict[int, tuple[int, int, int]], index: int) -> tuple[int, int, int]:
    if cl.cluster_id in legend:
        return legend[cl.cluster_id]
    if cl.color and chroma(cl.color) >= 22:
        return cl.color
    return _PLACEHOLDERS[index % len(_PLACEHOLDERS)]


def _annotate(
    rgb: np.ndarray,
    spec: GridSpec,
    assigned: list[tuple[CellPatch, int | None, float]],
    colors: dict[int, tuple[int, int, int]],
) -> Image.Image:
    im = Image.fromarray(rgb.copy(), mode="RGB")
    draw = ImageDraw.Draw(im)
    for cx in range(spec.width_stitches + 1):
        x = spec.origin_x + cx * spec.pitch_x
        y0 = spec.origin_y
        y1 = spec.origin_y + spec.height_stitches * spec.pitch_y
        draw.line([(x, y0), (x, y1)], fill=(40, 40, 40), width=1)
    for cy in range(spec.height_stitches + 1):
        y = spec.origin_y + cy * spec.pitch_y
        x0 = spec.origin_x
        x1 = spec.origin_x + spec.width_stitches * spec.pitch_x
        draw.line([(x0, y), (x1, y)], fill=(40, 40, 40), width=1)
    for patch, cid, conf in assigned:
        if cid is None:
            continue
        x0 = spec.origin_x + patch.x * spec.pitch_x
        y0 = spec.origin_y + patch.y * spec.pitch_y
        x1 = x0 + spec.pitch_x
        y1 = y0 + spec.pitch_y
        color = colors.get(cid, (0, 0, 0))
        outline = (220, 30, 30) if conf < _LOW_CONF else color
        draw.rectangle([x0 + 2, y0 + 2, x1 - 2, y1 - 2], outline=outline, width=2)
        draw.text((x0 + 3, y0 + 2), str(cid + 1), fill=outline)
    return im


def _recognize_symbols(rgb: np.ndarray, spec: GridSpec, patches: list[CellPatch]) -> RecognitionResult:
    clusters = cluster_symbols(patches)
    if not clusters:
        raise ValueError("No recurring symbols found in chart cells")
    legend = match_legend_swatches(rgb, spec, clusters)
    colors = {cl.cluster_id: _cluster_color(cl, legend, i) for i, cl in enumerate(clusters)}
    labels = {cl.cluster_id: cl.label for cl in clusters}
    assigned = assign_cells(patches, clusters)
    stitches: list[RecognizedStitch] = []
    low = 0
    for patch, cid, conf in assigned:
        if cid is None:
            if patch.ink_frac >= 0.028:
                low += 1
            continue
        if conf < _LOW_CONF:
            low += 1
        stitches.append(
            RecognizedStitch(
                x=patch.x,
                y=patch.y,
                rgb=colors[cid],
                confidence=float(conf),
                cluster_id=cid,
            )
        )
    log.info(
        "Symbol chart: %s clusters, %s stitches, %s legend matches, %s low-confidence",
        len(clusters),
        len(stitches),
        len(legend),
        low,
    )
    return RecognitionResult(
        width=spec.width_stitches,
        height=spec.height_stitches,
        stitches=stitches,
        source="symbols",
        mode="symbols",
        clusters=len(clusters),
        low_confidence=low,
        annotated=_annotate(rgb, spec, assigned, colors),
        labels=labels,
    )


def recognize_chart_image(
    im: Image.Image,
    *,
    max_width: int,
    max_height: int | None = None,
    max_colors: int,
) -> RecognitionResult:
    """Reconstruct an existing chart. Photos without a grid fall back to tiling."""
    max_height = max_height or max_width
    located = locate_chart_grid(im)
    if located:
        spec, rgb = located
        patches = extract_cell_patches(rgb, spec)
        if chart_looks_symbolic(patches):
            try:
                return _recognize_symbols(rgb, spec, patches)
            except ValueError as e:
                log.info("Symbol recognition failed (%s); sampling cell colours", e)
        try:
            grid = _trim_empty_border(_sample_grid(rgb, spec))
            grid = _quantize_cell_colors(grid, max_colors)
            result = _color_grid_to_result(grid)
            result.annotated = _annotate_color_grid(rgb, spec, grid)
            return result
        except ValueError:
            pass
    grid = extract_chart_grid(im, max_width=max_width, max_height=max_height, max_colors=max_colors)
    return _color_grid_to_result(grid)


def _annotate_color_grid(rgb: np.ndarray, spec: GridSpec, grid: ChartGrid) -> Image.Image:
    im = Image.fromarray(rgb.copy(), mode="RGB")
    draw = ImageDraw.Draw(im)
    for cy in range(min(grid.height_stitches, spec.height_stitches)):
        for cx in range(min(grid.width_stitches, spec.width_stitches)):
            r, g, b = (int(v) for v in grid.cells[cy, cx])
            if min(r, g, b) >= 248:
                continue
            x0 = spec.origin_x + cx * spec.pitch_x
            y0 = spec.origin_y + cy * spec.pitch_y
            draw.rectangle(
                [x0 + 1, y0 + 1, x0 + spec.pitch_x - 1, y0 + spec.pitch_y - 1],
                outline=(r, g, b),
                width=2,
            )
    return im

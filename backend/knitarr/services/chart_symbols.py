"""Extract stitch cells and cluster recurring chart symbols."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from knitarr.services.chart_detect import GridSpec, _cell_fill_color, _gray

_CELL = 24
_EMPTY_FRAC = 0.028
_FILLED_FRAC = 0.62
_CLUSTER_NCC = 0.76
_ASSIGN_NCC = 0.62
_MERGE_NCC = 0.88


@dataclass
class CellPatch:
    x: int
    y: int
    ink: np.ndarray
    ink_frac: float
    ink_rgb: tuple[int, int, int] | None
    fill_rgb: tuple[int, int, int] | None
    rgb: np.ndarray


@dataclass
class SymbolCluster:
    cluster_id: int
    template: np.ndarray
    members: list[CellPatch] = field(default_factory=list)
    color: tuple[int, int, int] | None = None
    label: str = ""


def _resize_gray(arr: np.ndarray, size: int) -> np.ndarray:
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")
    return np.asarray(im.resize((size, size), Image.Resampling.BILINEAR), dtype=np.float32)


def _ink_mask(
    patch: np.ndarray,
) -> tuple[np.ndarray, float, tuple[int, int, int] | None, tuple[int, int, int] | None]:
    if patch.size == 0:
        return np.zeros((_CELL, _CELL), dtype=np.float32), 0.0, None, None
    fill = _cell_fill_color(patch)
    gray = _gray(patch)
    # Drop a thin border so leftover grid ink does not become the symbol.
    if min(gray.shape) >= 6:
        gray = gray[1:-1, 1:-1]
        patch = patch[1:-1, 1:-1]
    thresh = min(155.0, float(np.percentile(gray, 35)) + 18.0)
    ink = gray < thresh
    frac = float(ink.mean())
    ink_f = _resize_gray(ink.astype(np.float32) * 255.0, _CELL) / 255.0
    color = None
    if ink.any():
        samples = patch[ink]
        med = np.median(samples.reshape(-1, 3), axis=0)
        color = (int(med[0]), int(med[1]), int(med[2]))
    return ink_f, frac, color, fill


def extract_cell_patches(rgb: np.ndarray, spec: GridSpec) -> list[CellPatch]:
    h, w = rgb.shape[:2]
    inset = 0.16
    patches: list[CellPatch] = []
    for cy in range(spec.height_stitches):
        y0 = spec.origin_y + cy * spec.pitch_y
        iy0 = int(round(y0 + spec.pitch_y * inset))
        iy1 = int(round(y0 + spec.pitch_y * (1.0 - inset)))
        iy0 = max(0, min(h - 1, iy0))
        iy1 = max(iy0 + 1, min(h, iy1))
        for cx in range(spec.width_stitches):
            x0 = spec.origin_x + cx * spec.pitch_x
            ix0 = int(round(x0 + spec.pitch_x * inset))
            ix1 = int(round(x0 + spec.pitch_x * (1.0 - inset)))
            ix0 = max(0, min(w - 1, ix0))
            ix1 = max(ix0 + 1, min(w, ix1))
            crop = rgb[iy0:iy1, ix0:ix1]
            ink, frac, ink_color, fill = _ink_mask(crop)
            patches.append(
                CellPatch(x=cx, y=cy, ink=ink, ink_frac=frac, ink_rgb=ink_color, fill_rgb=fill, rgb=crop)
            )
    return patches


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    av = a.reshape(-1).astype(np.float64)
    bv = b.reshape(-1).astype(np.float64)
    av = av - av.mean()
    bv = bv - bv.mean()
    na = float(np.linalg.norm(av))
    nb = float(np.linalg.norm(bv))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    return float(np.dot(av, bv) / (na * nb))


def _fill_is_paper(rgb: tuple[int, int, int] | None) -> bool:
    if rgb is None:
        return True
    return min(rgb) >= 236 and chroma(rgb) < 20


def _fill_spread(patches: list[CellPatch]) -> float | None:
    fills = [p.fill_rgb for p in patches if p.fill_rgb is not None]
    if len(fills) < 12:
        return None
    return float(np.array(fills, dtype=np.float32).std(axis=0).mean())


def chart_looks_symbolic(patches: list[CellPatch]) -> bool:
    """True for symbol charts on paper (including tinted paper), not colour-filled cells."""
    marked = [p for p in patches if p.ink_frac >= _EMPTY_FRAC]
    if len(marked) < 6:
        return False
    colour_fills = sum(1 for p in marked if not _fill_is_paper(p.fill_rgb))
    paper_fills = len(marked) - colour_fills
    spread = _fill_spread(patches)
    fills = [p.fill_rgb for p in patches if p.fill_rgb is not None]
    fill_luma = 255.0
    if fills:
        med = np.median(np.array(fills, dtype=np.float32), axis=0)
        fill_luma = float(0.299 * med[0] + 0.587 * med[1] + 0.114 * med[2])
    # Cream/yellow paper is a light, even tint — not a colour-block chart.
    tinted_paper = spread is not None and spread < 16.0 and fill_luma >= 170.0
    if colour_fills >= 8 and colour_fills > paper_fills and not tinted_paper:
        return False
    symbols = sum(1 for p in patches if _EMPTY_FRAC <= p.ink_frac < _FILLED_FRAC)
    filled = sum(1 for p in patches if p.ink_frac >= _FILLED_FRAC)
    if filled > symbols * 1.15:
        return False
    return symbols >= max(6, filled)


def _mean_template(members: list[CellPatch]) -> np.ndarray:
    stack = np.stack([m.ink for m in members], axis=0)
    return stack.mean(axis=0).astype(np.float32)


def _cluster_sample(patches: list[CellPatch]) -> list[CellPatch]:
    nonempty = [p for p in patches if p.ink_frac >= _EMPTY_FRAC]
    if len(nonempty) <= 900:
        return nonempty
    step = max(1, len(nonempty) // 900)
    return nonempty[::step]


def cluster_symbols(patches: list[CellPatch]) -> list[SymbolCluster]:
    sample = _cluster_sample(patches)
    clusters: list[SymbolCluster] = []
    for patch in sample:
        best_i, best_s = -1, -1.0
        for i, cl in enumerate(clusters):
            score = ncc(patch.ink, cl.template)
            if score > best_s:
                best_s, best_i = score, i
        if best_i >= 0 and best_s >= _CLUSTER_NCC:
            clusters[best_i].members.append(patch)
            if len(clusters[best_i].members) % 8 == 0:
                clusters[best_i].template = _mean_template(clusters[best_i].members)
        else:
            clusters.append(
                SymbolCluster(cluster_id=len(clusters), template=patch.ink.copy(), members=[patch])
            )
    for cl in clusters:
        cl.template = _mean_template(cl.members)

    merged: list[SymbolCluster] = []
    for cl in sorted(clusters, key=lambda c: -len(c.members)):
        mate = None
        for existing in merged:
            if ncc(cl.template, existing.template) >= _MERGE_NCC:
                mate = existing
                break
        if mate is None:
            merged.append(cl)
        else:
            mate.members.extend(cl.members)
            mate.template = _mean_template(mate.members)
    for i, cl in enumerate(merged):
        cl.cluster_id = i
        cl.label = f"Symbol {i + 1}"
        fills = [m.fill_rgb for m in cl.members if m.fill_rgb and not _fill_is_paper(m.fill_rgb)]
        inks = [m.ink_rgb for m in cl.members if m.ink_rgb]
        chosen = fills or inks
        if chosen:
            med = np.median(np.array(chosen), axis=0)
            cl.color = (int(med[0]), int(med[1]), int(med[2]))
    return merged


def assign_cells(
    patches: list[CellPatch], clusters: list[SymbolCluster]
) -> list[tuple[CellPatch, int | None, float]]:
    assigned: list[tuple[CellPatch, int | None, float]] = []
    for patch in patches:
        if patch.ink_frac < _EMPTY_FRAC:
            assigned.append((patch, None, 1.0))
            continue
        best_i, best_s = -1, -1.0
        for cl in clusters:
            score = ncc(patch.ink, cl.template)
            if score > best_s:
                best_s, best_i = score, cl.cluster_id
        if best_i < 0 or best_s < _ASSIGN_NCC:
            assigned.append((patch, None, max(0.0, best_s)))
        else:
            assigned.append((patch, best_i, best_s))
    return assigned


def _region_ink(rgb: np.ndarray) -> np.ndarray:
    gray = _gray(rgb)
    return (gray < 155).astype(np.float32)


def _best_template_hit(ink: np.ndarray, template: np.ndarray, *, stride: int = 2) -> tuple[int, int, float] | None:
    th, tw = template.shape
    h, w = ink.shape
    if h < th or w < tw:
        return None
    best_s, best = -1.0, None
    for y in range(0, h - th + 1, stride):
        for x in range(0, w - tw + 1, stride):
            score = ncc(ink[y : y + th, x : x + tw], template)
            if score > best_s:
                best_s, best = score, (x, y)
    if best is None or best_s < 0.7:
        return None
    return best[0], best[1], best_s


def _swatch_near(rgb: np.ndarray, x: int, y: int, tw: int, th: int) -> tuple[int, int, int] | None:
    h, w = rgb.shape[:2]
    y0 = max(0, y - 6)
    y1 = min(h, y + th + 6)
    x0 = min(w - 1, x + tw + 2)
    x1 = min(w, x0 + 80)
    roi = rgb[y0:y1, x0:x1]
    if roi.size < 30:
        return None
    chroma = roi.max(axis=2).astype(np.int16) - roi.min(axis=2).astype(np.int16)
    lum = roi.mean(axis=2)
    colorful = chroma > 28
    if float(colorful.mean()) >= 0.08:
        samples = roi[colorful]
    else:
        solid = (lum < 240) & (chroma <= 28)
        if float(solid.mean()) < 0.1:
            return None
        samples = roi[solid]
    med = np.median(samples.reshape(-1, 3), axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def _legend_regions(rgb: np.ndarray, spec: GridSpec) -> list[tuple[np.ndarray, int, int]]:
    h, w = rgb.shape[:2]
    gx0 = max(0, int(spec.origin_x) - 8)
    gy0 = max(0, int(spec.origin_y) - 8)
    gx1 = min(w, int(spec.origin_x + spec.width_stitches * spec.pitch_x) + 8)
    gy1 = min(h, int(spec.origin_y + spec.height_stitches * spec.pitch_y) + 8)
    regions: list[tuple[np.ndarray, int, int]] = []
    if gy1 < h - 16:
        regions.append((rgb[gy1:h, gx0:gx1] if gx1 > gx0 else rgb[gy1:h, :], gx0 if gx1 > gx0 else 0, gy1))
    if gx1 < w - 16:
        regions.append((rgb[gy0:gy1, gx1:w] if gy1 > gy0 else rgb[:, gx1:w], gx1, gy0 if gy1 > gy0 else 0))
    if gy0 > 16:
        regions.append((rgb[0:gy0, gx0:gx1] if gx1 > gx0 else rgb[0:gy0, :], gx0 if gx1 > gx0 else 0, 0))
    return [r for r in regions if r[0].size > 400]


def match_legend_swatches(
    rgb: np.ndarray, spec: GridSpec, clusters: list[SymbolCluster]
) -> dict[int, tuple[int, int, int]]:
    """Map cluster id → thread colour from a legend symbol + swatch pair."""
    regions = _legend_regions(rgb, spec)
    if not regions:
        return {}
    found: dict[int, tuple[int, int, int]] = {}
    for cl in clusters:
        best_color = None
        best_score = -1.0
        for region, _ox, _oy in regions:
            ink = _region_ink(region)
            hit = _best_template_hit(ink, cl.template)
            if hit is None:
                continue
            x, y, score = hit
            color = _swatch_near(region, x, y, cl.template.shape[1], cl.template.shape[0])
            if color is not None and score > best_score:
                best_score, best_color = score, color
        if best_color is not None:
            found[cl.cluster_id] = best_color
    return found


def chroma(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)

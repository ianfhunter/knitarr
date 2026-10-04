"""Detect gridded cross-stitch chart layout and sample one colour per cell."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

_BACKGROUND_LUM = 248
_ANALYSIS_MAX_SIDE = 1600
_ABSURD_GRID_SIDE = 800
_MIN_STITCHES = 4
_MIN_CONFIDENCE = 0.16
_MIN_LINE_STRENGTH = 10.0


@dataclass
class GridSpec:
    pitch_x: float
    pitch_y: float
    origin_x: float
    origin_y: float
    width_stitches: int
    height_stitches: int
    confidence: float


@dataclass
class ChartGrid:
    width_stitches: int
    height_stitches: int
    cells: np.ndarray  # RGB (height, width, 3); white = empty / cloth
    source: str = "grid"


def _rgb_array(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGB"), dtype=np.uint8)


def _gray(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0].astype(np.float32), rgb[..., 1].astype(np.float32), rgb[..., 2].astype(np.float32)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _thin_line_profile(gray: np.ndarray, axis: int) -> np.ndarray:
    """Evidence of thin dark grid lines, not colour-block edges or filled cells."""
    g = gray.astype(np.float32)
    evidence = np.zeros_like(g)
    local_min = np.zeros(g.shape, dtype=bool)
    if axis == 0:
        evidence[1:-1] = np.clip(g[:-2] + g[2:] - 2.0 * g[1:-1], 0, None)
        # 1–3px ink is darker than the nearby cells, unlike a colour-block boundary.
        local_min[2:-2] = g[2:-2] < 0.5 * (g[:-4] + g[4:]) - 8.0
        evidence *= local_min
        p50 = np.median(evidence, axis=1)
        p80 = np.percentile(evidence, 80, axis=1)
        return (0.35 * p50 + 0.65 * p80).astype(np.float32)
    evidence[:, 1:-1] = np.clip(g[:, :-2] + g[:, 2:] - 2.0 * g[:, 1:-1], 0, None)
    local_min[:, 2:-2] = g[:, 2:-2] < 0.5 * (g[:, :-4] + g[:, 4:]) - 8.0
    evidence *= local_min
    p50 = np.median(evidence, axis=0)
    p80 = np.percentile(evidence, 80, axis=0)
    return (0.35 * p50 + 0.65 * p80).astype(np.float32)


def _local_peaks(profile: np.ndarray, min_sep: int, min_height: float | None = None) -> np.ndarray:
    n = len(profile)
    if n < 3:
        return np.array([], dtype=np.int32)
    if min_height is None:
        min_height = max(float(np.percentile(profile, 58)), float(profile.mean() + 0.15 * (profile.std() + 1e-6)))
    raw: list[int] = []
    for i in range(1, n - 1):
        if profile[i] >= profile[i - 1] and profile[i] > profile[i + 1] and profile[i] >= min_height:
            raw.append(i)
    if not raw:
        return np.array([], dtype=np.int32)
    raw.sort(key=lambda i: float(profile[i]), reverse=True)
    kept: list[int] = []
    min_sep = max(2, min_sep)
    for i in raw:
        if all(abs(i - j) >= min_sep for j in kept):
            kept.append(i)
    return np.array(sorted(kept), dtype=np.int32)


def _autocorr_period_candidates(profile: np.ndarray, pmin: int, pmax: int, top_n: int = 8) -> list[tuple[float, float]]:
    x = profile.astype(np.float64)
    x = x - x.mean()
    n = len(x)
    if x.std() < 1e-6 or n < pmin * 4:
        return []
    win = np.hanning(n)
    nfft = 1 << int(np.ceil(np.log2(max(2 * n, 256))))
    spec = np.fft.rfft(x * win, n=nfft)
    mag = np.abs(spec)
    spec = spec * (mag + 1e-12) ** -0.5
    ac = np.fft.irfft(spec * np.conjugate(spec), n=nfft)[:n]
    if ac[0] > 0:
        ac = ac / ac[0]
    lo = max(pmin, 2)
    hi = min(pmax, n // 3)
    if hi <= lo + 1:
        return []
    cands: list[tuple[float, float]] = []
    for lag in range(lo, hi + 1):
        if ac[lag] >= ac[lag - 1] and (lag + 1 >= n or ac[lag] > ac[lag + 1]) and ac[lag] > 0.07:
            cands.append((float(lag), float(ac[lag])))
    cands.sort(key=lambda t: -t[1])
    return cands[:top_n]


def _fft_period_candidates(profile: np.ndarray, pmin: int, pmax: int, top_n: int = 6) -> list[tuple[float, float]]:
    x = profile.astype(np.float64)
    x = x - x.mean()
    n = len(x)
    if x.std() < 1e-6:
        return []
    nfft = 1 << int(np.ceil(np.log2(max(n * 4, 256))))
    spec = np.fft.rfft(x * np.hanning(n), n=nfft)
    power = spec.real**2 + spec.imag**2
    freqs = np.fft.rfftfreq(nfft)
    valid = (freqs >= 1.0 / pmax) & (freqs <= 1.0 / max(pmin, 1)) & (np.arange(len(freqs)) > 0)
    if not np.any(valid):
        return []
    work = np.where(valid, power, 0.0)
    baseline = float(np.median(power[valid])) + 1e-8
    idxs: list[int] = []
    for i in range(1, len(work) - 1):
        if work[i] >= work[i - 1] and work[i] > work[i + 1] and work[i] > 0:
            idxs.append(i)
    idxs.sort(key=lambda i: work[i], reverse=True)
    out: list[tuple[float, float]] = []
    seen: list[float] = []
    for i in idxs:
        pitch = 1.0 / float(freqs[i])
        if any(abs(pitch - s) < 0.55 for s in seen):
            continue
        out.append((pitch, float(work[i] / baseline)))
        seen.append(pitch)
        if len(out) >= top_n:
            break
    return out


def _gap_period_candidates(profile: np.ndarray, pmin: int, pmax: int) -> list[tuple[float, float]]:
    peaks = _local_peaks(profile, min_sep=pmin)
    if len(peaks) < 4:
        return []
    gaps = np.diff(peaks.astype(np.float64))
    usable = gaps[(gaps >= pmin) & (gaps <= pmax)]
    if len(usable) == 0:
        return []
    out = [(float(np.median(usable)), 1.0)]
    small = usable[usable <= np.median(usable) * 1.35]
    if len(small):
        out.append((float(np.median(small)), 0.9))
    return out


def _unique_pitches(items: list[tuple[float, float]]) -> list[tuple[float, float]]:
    items = sorted(items, key=lambda t: -t[1])
    out: list[tuple[float, float]] = []
    for pitch, score in items:
        if any(abs(pitch - p) < 0.45 for p, _ in out):
            continue
        out.append((pitch, score))
    return out


def _profile_has_lines(profile: np.ndarray) -> bool:
    return float(np.percentile(profile, 95)) >= _MIN_LINE_STRENGTH


def _collect_pitch_candidates(profile: np.ndarray, pmin: int, pmax: int) -> list[tuple[float, float]]:
    if not _profile_has_lines(profile):
        return []
    cands = []
    cands.extend(_autocorr_period_candidates(profile, pmin, pmax))
    cands.extend(_fft_period_candidates(profile, pmin, pmax))
    cands.extend(_gap_period_candidates(profile, pmin, pmax))
    return _unique_pitches(cands)


def _harmonic_divisors(pitch: float, pmin: float) -> list[float]:
    out = [pitch]
    for d in (2, 3, 4, 5, 8, 10):
        q = pitch / d
        if q >= pmin - 0.2:
            out.append(q)
    return out


def _refine_pitch(peaks: np.ndarray, pitch: float) -> float:
    if len(peaks) < 3:
        return pitch
    gaps = np.diff(peaks.astype(np.float64))
    near = gaps[(gaps > pitch * 0.72) & (gaps < pitch * 1.28)]
    if len(near) >= 2:
        return float(np.median(near))
    return pitch


def _circular_phase(peaks: np.ndarray, pitch: float) -> float:
    phases = np.mod(peaks.astype(np.float64), pitch)
    ang = phases / pitch * 2.0 * math.pi
    phase = (math.atan2(float(np.sin(ang).mean()), float(np.cos(ang).mean())) / (2.0 * math.pi)) * pitch
    if phase < 0:
        phase += pitch
    return float(phase)


def _fit_grid_1d(peaks: np.ndarray, pitch: float, length: int) -> tuple[float, int, float, float, float]:
    """Return origin, n_cells, align_err, hit_rate, explain_rate."""
    if len(peaks) < 3 or pitch < 2:
        return 0.0, max(_MIN_STITCHES, int(length / max(pitch, 1))), 1.0, 0.0, 0.0
    origin = _circular_phase(peaks, pitch)
    snapped: list[float] = []
    errors: list[float] = []
    tol = pitch * 0.28
    for p in peaks:
        k = round((float(p) - origin) / pitch)
        pred = origin + k * pitch
        err = abs(float(p) - pred)
        if err <= tol:
            snapped.append(pred)
            errors.append(err)
    if len(snapped) < 3:
        return origin, max(_MIN_STITCHES, int((length - origin) / pitch)), 1.0, 0.0, 0.0
    first = min(snapped)
    last = max(snapped)
    n_lines = int(round((last - first) / pitch)) + 1
    n_cells = max(1, n_lines - 1)
    predicted = first + np.arange(n_lines) * pitch
    hits = 0
    for pred in predicted:
        if np.any(np.abs(peaks.astype(np.float64) - pred) <= tol):
            hits += 1
    hit_rate = hits / max(1, n_lines)
    explained = 0
    for pk in peaks:
        if np.any(np.abs(predicted - float(pk)) <= tol):
            explained += 1
    explain_rate = explained / max(1, len(peaks))
    align_err = float(np.median(errors)) / pitch if errors else 1.0
    return first, n_cells, align_err, hit_rate, explain_rate


def _extend_grid(profile: np.ndarray, origin: float, pitch: float, n_cells: int) -> tuple[float, int]:
    if pitch < 2 or n_cells < 1:
        return origin, n_cells
    n = len(profile)
    strong = profile[profile >= _MIN_LINE_STRENGTH]
    peak = float(np.percentile(strong, 70)) if len(strong) else 0.0
    thresh = max(_MIN_LINE_STRENGTH, 0.35 * peak)
    while True:
        pos = origin - pitch
        i = int(round(pos))
        if i < 0 or i >= n or profile[i] < thresh:
            break
        origin = pos
        n_cells += 1
    while True:
        pos = origin + n_cells * pitch
        i = int(round(pos))
        if i < 0 or i >= n or profile[i] < thresh:
            break
        n_cells += 1
    return origin, n_cells


def _include_border_cells(origin: float, pitch: float, n_cells: int, length: int) -> tuple[float, int]:
    """Grid lines on the image edge are invisible to a 3-tap Laplacian."""
    if pitch * 0.88 <= origin <= pitch * 1.12:
        origin = max(0.0, origin - pitch)
        n_cells += 1
    last = origin + n_cells * pitch
    gap = (length - 1) - last
    if pitch * 0.88 <= gap <= pitch * 1.12:
        n_cells += 1
    return origin, n_cells


def _line_contrast(profile: np.ndarray, origin: float, pitch: float, n_cells: int) -> float:
    n = len(profile)
    if n_cells < 2:
        return 0.0
    radius = max(1.0, pitch * 0.22)

    def _win(center: float, fn) -> float:
        i0 = max(0, int(round(center - radius)))
        i1 = min(n, int(round(center + radius)) + 1)
        if i1 <= i0:
            return 0.0
        return float(fn(profile[i0:i1]))

    on_vals = [_win(origin + k * pitch, np.max) for k in range(n_cells + 1)]
    off_vals = [_win(origin + (k + 0.5) * pitch, np.mean) for k in range(n_cells)]
    if len(on_vals) < 3 or len(off_vals) < 2:
        return 0.0
    on_m = float(np.mean(on_vals))
    off_m = float(np.mean(off_vals))
    abs_contrast = on_m - off_m
    if abs_contrast <= 0:
        return 0.0
    peak = max(float(np.percentile(profile, 90)), abs_contrast, 1.0)
    rel = abs_contrast / peak
    if abs_contrast < 3.5 and rel < 0.12:
        return 0.0
    return rel


def _axis_score(contrast: float, align_err: float, hit_rate: float, explain_rate: float) -> float:
    coverage = hit_rate * explain_rate
    return max(0.0, contrast) * (0.25 + 0.75 * coverage) / (1.0 + 4.0 * align_err)


def _strong_line_peaks(profile: np.ndarray, pitch: float) -> np.ndarray:
    peaks = _local_peaks(profile, min_sep=max(2, int(round(pitch * 0.55))))
    if len(peaks) < 3:
        return peaks
    strengths = profile[peaks]
    cut = max(_MIN_LINE_STRENGTH * 3.0, float(np.percentile(strengths, 70)) * 0.35)
    kept = peaks[strengths >= cut]
    return kept if len(kept) >= 3 else peaks


def _try_fit_1d(profile: np.ndarray, pitch: float, length: int) -> tuple[float, float, int, float] | None:
    peaks = _strong_line_peaks(profile, pitch)
    pitches = [pitch]
    refined = _refine_pitch(peaks, pitch)
    if abs(refined - pitch) > 0.2:
        pitches.append(refined)
    best: tuple[float, float, int, float] | None = None
    best_key = (-1.0, -1)
    for cand in pitches:
        origin, n_cells, align_err, hit_rate, explain_rate = _fit_grid_1d(peaks, cand, length)
        origin, n_cells = _extend_grid(profile, origin, cand, n_cells)
        origin, n_cells = _include_border_cells(origin, cand, n_cells, length)
        contrast = _line_contrast(profile, origin, cand, n_cells)
        score = _axis_score(contrast, align_err, hit_rate, explain_rate)
        if hit_rate < 0.58 or explain_rate < 0.5:
            continue
        if n_cells < _MIN_STITCHES or score < 0.05:
            continue
        key = (n_cells * score, n_cells)
        if key > best_key:
            best_key = key
            best = (cand, origin, n_cells, score)
    return best


def _purity_score(rgb: np.ndarray, ox: float, oy: float, px: float, py: float, nx: int, ny: int) -> float:
    h, w = rgb.shape[:2]
    inset = 0.30
    variances: list[float] = []
    step_x = max(1, nx // 8)
    step_y = max(1, ny // 8)
    for cy in range(0, ny, step_y):
        y0 = oy + cy * py
        iy0 = int(round(y0 + py * inset))
        iy1 = int(round(y0 + py * (1.0 - inset)))
        iy0 = max(0, min(h - 1, iy0))
        iy1 = max(iy0 + 1, min(h, iy1))
        for cx in range(0, nx, step_x):
            x0 = ox + cx * px
            ix0 = int(round(x0 + px * inset))
            ix1 = int(round(x0 + px * (1.0 - inset)))
            ix0 = max(0, min(w - 1, ix0))
            ix1 = max(ix0 + 1, min(w, ix1))
            patch = rgb[iy0:iy1, ix0:ix1]
            if patch.size < 3:
                continue
            variances.append(float(_gray(patch).var()))
    if not variances:
        return 0.0
    return 1.0 / (1.0 + float(np.median(variances)) / 180.0)


def detect_grid_spec(rgb: np.ndarray) -> GridSpec | None:
    if rgb.ndim != 3:
        raise TypeError("detect_grid_spec expects an RGB array")
    gray = _gray(rgb)
    h, w = gray.shape
    pmin = max(4, min(h, w) // 160)
    pmax = max(pmin + 2, min(72, min(h, w) // 5))
    row_p = _thin_line_profile(gray, axis=0)
    col_p = _thin_line_profile(gray, axis=1)
    cands_y = _collect_pitch_candidates(row_p, pmin, pmax)
    cands_x = _collect_pitch_candidates(col_p, pmin, pmax)
    if not cands_x or not cands_y:
        return None

    fits_x: dict[float, tuple[float, float, int, float]] = {}
    fits_y: dict[float, tuple[float, float, int, float]] = {}
    for pitch, _ in cands_x[:8]:
        for cand in _harmonic_divisors(pitch, pmin):
            key = round(cand * 4.0) / 4.0
            if key in fits_x:
                continue
            fit = _try_fit_1d(col_p, cand, w)
            if fit:
                fits_x[key] = fit
    for pitch, _ in cands_y[:8]:
        for cand in _harmonic_divisors(pitch, pmin):
            key = round(cand * 4.0) / 4.0
            if key in fits_y:
                continue
            fit = _try_fit_1d(row_p, cand, h)
            if fit:
                fits_y[key] = fit
    if not fits_x or not fits_y:
        return None

    pairs: list[tuple[float, tuple[float, float, int, float], tuple[float, float, int, float]]] = []
    for fx in fits_x.values():
        for fy in fits_y.values():
            px, py = fx[0], fy[0]
            if py <= 0 or not (0.62 <= px / py <= 1.6):
                continue
            pairs.append((math.sqrt(fx[3] * fy[3]), fx, fy))
    pairs.sort(key=lambda t: t[0], reverse=True)
    if not pairs:
        return None

    best: GridSpec | None = None
    best_score = -1.0
    for cheap, fx, fy in pairs[:10]:
        px, ox, nx, sx = fx
        py, oy, ny, sy = fy
        if nx < _MIN_STITCHES or ny < _MIN_STITCHES:
            continue
        if nx > _ABSURD_GRID_SIDE or ny > _ABSURD_GRID_SIDE:
            continue
        purity = _purity_score(rgb, ox, oy, px, py, nx, ny)
        square = min(px, py) / max(px, py)
        conf_block = cheap * (0.30 + 0.70 * purity)
        # Symbol/colour-filled cells have low purity; still prefer a finer
        # nearly-square grid over a 2×/10-count harmonic.
        conf_symbol = cheap * square * math.log10(10 + nx * ny) / 2.5
        conf = max(conf_block, conf_symbol)
        if conf > best_score:
            best_score = conf
            best = GridSpec(
                pitch_x=px,
                pitch_y=py,
                origin_x=ox,
                origin_y=oy,
                width_stitches=nx,
                height_stitches=ny,
                confidence=conf,
            )
    if best is None or best.confidence < _MIN_CONFIDENCE:
        return None
    return best


def _scale_spec(spec: GridSpec, sx: float, sy: float) -> GridSpec:
    return GridSpec(
        pitch_x=spec.pitch_x * sx,
        pitch_y=spec.pitch_y * sy,
        origin_x=spec.origin_x * sx,
        origin_y=spec.origin_y * sy,
        width_stitches=spec.width_stitches,
        height_stitches=spec.height_stitches,
        confidence=spec.confidence,
    )


def _rgb_chroma(r: int, g: int, b: int) -> int:
    return max(r, g, b) - min(r, g, b)


def _is_paper_rgb(r: int, g: int, b: int) -> bool:
    return min(r, g, b) >= 236 and _rgb_chroma(r, g, b) < 22


def _is_ink_rgb(r: int, g: int, b: int) -> bool:
    return max(r, g, b) <= 58 and _rgb_chroma(r, g, b) < 42


def _median_rgb(samples: np.ndarray) -> tuple[int, int, int]:
    med = np.median(samples.reshape(-1, 3), axis=0)
    return int(med[0]), int(med[1]), int(med[2])


def _cell_fill_color(patch: np.ndarray) -> tuple[int, int, int] | None:
    """Printed cell fill, ignoring a dark or white symbol drawn on top."""
    if patch.size == 0:
        return None
    gray = _gray(patch)
    flat = patch.reshape(-1, 3)
    g = gray.reshape(-1)
    if len(g) < 4:
        r, gv, b = _median_rgb(flat)
        return None if _is_paper_rgb(r, gv, b) else (r, gv, b)

    p15, p85 = (float(v) for v in np.percentile(g, [15, 85]))
    if p85 - p15 >= 32.0:
        mid = 0.5 * (p15 + p85)
        dark = flat[g <= mid]
        light = flat[g >= mid]
        if len(dark) < 2:
            samples = light
        elif len(light) < 2:
            samples = dark
        else:
            dr, dg, db = _median_rgb(dark)
            lr, lg, lb = _median_rgb(light)
            if _is_paper_rgb(lr, lg, lb) and not _is_paper_rgb(dr, dg, db):
                # White mark on a dark fill, vs black mark on paper.
                samples = dark if len(dark) > len(light) else light
            elif _is_ink_rgb(dr, dg, db) and not _is_paper_rgb(lr, lg, lb):
                samples = light
            elif _is_paper_rgb(lr, lg, lb):
                samples = light
            else:
                dc = _rgb_chroma(dr, dg, db)
                lc = _rgb_chroma(lr, lg, lb)
                if lc >= dc + 8 and len(light) >= max(3, int(len(dark) * 0.35)):
                    samples = light
                elif dc >= lc + 8 and len(dark) >= max(3, int(len(light) * 0.35)):
                    samples = dark
                else:
                    samples = light if len(light) >= len(dark) else dark
    else:
        samples = flat
    r, gv, b = _median_rgb(samples)
    if _is_paper_rgb(r, gv, b) or min(r, gv, b) >= _BACKGROUND_LUM:
        return None
    return r, gv, b


def _cell_color(patch: np.ndarray) -> tuple[int, int, int] | None:
    return _cell_fill_color(patch)


def _sample_grid(rgb: np.ndarray, spec: GridSpec) -> ChartGrid:
    h, w = rgb.shape[:2]
    nx, ny = spec.width_stitches, spec.height_stitches
    if nx < 2 or ny < 2:
        raise ValueError("Could not locate chart grid")
    cells = np.full((ny, nx, 3), 255, dtype=np.uint8)
    inset = 0.16
    for cy in range(ny):
        y0 = spec.origin_y + cy * spec.pitch_y
        iy0 = int(round(y0 + spec.pitch_y * inset))
        iy1 = int(round(y0 + spec.pitch_y * (1.0 - inset)))
        iy0 = max(0, min(h - 1, iy0))
        iy1 = max(iy0 + 1, min(h, iy1))
        for cx in range(nx):
            x0 = spec.origin_x + cx * spec.pitch_x
            ix0 = int(round(x0 + spec.pitch_x * inset))
            ix1 = int(round(x0 + spec.pitch_x * (1.0 - inset)))
            ix0 = max(0, min(w - 1, ix0))
            ix1 = max(ix0 + 1, min(w, ix1))
            med = _cell_color(rgb[iy0:iy1, ix0:ix1])
            if med is None:
                continue
            cells[cy, cx] = med
    return ChartGrid(width_stitches=nx, height_stitches=ny, cells=cells, source="grid")


def _trim_empty_border(grid: ChartGrid) -> ChartGrid:
    empty = np.min(grid.cells, axis=2) >= _BACKGROUND_LUM
    rows = ~empty.all(axis=1)
    cols = ~empty.all(axis=0)
    if not rows.any() or not cols.any():
        return grid
    r0 = int(np.argmax(rows))
    r1 = int(len(rows) - np.argmax(rows[::-1]))
    c0 = int(np.argmax(cols))
    c1 = int(len(cols) - np.argmax(cols[::-1]))
    if r1 - r0 < 2 or c1 - c0 < 2:
        return grid
    if r0 == 0 and c0 == 0 and r1 == grid.height_stitches and c1 == grid.width_stitches:
        return grid
    return ChartGrid(
        width_stitches=c1 - c0,
        height_stitches=r1 - r0,
        cells=grid.cells[r0:r1, c0:c1],
        source=grid.source,
    )


def _unique_color_count(rgb: np.ndarray, cap_samples: int = 20000) -> int:
    flat = rgb.reshape(-1, 3)
    if len(flat) > cap_samples:
        rng = np.random.default_rng(0)
        flat = flat[rng.choice(len(flat), cap_samples, replace=False)]
    packed = (
        (flat[:, 0].astype(np.uint32) << 16)
        | (flat[:, 1].astype(np.uint32) << 8)
        | flat[:, 2].astype(np.uint32)
    )
    return int(np.unique(packed).size)


def _has_blocky_runs(rgb: np.ndarray) -> bool:
    if rgb.shape[1] < 2:
        return False
    same = np.all(rgb[:, 1:] == rgb[:, :-1], axis=2).mean()
    return bool(same > 0.32)


def _looks_like_pixel_art(rgb: np.ndarray) -> bool:
    h, w = rgb.shape[:2]
    if max(h, w) > 96:
        return False
    return _unique_color_count(rgb) <= 56 and (max(h, w) <= 64 or _has_blocky_runs(rgb))


def _infer_pixel_scale(rgb: np.ndarray) -> int:
    """Guess upscale factor from identical-colour run lengths."""
    h, w = rgb.shape[:2]
    runs: list[int] = []
    step = max(1, h // 24)
    for y in range(0, h, step):
        run = 1
        for x in range(1, w):
            if (
                rgb[y, x, 0] == rgb[y, x - 1, 0]
                and rgb[y, x, 1] == rgb[y, x - 1, 1]
                and rgb[y, x, 2] == rgb[y, x - 1, 2]
            ):
                run += 1
            else:
                if 2 <= run < w:
                    runs.append(run)
                run = 1
        if 2 <= run < w:
            runs.append(run)
    if len(runs) < 4:
        return 1
    vals, counts = np.unique(np.array(runs), return_counts=True)
    mode = int(vals[int(np.argmax(counts))])
    if mode < 2:
        return 1
    return mode


def _pixel_art_grid(rgb: np.ndarray, max_w: int, max_h: int) -> ChartGrid:
    h, w = rgb.shape[:2]
    block = _infer_pixel_scale(rgb)
    if block >= 2 and h >= block * 2 and w >= block * 2:
        nh, nw = h // block, w // block
        cells = np.zeros((nh, nw, 3), dtype=np.uint8)
        for cy in range(nh):
            for cx in range(nw):
                y = cy * block + block // 2
                x = cx * block + block // 2
                cells[cy, cx] = rgb[min(y, h - 1), min(x, w - 1)]
        rgb = cells
        h, w = nh, nw
    if w <= max_w and h <= max_h:
        return ChartGrid(width_stitches=w, height_stitches=h, cells=rgb.copy(), source="pixel_art")
    scale = max(w / max_w, h / max_h)
    nw, nh = max(2, int(round(w / scale))), max(2, int(round(h / scale)))
    im = Image.fromarray(rgb, mode="RGB").resize((nw, nh), Image.Resampling.NEAREST)
    return ChartGrid(width_stitches=nw, height_stitches=nh, cells=np.asarray(im, dtype=np.uint8), source="pixel_art")


def _uniform_fallback_grid(rgb: np.ndarray, max_w: int, max_h: int) -> ChartGrid:
    """Equal tiles (no line detection) — one stitch per tile, not per pixel."""
    h, w = rgb.shape[:2]
    grid_w = min(max_w, max(2, w if w <= max_w else max_w))
    grid_h = min(max_h, max(2, int(round(h * (grid_w / w)))))
    cell_w = w / grid_w
    cell_h = h / grid_h
    cells = np.full((grid_h, grid_w, 3), 255, dtype=np.uint8)
    for cy in range(grid_h):
        y0 = int(cy * cell_h)
        y1 = int((cy + 1) * cell_h)
        for cx in range(grid_w):
            x0 = int(cx * cell_w)
            x1 = int((cx + 1) * cell_w)
            med = _cell_color(rgb[y0:y1, x0:x1])
            if med is None:
                continue
            cells[cy, cx] = med
    return ChartGrid(width_stitches=grid_w, height_stitches=grid_h, cells=cells, source="fallback")


def _downscale_grid(grid: ChartGrid, max_w: int, max_h: int) -> ChartGrid:
    if grid.width_stitches <= max_w and grid.height_stitches <= max_h:
        return grid
    fx = max(1, int(np.ceil(grid.width_stitches / max_w)))
    fy = max(1, int(np.ceil(grid.height_stitches / max_h)))
    factor = max(fx, fy)
    gw = grid.width_stitches // factor
    gh = grid.height_stitches // factor
    if gw < 2 or gh < 2:
        return grid
    out = np.full((gh, gw, 3), 255, dtype=np.uint8)
    for gy in range(gh):
        for gx in range(gw):
            block = grid.cells[gy * factor : (gy + 1) * factor, gx * factor : (gx + 1) * factor]
            flat = block.reshape(-1, 3)
            non_white = flat[np.any(flat < _BACKGROUND_LUM, axis=1)]
            if len(non_white) == 0:
                continue
            out[gy, gx] = np.median(non_white, axis=0).astype(np.uint8)
    return ChartGrid(width_stitches=gw, height_stitches=gh, cells=out, source=grid.source)


def _quantize_cell_colors(grid: ChartGrid, max_colors: int) -> ChartGrid:
    cells = grid.cells.copy()
    empty = np.min(cells, axis=2) >= _BACKGROUND_LUM
    if empty.all() or int((~empty).sum()) < 2:
        return grid
    img = Image.fromarray(cells, mode="RGB")
    q = img.quantize(colors=max(2, min(max_colors, 64)), method=Image.Quantize.MEDIANCUT).convert("RGB")
    arr = np.array(q, dtype=np.uint8, copy=True)
    arr[empty] = 255
    return ChartGrid(width_stitches=grid.width_stitches, height_stitches=grid.height_stitches, cells=arr, source=grid.source)


def _prepare_analysis(im: Image.Image) -> tuple[Image.Image, float, float]:
    w, h = im.size
    if max(w, h) <= _ANALYSIS_MAX_SIDE:
        return im, 1.0, 1.0
    scale = _ANALYSIS_MAX_SIDE / max(w, h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return im.resize((nw, nh), Image.Resampling.LANCZOS), w / nw, h / nh


def _line_energy(gray: np.ndarray) -> float:
    return float(np.percentile(_thin_line_profile(gray, 0), 95) + np.percentile(_thin_line_profile(gray, 1), 95))


def deskew_image(im: Image.Image) -> tuple[Image.Image, float]:
    """Rotate a few degrees if that clearly strengthens the stitch grid."""
    w, h = im.size
    probe = im
    if max(w, h) > 900:
        scale = 900 / max(w, h)
        probe = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BILINEAR)
    gray = _gray(_rgb_array(probe))
    base = _line_energy(gray)
    best_ang, best_e = 0.0, base
    for ang in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0):
        rot = probe.rotate(ang, resample=Image.Resampling.BILINEAR, fillcolor=(255, 255, 255))
        energy = _line_energy(_gray(_rgb_array(rot)))
        if energy > best_e:
            best_e, best_ang = energy, ang
    if abs(best_ang) < 0.4 or best_e < base * 1.12:
        return im, 0.0
    log.info("Deskewing chart by %.1f°", best_ang)
    return im.rotate(best_ang, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)), best_ang


def locate_chart_grid(im: Image.Image, *, allow_deskew: bool = True) -> tuple[GridSpec, np.ndarray] | None:
    """Detect the stitch grid; spec is in the returned RGB image's coordinates."""
    analysis, sx, sy = _prepare_analysis(im)
    rgb_a = _rgb_array(analysis)
    spec = detect_grid_spec(rgb_a)
    if (spec is None or spec.confidence < 0.22) and allow_deskew:
        rotated, angle = deskew_image(im)
        if angle != 0:
            return locate_chart_grid(rotated, allow_deskew=False)
    if spec is None:
        return None
    if spec.confidence < 0.5 and _looks_like_pixel_art(rgb_a):
        log.info("Weak grid on pixel-art image (conf=%.3f); ignoring", spec.confidence)
        return None
    sample_rgb = rgb_a if sx == 1.0 and sy == 1.0 else _rgb_array(im)
    if sx != 1.0 or sy != 1.0:
        spec = _scale_spec(spec, sx, sy)
    log.info(
        "Chart grid detected pitch=%.2fx%.2f origin=%.1f,%.1f conf=%.3f cells=%sx%s",
        spec.pitch_x,
        spec.pitch_y,
        spec.origin_x,
        spec.origin_y,
        spec.confidence,
        spec.width_stitches,
        spec.height_stitches,
    )
    return spec, sample_rgb


def extract_chart_grid(
    im: Image.Image,
    *,
    max_width: int,
    max_height: int | None = None,
    max_colors: int,
) -> ChartGrid:
    max_height = max_height or max_width
    located = locate_chart_grid(im)
    grid: ChartGrid | None = None
    rgb_a = _rgb_array(_prepare_analysis(im)[0])
    if located:
        spec, sample_rgb = located
        try:
            grid = _sample_grid(sample_rgb, spec)
        except ValueError:
            grid = None
    if grid is None:
        if _looks_like_pixel_art(rgb_a):
            log.info("No chart grid detected; using pixel-art sampling")
            grid = _pixel_art_grid(rgb_a, max_width, max_height)
        else:
            log.info("No chart grid detected; using uniform tile sampling")
            grid = _uniform_fallback_grid(rgb_a, max_width, max_height)
            grid = _downscale_grid(grid, max_width, max_height)
    grid = _trim_empty_border(grid)
    grid = _quantize_cell_colors(grid, max_colors)
    return grid

"""Render a normalized stitch chart as Chart Export.pdf (source page + chart page)."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from knitarr.parsers.oxs import NormalizedPattern
from knitarr.services.chart_symbol_modes import build_symbol_map, normalize_symbol_mode
from knitarr.services.checksum import sha256_file

log = logging.getLogger(__name__)

CHART_EXPORT_FILENAME = "Chart Export.pdf"
CHART_PREVIEW_FILENAME = "chart_preview.jpg"
CONVERSION_SOURCE_FILENAME = "conversion_source.jpg"
A4_WIDTH = 595.276  # 210mm
A4_HEIGHT = 841.890  # 297mm
MARGIN = 36.0
TITLE_SIZE = 14.0
META_SIZE = 9.0
LEGEND_SIZE = 8.0
MIN_CELL = 1.5
MAX_CELL = 18.0


def _hex_rgb8(color: str) -> tuple[int, int, int]:
    raw = (color or "FFFFFF").lstrip("#")
    if len(raw) != 6:
        raw = "CCCCCC"
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return (204, 204, 204)


def _hex_rgb(color: str) -> tuple[float, float, float]:
    r, g, b = _hex_rgb8(color)
    return (r / 255.0, g / 255.0, b / 255.0)


def _luminance8(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _ink8(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return (0, 0, 0) if _luminance8(rgb) > 0.55 else (255, 255, 255)


def _render_chart_image(
    norm: NormalizedPattern,
    *,
    w: int,
    h: int,
    cell_px: int,
    color_map: dict[int, tuple[int, int, int]],
    symbol_map: dict[int, str],
) -> Image.Image:
    """Rasterize stitches/grid/symbols/backstitches for embedding in the PDF."""
    cell_px = max(2, int(cell_px))
    img_w = w * cell_px
    img_h = h * cell_px
    arr = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
    for st in norm.full_stitches:
        pal = int(st.get("palindex") or 0)
        if pal <= 0:
            continue
        x = int(st.get("x") or 0)
        y = int(st.get("y") or 0)
        if not (0 <= x < w and 0 <= y < h):
            continue
        rgb = color_map.get(pal, (200, 200, 200))
        y0, y1 = y * cell_px, (y + 1) * cell_px
        x0, x1 = x * cell_px, (x + 1) * cell_px
        arr[y0:y1, x0:x1] = rgb

    im = Image.fromarray(arr, mode="RGB")
    draw = ImageDraw.Draw(im)
    for ps in norm.part_stitches:
        x = int(ps.get("x") or 0)
        y = int(ps.get("y") or 0)
        if not (0 <= x < w and 0 <= y < h):
            continue
        direction = int(ps.get("direction") or 1)
        p1 = int(ps.get("palindex1") or 0)
        p2 = int(ps.get("palindex2") or 0)
        x0, y0 = x * cell_px, y * cell_px
        x1, y1 = x0 + cell_px, y0 + cell_px
        if direction in (3, 4):
            pal = p1 if p1 > 0 else p2
            if pal <= 0:
                continue
            rgb = color_map.get(pal, (200, 200, 200))
            pad = max(1, cell_px // 5)
            width = max(1, cell_px // 4)
            if direction == 3:
                draw.line(
                    [(x0 + pad, y0 + pad), (x1 - pad, y1 - pad)],
                    fill=rgb,
                    width=width,
                )
            else:
                draw.line(
                    [(x1 - pad, y0 + pad), (x0 + pad, y1 - pad)],
                    fill=rgb,
                    width=width,
                )
            continue
        for which, pal in ((1, p1), (2, p2)):
            if pal <= 0:
                continue
            rgb = color_map.get(pal, (200, 200, 200))
            pts = _part_triangle_points(x0, y0, x1, y1, direction, which)
            if pts:
                draw.polygon(pts, fill=rgb)
    if cell_px >= 4:
        grid = (160, 160, 160) if cell_px >= 8 else (200, 200, 200)
        for i in range(w + 1):
            x = i * cell_px
            draw.line([(x, 0), (x, img_h)], fill=grid, width=1)
        for j in range(h + 1):
            y = j * cell_px
            draw.line([(0, y), (img_w, y)], fill=grid, width=1)

    if cell_px >= 8:
        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", max(6, int(cell_px * 0.55)))
        except OSError:
            font = ImageFont.load_default()
        for st in norm.full_stitches:
            pal = int(st.get("palindex") or 0)
            mark = symbol_map.get(pal) or ""
            if pal <= 0 or not mark:
                continue
            x = int(st.get("x") or 0)
            y = int(st.get("y") or 0)
            if not (0 <= x < w and 0 <= y < h):
                continue
            ink = _ink8(color_map.get(pal, (255, 255, 255)))
            cx = x * cell_px + cell_px / 2
            cy = y * cell_px + cell_px / 2
            draw.text((cx, cy), mark, fill=ink, font=font, anchor="mm")

    for b in norm.backstitches:
        pal = int(b.get("palindex") or 0)
        rgb = color_map.get(pal, (0, 0, 0))
        if _luminance8(rgb) > 0.7:
            rgb = (20, 20, 20)
        x1 = float(b.get("x1") or 0) * cell_px
        y1 = float(b.get("y1") or 0) * cell_px
        x2 = float(b.get("x2") or 0) * cell_px
        y2 = float(b.get("y2") or 0) * cell_px
        draw.line([(x1, y1), (x2, y2)], fill=rgb, width=max(1, cell_px // 8))

    for o in norm.ornaments:
        pal = int(o.get("palindex") or 0)
        rgb = color_map.get(pal, (0, 0, 0))
        cx = float(o.get("x") or 0) * cell_px
        cy = float(o.get("y") or 0) * cell_px
        otype = str(o.get("objecttype") or "knot").lower()
        if otype.startswith("bead"):
            r = max(1.5, cell_px * 0.22)
        else:
            r = max(1.2, cell_px * 0.18)
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=rgb, outline=(20, 20, 20))
    return im


def _part_triangle_points(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    direction: int,
    which: int,
) -> list[tuple[float, float]] | None:
    """Ursa triangles: dir1 \\ (BL/TR), dir2 / (TL/BR). palindex1=left, palindex2=right."""
    if direction in (2, 4):
        half = "tl" if which == 1 else "br"
    else:
        half = "bl" if which == 1 else "tr"
    if half == "bl":
        return [(x0, y0), (x0, y1), (x1, y1)]
    if half == "tr":
        return [(x0, y0), (x1, y0), (x1, y1)]
    if half == "tl":
        return [(x0, y0), (x1, y0), (x0, y1)]
    return [(x1, y0), (x1, y1), (x0, y1)]


def render_chart_preview_image(norm: NormalizedPattern, *, max_side: int = 640) -> Image.Image:
    """Rasterize a chart for library thumbnails / OXS preview when no source image exists."""
    w = max(1, int(norm.width_stitches or 1))
    h = max(1, int(norm.height_stitches or 1))
    longest = max(w, h)
    # Prefer ~3–6px cells for readable thumbs without huge rasters.
    cell_px = max(2, min(8, int(round(max_side / max(1, longest)))))
    if longest * cell_px > max_side * 2:
        cell_px = max(2, int(max_side * 2 / longest))
    color_map = {pe.index: _hex_rgb8(pe.color) for pe in norm.palette}
    symbol_map = build_symbol_map(norm.palette, _symbol_mode_for_norm(norm))
    im = _render_chart_image(
        norm, w=w, h=h, cell_px=cell_px, color_map=color_map, symbol_map=symbol_map
    )
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.Resampling.NEAREST)
    return im.convert("RGB")


def write_chart_preview_image(
    path: Path, norm: NormalizedPattern, *, max_side: int = 640
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im = render_chart_preview_image(norm, max_side=max_side)
    im.save(path, format="JPEG", quality=88, optimize=True)
    return path


def _symbol_mode_for_norm(norm: NormalizedPattern, override: str | None = None) -> str:
    if override:
        return normalize_symbol_mode(override)
    recog = norm.recognition if isinstance(norm.recognition, dict) else {}
    return normalize_symbol_mode(recog.get("symbol_mode") if recog else None)


def write_chart_export_pdf(
    path: Path,
    norm: NormalizedPattern,
    *,
    source_image: Path | None = None,
    symbol_mode: str | None = None,
) -> Path:
    """Write Chart Export.pdf: optional cropped-source page, then chart + legend."""
    import io

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    w = max(1, int(norm.width_stitches or 1))
    h = max(1, int(norm.height_stitches or 1))
    title = (norm.title or "Chart").strip() or "Chart"
    fabric = norm.fabric_count or 14
    colors = norm.color_count()
    mode = _symbol_mode_for_norm(norm, symbol_mode)

    palette = {pe.index: pe for pe in norm.palette}
    color_map8 = {idx: _hex_rgb8(pe.color) for idx, pe in palette.items()}
    color_map = {idx: (r / 255.0, g / 255.0, b / 255.0) for idx, (r, g, b) in color_map8.items()}
    symbol_map = build_symbol_map(norm.palette, mode)

    used_ids = {int(s.get("palindex") or 0) for s in norm.full_stitches}
    used_ids |= {int(b.get("palindex") or 0) for b in norm.backstitches}
    for ps in norm.part_stitches:
        used_ids.add(int(ps.get("palindex1") or 0))
        used_ids.add(int(ps.get("palindex2") or 0))
    used_ids |= {int(o.get("palindex") or 0) for o in norm.ornaments}
    used = sorted(
        (pe for pe in norm.palette if pe.index > 0 and (pe.stitch_count > 0 or pe.index in used_ids)),
        key=lambda pe: pe.index,
    )
    if not used:
        used = [pe for pe in sorted(norm.palette, key=lambda p: p.index) if pe.index > 0]

    counts = {pe.index: pe.stitch_count for pe in used}
    if not any(counts.values()):
        for s in norm.full_stitches:
            pal = int(s.get("palindex") or 0)
            if pal > 0:
                counts[pal] = counts.get(pal, 0) + 1

    doc = fitz.open()
    content_w = A4_WIDTH - 2 * MARGIN

    src_path = Path(source_image) if source_image else None
    if src_path and src_path.is_file():
        page0 = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
        y = MARGIN
        page0.insert_text(
            fitz.Point(MARGIN, y + TITLE_SIZE),
            f"{title[:80]} — source",
            fontsize=TITLE_SIZE,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        y += TITLE_SIZE + 10
        page0.insert_text(
            fitz.Point(MARGIN, y + META_SIZE),
            "Cropped image used to generate the stitch chart",
            fontsize=META_SIZE,
            fontname="helv",
            color=(0.35, 0.35, 0.35),
        )
        y += META_SIZE + 16
        try:
            with Image.open(src_path) as src_im:
                src_rgb = src_im.convert("RGB")
                max_side = 2200
                if max(src_rgb.size) > max_side:
                    src_rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                buf0 = io.BytesIO()
                src_rgb.save(buf0, format="JPEG", quality=90, optimize=True)
                avail_w = content_w
                avail_h = A4_HEIGHT - MARGIN - y
                iw, ih = src_rgb.size
                scale = min(avail_w / max(1, iw), avail_h / max(1, ih))
                dw, dh = iw * scale, ih * scale
                ox = MARGIN + max(0.0, (avail_w - dw) / 2)
                rect0 = fitz.Rect(ox, y, ox + dw, y + dh)
                page0.insert_image(rect0, stream=buf0.getvalue())
        except Exception as e:
            log.warning("Could not embed conversion source in PDF: %s", e)
            page0.insert_text(
                fitz.Point(MARGIN, y + 20),
                "(Source image unavailable)",
                fontsize=META_SIZE,
                fontname="helv",
                color=(0.5, 0.2, 0.2),
            )

    page = doc.new_page(width=A4_WIDTH, height=A4_HEIGHT)
    y = MARGIN

    page.insert_text(
        fitz.Point(MARGIN, y + TITLE_SIZE),
        title[:90],
        fontsize=TITLE_SIZE,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
    )
    y += TITLE_SIZE + 8
    meta = f"{w} × {h} stitches · {colors} colours · {fabric} count · symbols: {mode}"
    page.insert_text(
        fitz.Point(MARGIN, y + META_SIZE),
        meta,
        fontsize=META_SIZE,
        fontname="helv",
        color=(0.35, 0.35, 0.35),
    )
    y += META_SIZE + 14

    legend_rows = max(1, len(used))
    legend_line_h = 12.0
    legend_cols = 2 if legend_rows > 12 else 1
    legend_h = ((legend_rows + legend_cols - 1) // legend_cols) * legend_line_h + 18
    chart_bottom = A4_HEIGHT - MARGIN - legend_h - 8
    avail_h = max(80.0, chart_bottom - y)
    cell = min(MAX_CELL, content_w / w, avail_h / h)
    cell = max(MIN_CELL, cell)
    chart_w = cell * w
    chart_h = cell * h
    origin_x = MARGIN + max(0.0, (content_w - chart_w) / 2)
    origin_y = y

    cell_px = max(2, min(16, int(round(cell * 2.0))))
    chart_im = _render_chart_image(
        norm, w=w, h=h, cell_px=cell_px, color_map=color_map8, symbol_map=symbol_map
    )
    max_side = 2800
    if max(chart_im.size) > max_side:
        chart_im.thumbnail((max_side, max_side), Image.Resampling.NEAREST)

    buf = io.BytesIO()
    chart_im.save(buf, format="JPEG", quality=90, optimize=True)
    rect = fitz.Rect(origin_x, origin_y, origin_x + chart_w, origin_y + chart_h)
    page.draw_rect(rect, color=(0.75, 0.75, 0.75), width=0.6)
    page.insert_image(rect, stream=buf.getvalue())

    legend_top = origin_y + chart_h + 16
    page.insert_text(
        fitz.Point(MARGIN, legend_top + LEGEND_SIZE),
        "Legend",
        fontsize=LEGEND_SIZE + 1,
        fontname="helv",
        color=(0.15, 0.15, 0.15),
    )
    legend_top += LEGEND_SIZE + 8
    col_w = content_w / legend_cols
    for i, pe in enumerate(used):
        col = i % legend_cols
        row = i // legend_cols
        lx = MARGIN + col * col_w
        ly = legend_top + row * legend_line_h
        if ly + legend_line_h > A4_HEIGHT - MARGIN + 2:
            break
        rgb = color_map.get(pe.index, (0.8, 0.8, 0.8))
        sw = fitz.Rect(lx, ly, lx + 10, ly + 10)
        page.draw_rect(sw, color=(0.4, 0.4, 0.4), fill=rgb, width=0.4)
        mark = symbol_map.get(pe.index) or ""
        label = f"{mark + '  ' if mark else ''}{(pe.number or '').strip() or pe.name}".strip()
        if pe.name and pe.name.strip() and pe.name.strip() not in label:
            label = f"{label} — {pe.name.strip()}"
        count = counts.get(pe.index, pe.stitch_count)
        text = f"{label}  ({count})"
        page.insert_text(
            fitz.Point(lx + 14, ly + 8.5),
            text[:70],
            fontsize=LEGEND_SIZE,
            fontname="helv",
            color=(0.15, 0.15, 0.15),
        )

    doc.save(path)
    doc.close()
    return path


def _upsert_derived_file(conn, pattern_id: int, path: Path, *, role: str = "derived") -> None:
    cs = sha256_file(path)
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    existing = conn.execute(
        "SELECT id FROM pattern_files WHERE pattern_id = ? AND filename = ?",
        (pattern_id, path.name),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE pattern_files SET path = ?, mime_type = ?, checksum_sha256 = ?, size_bytes = ?, role = ? WHERE id = ?",
            (str(path), mime, cs, path.stat().st_size, role, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pattern_id, role, str(path), path.name, mime, cs, path.stat().st_size),
        )


def upsert_chart_preview(conn, pattern_id: int, pattern_dir: Path, norm: NormalizedPattern) -> Path | None:
    """Write chart_preview.jpg from the normalized chart and register it."""
    try:
        path = write_chart_preview_image(pattern_dir / CHART_PREVIEW_FILENAME, norm)
    except Exception as e:
        log.warning("Chart preview image failed for pattern %s: %s", pattern_id, e)
        return None
    _upsert_derived_file(conn, pattern_id, path)
    return path


def upsert_chart_export(
    conn,
    pattern_id: int,
    pattern_dir: Path,
    norm: NormalizedPattern,
    *,
    symbol_mode: str | None = None,
) -> Path | None:
    """Write Chart Export.pdf and register/update it as a derived pattern file."""
    try:
        source = pattern_dir / CONVERSION_SOURCE_FILENAME
        path = write_chart_export_pdf(
            pattern_dir / CHART_EXPORT_FILENAME,
            norm,
            source_image=source if source.is_file() else None,
            symbol_mode=symbol_mode,
        )
    except Exception as e:
        log.warning("Chart export PDF failed for pattern %s: %s", pattern_id, e)
        return None
    _upsert_derived_file(conn, pattern_id, path)
    return path

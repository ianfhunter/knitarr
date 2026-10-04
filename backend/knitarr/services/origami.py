"""Origami FOLD crease-pattern helpers and SVG preview."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.services.checksum import sha256_file

log = logging.getLogger(__name__)

FOLD_SUFFIXES = frozenset({".fold", ".json"})
META_FILENAME = "origami.json"
PREVIEW_SVG = "origami_preview.svg"

# FOLD edge assignments → stroke style
_ASSIGN = {
    "B": ("#1a1a1a", "4", ""),  # border
    "M": ("#c0392b", "2.5", "6 4"),  # mountain
    "V": ("#2471a3", "2.5", "2 3"),  # valley
    "U": ("#7f8c8d", "1.5", "1 2"),  # unassigned
    "F": ("#27ae60", "1.5", ""),  # flat/facet
    "C": ("#8e44ad", "2", "4 2"),  # cut
}


def is_fold_file(path: Path) -> bool:
    if path.suffix.lower() not in FOLD_SUFFIXES:
        return False
    if path.suffix.lower() == ".fold":
        return True
    # .json — only if it looks like FOLD
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and (
        "vertices_coords" in data or "file_spec" in data or "frame_classes" in data
    )


def find_fold_file(pattern_id: int) -> Path | None:
    lib = settings.library_dir / str(pattern_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT path, filename FROM pattern_files WHERE pattern_id = ? ORDER BY id",
            (pattern_id,),
        ).fetchall()
    for row in rows:
        p = Path(row["path"]) if row["path"] else lib / row["filename"]
        if p.is_file() and is_fold_file(p):
            return p
    if lib.is_dir():
        for p in sorted(lib.glob("*.fold")) + sorted(lib.glob("*.json")):
            if is_fold_file(p):
                return p
    return None


def load_fold(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("FOLD file must be a JSON object")
    return data


def fold_summary(data: dict[str, Any]) -> dict[str, Any]:
    verts = data.get("vertices_coords") or []
    edges = data.get("edges_vertices") or []
    faces = data.get("faces_vertices") or data.get("faces_edges") or []
    assigns = data.get("edges_assignment") or []
    counts: dict[str, int] = {}
    for a in assigns:
        key = str(a or "U")
        counts[key] = counts.get(key, 0) + 1
    classes = data.get("frame_classes") or data.get("file_classes") or []
    return {
        "format": "knitarr_origami_v1",
        "file_spec": data.get("file_spec"),
        "file_creator": data.get("file_creator"),
        "frame_title": data.get("frame_title") or data.get("file_title"),
        "frame_classes": classes,
        "vertex_count": len(verts),
        "edge_count": len(edges),
        "face_count": len(faces),
        "assignment_counts": counts,
    }


def crease_pattern_svg(data: dict[str, Any], *, size: int = 640) -> str:
    """Render a 2D crease-pattern SVG from FOLD vertices/edges."""
    coords = data.get("vertices_coords") or []
    edges = data.get("edges_vertices") or []
    assigns = data.get("edges_assignment") or []
    if not coords or not edges:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            f'<rect width="100%" height="100%" fill="#f4f0ea"/>'
            f'<text x="50%" y="50%" text-anchor="middle" fill="#666" font-family="system-ui">'
            f"No crease geometry</text></svg>"
        )

    xs = [float(c[0]) for c in coords if c]
    ys = [float(c[1]) for c in coords if c]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    pad = 24
    scale = (size - 2 * pad) / max(span_x, span_y)

    def tx(x: float, y: float) -> tuple[float, float]:
        # Flip Y for screen coords
        return (
            pad + (x - min_x) * scale + (size - 2 * pad - span_x * scale) / 2,
            pad + (max_y - y) * scale + (size - 2 * pad - span_y * scale) / 2,
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">',
        f'<rect width="100%" height="100%" fill="#f7f3ec"/>',
    ]
    # Draw unassigned/flat first, then MV, borders on top
    order = sorted(range(len(edges)), key=lambda i: 0 if (assigns[i] if i < len(assigns) else "U") in {"B"} else 1)
    for i in order:
        ev = edges[i]
        if not ev or len(ev) < 2:
            continue
        a, b = int(ev[0]), int(ev[1])
        if a >= len(coords) or b >= len(coords):
            continue
        x1, y1 = tx(float(coords[a][0]), float(coords[a][1]))
        x2, y2 = tx(float(coords[b][0]), float(coords[b][1]))
        assign = str(assigns[i]) if i < len(assigns) else "U"
        color, width, dash = _ASSIGN.get(assign, _ASSIGN["U"])
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash_attr}/>'
        )

    # Legend
    legend_y = size - 14
    parts.append(
        f'<text x="16" y="{legend_y}" font-size="11" font-family="system-ui" fill="#555">'
        f'<tspan fill="#c0392b">Mountain</tspan> · '
        f'<tspan fill="#2471a3">Valley</tspan> · '
        f'<tspan fill="#1a1a1a">Border</tspan></text>'
    )
    title = data.get("frame_title") or data.get("file_title")
    if title:
        parts.append(
            f'<text x="{size/2:.0f}" y="18" text-anchor="middle" font-size="13" '
            f'font-family="system-ui" font-weight="600" fill="#2d4a3e">{escape(str(title))}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _write_crease_thumb(data: dict[str, Any], dest: Path, size: int = 480) -> None:
    """Draw a simple crease-pattern JPEG for library cards (Pillow; no SVG rasterizer)."""
    from PIL import Image, ImageDraw

    coords = data.get("vertices_coords") or []
    edges = data.get("edges_vertices") or []
    assigns = data.get("edges_assignment") or []
    img = Image.new("RGB", (size, size), "#f7f3ec")
    draw = ImageDraw.Draw(img)
    if not coords or not edges:
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="JPEG", quality=88, optimize=True)
        return

    xs = [float(c[0]) for c in coords if c]
    ys = [float(c[1]) for c in coords if c]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    pad = 18
    scale = (size - 2 * pad) / max(span_x, span_y)

    def tx(x: float, y: float) -> tuple[float, float]:
        return (
            pad + (x - min_x) * scale + (size - 2 * pad - span_x * scale) / 2,
            pad + (max_y - y) * scale + (size - 2 * pad - span_y * scale) / 2,
        )

    colours = {
        "B": "#1a1a1a",
        "M": "#c0392b",
        "V": "#2471a3",
        "U": "#7f8c8d",
        "F": "#27ae60",
        "C": "#8e44ad",
    }
    for i, ev in enumerate(edges):
        if not ev or len(ev) < 2:
            continue
        a, b = int(ev[0]), int(ev[1])
        if a >= len(coords) or b >= len(coords):
            continue
        p1 = tx(float(coords[a][0]), float(coords[a][1]))
        p2 = tx(float(coords[b][0]), float(coords[b][1]))
        assign = str(assigns[i]) if i < len(assigns) else "U"
        draw.line([p1, p2], fill=colours.get(assign, "#7f8c8d"), width=2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="JPEG", quality=88, optimize=True)


def process_fold(pattern_id: int, source: Path | None = None) -> dict[str, Any]:
    src = source or find_fold_file(pattern_id)
    if not src or not src.is_file():
        raise FileNotFoundError("No FOLD origami file found")
    data = load_fold(src)
    summary = fold_summary(data)
    summary["source_filename"] = src.name

    lib = settings.library_dir / str(pattern_id)
    lib.mkdir(parents=True, exist_ok=True)
    svg_path = lib / PREVIEW_SVG
    meta_path = lib / META_FILENAME
    svg_path.write_text(crease_pattern_svg(data), encoding="utf-8")
    meta_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    thumb = lib / "thumb.jpg"
    try:
        _write_crease_thumb(data, thumb)
    except Exception as e:
        log.info("Origami thumb skipped for %s: %s", pattern_id, e)

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE patterns SET
                pattern_format = ?,
                thumbnail_path = COALESCE(?, thumbnail_path)
            WHERE id = ?
            """,
            ("origami", str(thumb) if thumb.is_file() else None, pattern_id),
        )
        for path, mime in (
            (svg_path, "image/svg+xml"),
            (meta_path, "application/json"),
        ):
            existing = conn.execute(
                "SELECT id FROM pattern_files WHERE pattern_id = ? AND filename = ?",
                (pattern_id, path.name),
            ).fetchone()
            cs = sha256_file(path)
            if existing:
                conn.execute(
                    """
                    UPDATE pattern_files
                    SET path = ?, checksum_sha256 = ?, size_bytes = ?, mime_type = ?
                    WHERE id = ?
                    """,
                    (str(path), cs, path.stat().st_size, mime, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO pattern_files
                        (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
                    VALUES (?, 'derived', ?, ?, ?, ?, ?)
                    """,
                    (pattern_id, str(path), path.name, mime, cs, path.stat().st_size),
                )
    return summary


def load_meta(pattern_id: int) -> dict[str, Any] | None:
    path = settings.library_dir / str(pattern_id) / META_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def get_or_process(pattern_id: int) -> dict[str, Any]:
    existing = load_meta(pattern_id)
    svg = settings.library_dir / str(pattern_id) / PREVIEW_SVG
    if existing and svg.is_file():
        return existing
    return process_fold(pattern_id)


def fold_data_for_viewer(pattern_id: int) -> dict[str, Any]:
    """Return FOLD JSON plus summary for the frontend viewer."""
    src = find_fold_file(pattern_id)
    if not src:
        raise FileNotFoundError("No FOLD file")
    data = load_fold(src)
    meta = get_or_process(pattern_id)
    return {"fold": data, "meta": meta, "preview_svg_url": f"/api/patterns/{pattern_id}/file-by-name/{PREVIEW_SVG}"}

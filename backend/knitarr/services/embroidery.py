"""Machine embroidery / quilting file parsing via pyembroidery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.services.checksum import sha256_file

log = logging.getLogger(__name__)

MACHINE_SUFFIXES = frozenset(
    {
        ".dst",
        ".pes",
        ".pec",
        ".jef",
        ".exp",
        ".vp3",
        ".xxx",
        ".u01",
        ".sew",
        ".pcs",
        ".pcm",
        ".csd",
        ".csq",
        ".hqf",
        ".hqv",
        ".iqp",
        ".plt",
        ".10o",
        ".inb",
        ".tbf",
        ".emd",
        ".new",
        ".tap",
        ".phb",
        ".phc",
        ".max",
        ".dat",
        ".dsb",
        ".dsz",
        ".ksm",
        ".shv",
        ".stx",
    }
)

PRIMARY_MACHINE_SUFFIXES = (
    ".pes",
    ".dst",
    ".jef",
    ".exp",
    ".vp3",
    ".xxx",
    ".csq",
    ".hqf",
    ".hqv",
    ".iqp",
)

META_FILENAME = "embroidery.json"
PREVIEW_PNG = "embroidery_preview.png"
PREVIEW_SVG = "embroidery_preview.svg"


def is_machine_embroidery_file(path: Path) -> bool:
    return path.suffix.lower() in MACHINE_SUFFIXES


def find_machine_file(pattern_id: int) -> Path | None:
    lib = settings.library_dir / str(pattern_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT path, filename FROM pattern_files
            WHERE pattern_id = ? ORDER BY id
            """,
            (pattern_id,),
        ).fetchall()
    ranked: list[tuple[int, Path]] = []
    for row in rows:
        name = (row["filename"] or "").lower()
        p = Path(row["path"]) if row["path"] else lib / row["filename"]
        if not p.is_file():
            continue
        suf = Path(name).suffix.lower()
        if suf in MACHINE_SUFFIXES:
            try:
                rank = PRIMARY_MACHINE_SUFFIXES.index(suf)
            except ValueError:
                rank = 50
            ranked.append((rank, p))
    if ranked:
        ranked.sort(key=lambda t: t[0])
        return ranked[0][1]
    for p in sorted(lib.iterdir()) if lib.is_dir() else []:
        if p.is_file() and is_machine_embroidery_file(p):
            return p
    return None


def _thread_hex(thread: Any) -> str:
    try:
        if hasattr(thread, "hex_color"):
            hc = thread.hex_color()
            if isinstance(hc, str):
                return hc if hc.startswith("#") else f"#{hc}"
        if hasattr(thread, "get_hex_color"):
            hc = thread.get_hex_color()
            if isinstance(hc, int):
                return f"#{hc:06x}"
            if isinstance(hc, str):
                return hc if hc.startswith("#") else f"#{hc}"
        rgb = getattr(thread, "color", None) or getattr(thread, "rgb", None)
        if rgb and len(rgb) >= 3:
            return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
    except Exception:
        pass
    return "#808080"


def _pattern_stats(pattern: Any) -> dict[str, Any]:
    import pyembroidery

    bounds = pattern.bounds()
    width = height = None
    if bounds:
        min_x, min_y, max_x, max_y = bounds
        width = round((max_x - min_x) / 10.0, 2)
        height = round((max_y - min_y) / 10.0, 2)
    stitch_count = pattern.count_stitch_commands(pyembroidery.STITCH)
    threads = []
    for t in getattr(pattern, "threadlist", None) or []:
        desc = ""
        for attr in ("description", "chart", "catalog_number"):
            val = getattr(t, attr, None)
            if val:
                desc = str(val)
                break
        threads.append({"hex": _thread_hex(t), "description": desc})
    return {
        "stitch_count": int(stitch_count or 0),
        "color_count": len(threads) or None,
        "width_mm": width,
        "height_mm": height,
        "threads": threads,
    }


def process_machine_file(pattern_id: int, source: Path | None = None) -> dict[str, Any]:
    """Read a machine file, write preview artifacts, return metadata."""
    import pyembroidery

    src = source or find_machine_file(pattern_id)
    if not src or not src.is_file():
        raise FileNotFoundError("No machine embroidery/quilting file found")

    try:
        pattern = pyembroidery.read(str(src))
    except Exception as e:
        raise ValueError(f"Could not parse {src.name}: {e}") from e
    if pattern is None:
        raise ValueError(f"Unsupported or empty embroidery file: {src.name}")

    lib = settings.library_dir / str(pattern_id)
    lib.mkdir(parents=True, exist_ok=True)
    png_path = lib / PREVIEW_PNG
    svg_path = lib / PREVIEW_SVG
    meta_path = lib / META_FILENAME

    try:
        pyembroidery.write_png(pattern, str(png_path))
    except Exception as e:
        log.warning("embroidery PNG preview failed for %s: %s", pattern_id, e)
    try:
        pyembroidery.write_svg(pattern, str(svg_path))
    except Exception as e:
        log.warning("embroidery SVG preview failed for %s: %s", pattern_id, e)

    stats = _pattern_stats(pattern)
    meta = {
        "format": "knitarr_embroidery_v1",
        "source_filename": src.name,
        "source_suffix": src.suffix.lower(),
        **stats,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with get_conn() as conn:
        thumb = lib / "thumb.jpg"
        if png_path.is_file():
            try:
                from PIL import Image

                with Image.open(png_path) as im:
                    rgb = im.convert("RGB")
                    rgb.thumbnail((480, 480))
                    rgb.save(thumb, format="JPEG", quality=88, optimize=True)
            except Exception:
                pass
        conn.execute(
            """
            UPDATE patterns SET
                thumbnail_path = COALESCE(?, thumbnail_path),
                stitch_count = COALESCE(?, stitch_count),
                color_count = COALESCE(?, color_count),
                pattern_format = ?
            WHERE id = ?
            """,
            (
                str(thumb) if thumb.is_file() else None,
                stats.get("stitch_count"),
                stats.get("color_count"),
                "embroidery",
                pattern_id,
            ),
        )
        for path in (png_path, svg_path, meta_path):
            if not path.is_file():
                continue
            existing = conn.execute(
                "SELECT id FROM pattern_files WHERE pattern_id = ? AND filename = ?",
                (pattern_id, path.name),
            ).fetchone()
            cs = sha256_file(path)
            mime = {
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".json": "application/json",
            }.get(path.suffix.lower(), "application/octet-stream")
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
    return meta


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
    png = settings.library_dir / str(pattern_id) / PREVIEW_PNG
    if existing and (png.is_file() or (settings.library_dir / str(pattern_id) / PREVIEW_SVG).is_file()):
        return existing
    return process_machine_file(pattern_id)

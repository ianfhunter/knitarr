"""Attach raster/structured → OXS conversion to an imported pattern."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from knitarr.models import CropRect
from knitarr.parsers.oxs import NormalizedPattern, metadata_from_oxs
from knitarr.parsers.saga import parse_saga
from knitarr.services import dedupe
from knitarr.services.checksum import sha256_file
from knitarr.services.image_to_oxs import (
    RASTER_SUFFIXES,
    convert_raster_to_normalized,
    looks_like_xps,
    write_conversion_artifacts,
)

log = logging.getLogger(__name__)

STRUCTURED_SUFFIXES = {".saga"}


def try_convert_upload_to_chart(
    conn,
    pattern_id: int,
    pattern_dir: Path,
    primary: Path,
    *,
    title: str,
    craft: str,
    crop: CropRect | None = None,
    pdf_page: int = 0,
) -> str | None:
    if craft != "cross_stitch":
        return None
    suffix = primary.suffix.lower()
    if suffix in STRUCTURED_SUFFIXES:
        norm = parse_saga(primary, title=title)
        return _store_normalized(
            conn,
            pattern_id,
            pattern_dir,
            norm,
            kind="Converted Saga chart",
            notes=[],
        )
    if suffix == ".xsp" and not looks_like_xps(primary):
        raise ValueError(
            "XSPro Platinum (.xsp) files are encrypted and cannot be converted to OXS. "
            "If this is a Microsoft XPS document, rename it to .xps."
        )
    if suffix not in RASTER_SUFFIXES and not (suffix == ".xsp" and looks_like_xps(primary)):
        return None
    try:
        norm = convert_raster_to_normalized(primary, title=title, crop=crop, pdf_page=pdf_page)
        notes: list[str] = []
        if pdf_page > 0:
            label = "XPS" if suffix in {".xps", ".oxps", ".xsp"} else "PDF"
            notes.append(f"{label} page {pdf_page + 1}")
        if crop:
            notes.append("cropped region")
        source = getattr(norm, "chart_source", None)
        recog = norm.recognition or {}
        if source == "symbols":
            low = recog.get("low_confidence") or 0
            low_note = f", {low} low-confidence cells" if low else ""
            kind = f"Recognised symbol chart{low_note}"
        elif source == "grid":
            kind = "Detected colour-block chart"
        elif source == "pixel_art":
            kind = "Converted pixel image"
        else:
            kind = "Generated experimental chart"
        return _store_normalized(conn, pattern_id, pattern_dir, norm, kind=kind, notes=notes)
    except ValueError:
        raise
    except Exception as e:
        log.warning("Chart conversion failed for pattern %s: %s", pattern_id, e)
        return None


def _store_normalized(
    conn,
    pattern_id: int,
    pattern_dir: Path,
    norm: NormalizedPattern,
    *,
    kind: str,
    notes: list[str],
) -> str:
    oxs_path, json_path = write_conversion_artifacts(pattern_dir, norm)
    conn.execute("DELETE FROM pattern_files WHERE pattern_id = ? AND role = 'derived'", (pattern_id,))
    meta = metadata_from_oxs(norm)
    structure_fp = dedupe.fingerprint_from_normalized(norm)
    conn.execute(
        """
        UPDATE patterns SET
            normalized_path = ?,
            width_stitches = ?,
            height_stitches = ?,
            stitch_count = ?,
            color_count = ?,
            structure_fingerprint = ?,
            floss_brand = ?
        WHERE id = ?
        """,
        (
            str(json_path),
            meta.get("width_stitches"),
            meta.get("height_stitches"),
            meta.get("stitch_count"),
            meta.get("color_count"),
            structure_fp,
            meta.get("floss_brand"),
            pattern_id,
        ),
    )
    cs = sha256_file(oxs_path)
    mime, _ = mimetypes.guess_type(oxs_path.name)
    conn.execute(
        """
        INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
        VALUES (?, 'derived', ?, ?, ?, ?, ?)
        """,
        (pattern_id, str(oxs_path), oxs_path.name, mime or "application/xml", cs, oxs_path.stat().st_size),
    )
    preview = pattern_dir / "recognition.png"
    if preview.is_file():
        cs_p = sha256_file(preview)
        conn.execute(
            """
            INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
            VALUES (?, 'derived', ?, ?, ?, ?, ?)
            """,
            (pattern_id, str(preview), preview.name, "image/png", cs_p, preview.stat().st_size),
        )
        thumb = pattern_dir / "thumb.jpg"
        try:
            from PIL import Image

            with Image.open(preview) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((320, 320))
                rgb.save(thumb, format="JPEG", quality=85)
            conn.execute(
                "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                (str(thumb), pattern_id),
            )
        except Exception:
            pass
    extra = f" ({', '.join(notes)})" if notes else ""
    w, h = meta.get("width_stitches"), meta.get("height_stitches")
    colors = meta.get("color_count")
    return f"{kind} ({w}×{h}, {colors} colours){extra}. Verify against your original."

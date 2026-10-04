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
from knitarr.services.chart_export import (
    CONVERSION_SOURCE_FILENAME,
    upsert_chart_export,
    upsert_chart_preview,
)
from knitarr.services.chart_symbol_modes import normalize_symbol_mode
from knitarr.services.image_to_oxs import (
    RASTER_SUFFIXES,
    _apply_crop,
    _load_raster,
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
    symbol_mode: str | None = None,
) -> str | None:
    from knitarr.services.craft_files import CHART_CRAFTS, PIXEL_CRAFTS, default_fabric_count

    if craft not in CHART_CRAFTS:
        return None
    suffix = primary.suffix.lower()
    mode = normalize_symbol_mode(symbol_mode)
    if suffix in STRUCTURED_SUFFIXES:
        if craft != "cross_stitch":
            return None
        norm = parse_saga(primary, title=title)
        recog = dict(norm.recognition or {})
        recog["symbol_mode"] = mode
        norm.recognition = recog
        return _store_normalized(
            conn,
            pattern_id,
            pattern_dir,
            norm,
            kind="Converted Saga chart",
            notes=[],
            symbol_mode=mode,
        )
    if suffix == ".xsp" and not looks_like_xps(primary):
        raise ValueError(
            "XSPro Platinum (.xsp) files are encrypted and cannot be converted to OXS. "
            "If this is a Microsoft XPS document, rename it to .xps."
        )
    if suffix not in RASTER_SUFFIXES and not (suffix == ".xsp" and looks_like_xps(primary)):
        return None
    try:
        # Persist the cropped raster used for conversion (Chart Export page 1).
        try:
            from PIL import Image

            src = _apply_crop(_load_raster(primary, pdf_page=pdf_page, pdf_zoom=3.0), crop)
            src_path = pattern_dir / CONVERSION_SOURCE_FILENAME
            src.convert("RGB").save(src_path, format="JPEG", quality=90, optimize=True)
        except Exception as e:
            log.warning("Could not save conversion source for pattern %s: %s", pattern_id, e)

        norm = convert_raster_to_normalized(primary, title=title, crop=crop, pdf_page=pdf_page)
        notes: list[str] = []
        if pdf_page > 0:
            label = "XPS" if suffix in {".xps", ".oxps", ".xsp"} else "PDF"
            notes.append(f"{label} page {pdf_page + 1}")
        if crop:
            notes.append("cropped region")
        recog = dict(norm.recognition or {})
        recog["symbol_mode"] = mode
        recog["conversion_source"] = CONVERSION_SOURCE_FILENAME
        recog["craft"] = craft
        if crop:
            recog["crop"] = {"x": crop.x, "y": crop.y, "w": crop.w, "h": crop.h}
        if pdf_page >= 0:
            recog["pdf_page"] = pdf_page + 1
        if craft in PIXEL_CRAFTS:
            norm.fabric_count = default_fabric_count(craft)
            notes.append(f"{craft.replace('_', ' ')} ({norm.fabric_count}-count grid)")
        norm.recognition = recog
        source = getattr(norm, "chart_source", None)
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
        return _store_normalized(
            conn,
            pattern_id,
            pattern_dir,
            norm,
            kind=kind,
            notes=notes,
            symbol_mode=mode,
        )
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
    symbol_mode: str | None = None,
) -> str:
    oxs_path, json_path = write_conversion_artifacts(pattern_dir, norm)
    # Keep conversion_source.jpg; wipe other derived roles then re-add.
    conn.execute(
        """
        DELETE FROM pattern_files
        WHERE pattern_id = ? AND role = 'derived'
          AND filename != ?
        """,
        (pattern_id, CONVERSION_SOURCE_FILENAME),
    )
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
    src = pattern_dir / CONVERSION_SOURCE_FILENAME
    if src.is_file():
        cs_s = sha256_file(src)
        existing_src = conn.execute(
            "SELECT id FROM pattern_files WHERE pattern_id = ? AND filename = ?",
            (pattern_id, src.name),
        ).fetchone()
        if existing_src:
            conn.execute(
                "UPDATE pattern_files SET path = ?, mime_type = ?, checksum_sha256 = ?, size_bytes = ?, role = ? WHERE id = ?",
                (str(src), "image/jpeg", cs_s, src.stat().st_size, "derived", existing_src["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
                VALUES (?, 'derived', ?, ?, ?, ?, ?)
                """,
                (pattern_id, str(src), src.name, "image/jpeg", cs_s, src.stat().st_size),
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
    upsert_chart_preview(conn, pattern_id, pattern_dir, norm)
    upsert_chart_export(conn, pattern_id, pattern_dir, norm, symbol_mode=symbol_mode)
    extra = f" ({', '.join(notes)})" if notes else ""
    w, h = meta.get("width_stitches"), meta.get("height_stitches")
    colors = meta.get("color_count")
    return f"{kind} ({w}×{h}, {colors} colours){extra}. Verify against your original."

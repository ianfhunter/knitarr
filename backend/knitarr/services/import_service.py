from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.indexers.registry import get_indexer
from knitarr.models import ExternalDetail, LicenseClass, PatternFormat
from knitarr.parsers.oxs import metadata_from_oxs, parse_oxs, write_normalized
from knitarr.services import dedupe
from knitarr.services.chart_conversion import try_convert_upload_to_chart
from knitarr.services.checksum import sha256_file
from knitarr.services.image_to_oxs import DOCUMENT_SUFFIXES, raster_preview_image

log = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_format(filename: str) -> PatternFormat:
    from knitarr.services.embroidery import MACHINE_SUFFIXES

    lower = filename.lower()
    if lower.endswith(".oxs"):
        return PatternFormat.OXS
    if lower.endswith(".pdf"):
        return PatternFormat.PDF
    if lower.endswith((".xps", ".oxps")):
        return PatternFormat.XPS
    if lower.endswith(".saga"):
        return PatternFormat.SAGA
    if lower.endswith(".xsp"):
        return PatternFormat.XSP
    if lower.endswith(".fold"):
        return PatternFormat.ORIGAMI
    if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return PatternFormat.IMAGE
    suf = Path(filename).suffix.lower()
    if suf in MACHINE_SUFFIXES:
        return PatternFormat.EMBROIDERY
    return PatternFormat.UNKNOWN


_PRIMARY_RANK = {
    ".oxs": 0,
    ".pes": 1,
    ".dst": 2,
    ".jef": 3,
    ".exp": 4,
    ".vp3": 5,
    ".fold": 6,
    ".saga": 7,
    ".xps": 8,
    ".oxps": 9,
    ".pdf": 10,
    ".xsp": 11,
}


async def download_urls(
    urls: list[tuple[str, str]],
    dest_dir: Path,
    user_agent: str,
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    async with httpx.AsyncClient(
        timeout=120.0,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
    ) as client:
        for url, filename in urls:
            dest = dest_dir / filename
            if dest.exists():
                paths.append(dest)
                continue
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            paths.append(dest)
    return paths


def _make_thumbnail(path: Path, thumb_path: Path) -> None:
    try:
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_SUFFIXES or suffix == ".xsp":
            im = raster_preview_image(path, max_side=320)
            im.save(thumb_path, format="JPEG", quality=85)
            return
        with Image.open(path) as im:
            im.thumbnail((320, 320))
            im.save(thumb_path, format="JPEG", quality=85)
    except Exception as e:
        log.debug("thumbnail failed: %s", e)


def import_downloaded_files(
    conn,
    detail: ExternalDetail,
    file_paths: list[Path],
    external_release_id: int | None,
) -> tuple[int | None, int | None, str]:
    """Returns (pattern_id, duplicate_of, message)."""
    if not file_paths:
        return None, None, "No files to import"

    primary = min(file_paths, key=lambda p: _PRIMARY_RANK.get(p.suffix.lower(), 99))

    checksum = sha256_file(primary)
    dup = dedupe.find_checksum_duplicate(conn, checksum)
    if dup:
        return None, dup, f"Duplicate file already in library (pattern #{dup})"

    now = _utc_now()
    fmt = _detect_format(primary.name)
    pattern_dir = settings.library_dir / f"pending_{checksum[:12]}"
    pattern_dir.mkdir(parents=True, exist_ok=True)
    stored_files: list[tuple[Path, str, str]] = []

    stored_names: list[str] = []
    for src in file_paths:
        dest = pattern_dir / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        cs = sha256_file(dest)
        mime, _ = mimetypes.guess_type(dest.name)
        stored_files.append((dest, cs, mime or "application/octet-stream"))
        stored_names.append(src.name)

    normalized_path = None
    structure_fp = None
    meta_extra: dict = {}
    oxs_norm = None
    if fmt == PatternFormat.OXS:
        oxs_norm = parse_oxs(primary)
        normalized_path = pattern_dir / "normalized.json"
        write_normalized(normalized_path, oxs_norm)
        structure_fp = dedupe.fingerprint_from_normalized(oxs_norm)
        meta_extra = metadata_from_oxs(oxs_norm)
        dup_struct = dedupe.find_structure_duplicate(conn, structure_fp)
        if dup_struct:
            shutil.rmtree(pattern_dir, ignore_errors=True)
            return None, dup_struct, f"Duplicate structure matches pattern #{dup_struct}"

    thumb_path = pattern_dir / "thumb.jpg"
    _make_thumbnail(primary, thumb_path)
    if not thumb_path.exists():
        # Prefer an accompanying image from the download before synthesizing a chart preview.
        for src in file_paths:
            if src.resolve() == primary.resolve():
                continue
            if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
                _make_thumbnail(src, thumb_path)
                if thumb_path.exists():
                    break
    chart_preview_path = None
    if oxs_norm is not None:
        from knitarr.services.chart_export import CHART_PREVIEW_FILENAME, write_chart_preview_image

        try:
            chart_preview_path = write_chart_preview_image(
                pattern_dir / CHART_PREVIEW_FILENAME, oxs_norm
            )
        except Exception as e:
            log.debug("chart preview failed: %s", e)
            chart_preview_path = None
        if not thumb_path.exists() and chart_preview_path and chart_preview_path.is_file():
            try:
                shutil.copy2(chart_preview_path, thumb_path)
            except OSError:
                _make_thumbnail(chart_preview_path, thumb_path)
    if not thumb_path.exists():
        thumb_path = None

    cur = conn.execute(
        """
        INSERT INTO patterns (
            external_release_id, title, designer, source, source_url, pattern_url,
            craft, description, license_class, redistribution_allowed, downloaded,
            checksum_sha256, structure_fingerprint, pattern_format,
            width_stitches, height_stitches, stitch_count, color_count, fabric_count,
            floss_brand, date_discovered, date_downloaded, thumbnail_path, normalized_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            external_release_id,
            detail.title,
            detail.designer,
            detail.indexer_id,
            detail.source_url,
            detail.pattern_url,
            detail.craft,
            detail.description,
            detail.license_class.value,
            1 if detail.redistribution_allowed else 0,
            checksum,
            structure_fp,
            fmt.value,
            meta_extra.get("width_stitches"),
            meta_extra.get("height_stitches"),
            meta_extra.get("stitch_count"),
            meta_extra.get("color_count"),
            meta_extra.get("fabric_count"),
            meta_extra.get("floss_brand"),
            now,
            now,
            str(thumb_path) if thumb_path else None,
            str(normalized_path) if normalized_path else None,
        ),
    )
    pattern_id = int(cur.lastrowid)
    final_dir = settings.library_dir / str(pattern_id)
    if pattern_dir != final_dir:
        if final_dir.exists():
            shutil.rmtree(final_dir)
        pattern_dir.rename(final_dir)
        stored_files = [
            (final_dir / name, cs, mime) for name, (_, cs, mime) in zip(stored_names, stored_files)
        ]
        if normalized_path:
            normalized_path = final_dir / "normalized.json"
        if thumb_path:
            thumb_path = final_dir / "thumb.jpg"
        if chart_preview_path:
            from knitarr.services.chart_export import CHART_PREVIEW_FILENAME

            chart_preview_path = final_dir / CHART_PREVIEW_FILENAME
        conn.execute(
            "UPDATE patterns SET thumbnail_path = ?, normalized_path = ? WHERE id = ?",
            (
                str(thumb_path) if thumb_path and thumb_path.exists() else None,
                str(normalized_path) if normalized_path and normalized_path.exists() else None,
                pattern_id,
            ),
        )

    for path, cs, mime in stored_files:
        conn.execute(
            """
            INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
            VALUES (?, 'original', ?, ?, ?, ?, ?)
            """,
            (pattern_id, str(path), path.name, mime, cs, path.stat().st_size),
        )

    dedupe.suggest_metadata_duplicates(
        conn,
        pattern_id,
        detail.title,
        meta_extra.get("width_stitches"),
        meta_extra.get("height_stitches"),
        meta_extra.get("color_count"),
    )

    conn.execute(
        """
        INSERT INTO projects (pattern_id, status, progress_json, updated_at)
        VALUES (?, 'not_started', '{}', ?)
        """,
        (pattern_id, now),
    )

    msg = "Imported successfully"
    primary_path = final_dir / primary.name
    try:
        conv = try_convert_upload_to_chart(
            conn,
            pattern_id,
            final_dir,
            primary_path,
            title=detail.title,
            craft=detail.craft,
        )
    except ValueError as e:
        log.info("Skipped chart conversion for pattern %s: %s", pattern_id, e)
        conv = None
    if conv:
        msg = f"{msg} {conv}"
    elif oxs_norm is not None:
        from knitarr.services.chart_export import upsert_chart_export, upsert_chart_preview

        preview = upsert_chart_preview(conn, pattern_id, final_dir, oxs_norm)
        thumb = final_dir / "thumb.jpg"
        if preview and preview.is_file() and not thumb.is_file():
            try:
                shutil.copy2(preview, thumb)
            except OSError:
                _make_thumbnail(preview, thumb)
            if thumb.is_file():
                conn.execute(
                    "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                    (str(thumb), pattern_id),
                )
        if upsert_chart_export(conn, pattern_id, final_dir, oxs_norm):
            msg = f"{msg} Chart Export.pdf ready."

    # Machine embroidery / quilting designs
    from knitarr.services.craft_files import MACHINE_CRAFTS
    from knitarr.services.embroidery import is_machine_embroidery_file, process_machine_file
    from knitarr.services.origami import is_fold_file, process_fold

    if detail.craft in MACHINE_CRAFTS or is_machine_embroidery_file(primary_path):
        try:
            meta = process_machine_file(pattern_id, primary_path if is_machine_embroidery_file(primary_path) else None)
            msg = f"{msg} Machine design parsed ({meta.get('stitch_count') or '?'} stitches)."
        except Exception as e:
            log.info("Machine embroidery parse skipped for pattern %s: %s", pattern_id, e)

    if detail.craft == "origami" or is_fold_file(primary_path):
        try:
            ometa = process_fold(pattern_id, primary_path if is_fold_file(primary_path) else None)
            msg = f"{msg} Origami crease pattern loaded ({ometa.get('edge_count') or '?'} edges)."
        except Exception as e:
            log.info("Origami parse skipped for pattern %s: %s", pattern_id, e)

    return pattern_id, None, msg


def import_local_file(
    conn,
    src_path: Path,
    title: str | None = None,
    *,
    craft: str = "cross_stitch",
    license_class: LicenseClass = LicenseClass.USER_OWNED,
) -> tuple[int | None, int | None, str]:
    detail = ExternalDetail(
        indexer_id="user_import",
        external_id=src_path.name,
        title=title or src_path.stem,
        source_url="",
        craft=craft,
        license_class=license_class,
        redistribution_allowed=False,
        download_available=True,
    )
    return import_downloaded_files(conn, detail, [src_path], None)


async def import_from_indexer(indexer_id: str, external_id: str, *, craft: str = "cross_stitch"):
    from knitarr.models import ImportResult
    from knitarr.services import catalog

    indexer = get_indexer(indexer_id)
    detail = await indexer.get_pattern(external_id, craft=craft)
    release_id = catalog.upsert_external_release(detail)
    spec = await indexer.get_download(external_id, craft=craft)
    if not spec:
        raise ValueError("This source has no downloadable file — open the site and import it yourself")
    urls = spec.all_urls if spec.all_urls else [(spec.url, spec.filename)]
    with tempfile.TemporaryDirectory() as tmp:
        paths = await download_urls(urls, Path(tmp), settings.ia_user_agent)
        with get_conn() as conn:
            pattern_id, dup, msg = import_downloaded_files(conn, detail, paths, release_id)
    if dup:
        return ImportResult(pattern_id=None, duplicate_of=dup, message=msg)
    if not pattern_id:
        raise ValueError(msg or "Import failed")
    return ImportResult(pattern_id=pattern_id, duplicate_of=None, message=msg)

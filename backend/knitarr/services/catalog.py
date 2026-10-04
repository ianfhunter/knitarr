"""DB helpers for pattern library queries."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.models import (
    ExternalHit,
    LicenseClass,
    PatternDetail,
    PatternFormat,
    PatternSummary,
    ProjectStatus,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_indexers() -> None:
    from knitarr.indexers.registry import list_indexers

    with get_conn() as conn:
        for idx in list_indexers():
            cap = idx.capabilities
            conn.execute(
                """
                INSERT INTO indexers (id, name, source, access_method, auth_required,
                    automated_access_policy, default_license_class, can_download)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name
                """,
                (
                    idx.id,
                    idx.name,
                    cap.source,
                    cap.access_method,
                    cap.authentication,
                    cap.automated_access_policy,
                    cap.license_default.value,
                    1 if cap.can_download else 0,
                ),
            )


async def upsert_external_release(hit: ExternalHit) -> int:
    now = _utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO external_releases (
                indexer_id, external_id, title, designer, source_url, pattern_url,
                description, metadata_json, license_class, redistribution_allowed, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(indexer_id, external_id) DO UPDATE SET
                title=excluded.title,
                designer=excluded.designer,
                description=excluded.description,
                metadata_json=excluded.metadata_json,
                license_class=excluded.license_class,
                redistribution_allowed=excluded.redistribution_allowed,
                last_seen_at=excluded.last_seen_at
            """,
            (
                hit.indexer_id,
                hit.external_id,
                hit.title,
                hit.designer,
                hit.source_url,
                hit.pattern_url,
                hit.description,
                json.dumps({**hit.metadata, "craft": hit.craft}),
                hit.license_class.value,
                1 if hit.redistribution_allowed else 0,
                now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM external_releases WHERE indexer_id = ? AND external_id = ?",
            (hit.indexer_id, hit.external_id),
        ).fetchone()
        return int(row["id"])


def _row_to_summary(row) -> PatternSummary:
    return PatternSummary(
        id=int(row["id"]),
        title=row["title"],
        designer=row["designer"],
        source=row["source"],
        source_url=row["source_url"],
        craft=row["craft"],
        license_class=LicenseClass(row["license_class"]),
        redistribution_allowed=bool(row["redistribution_allowed"]),
        pattern_format=PatternFormat(row["pattern_format"]),
        downloaded=bool(row["downloaded"]),
        width_stitches=row["width_stitches"],
        height_stitches=row["height_stitches"],
        color_count=row["color_count"],
        thumbnail_url=f"/api/patterns/{row['id']}/thumbnail",
        date_discovered=row["date_discovered"],
        date_downloaded=row["date_downloaded"],
    )


def list_patterns(
    *,
    downloaded_only: bool | None = None,
    limit: int = 100,
) -> list[PatternSummary]:
    q = "SELECT * FROM patterns WHERE 1=1"
    params: list = []
    if downloaded_only is True:
        q += " AND downloaded = 1"
    elif downloaded_only is False:
        q += " AND downloaded = 0"
    q += " ORDER BY COALESCE(date_downloaded, date_discovered) DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_row_to_summary(r) for r in rows]


def get_pattern_detail(pattern_id: int) -> PatternDetail | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            return None
        proj = conn.execute(
            "SELECT status FROM projects WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()
        files = conn.execute(
            "SELECT COUNT(*) AS c FROM pattern_files WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()
        tags = conn.execute(
            """
            SELECT t.name FROM pattern_tags t
            JOIN pattern_tag_map m ON m.tag_id = t.id
            WHERE m.pattern_id = ?
            """,
            (pattern_id,),
        ).fetchall()
    base = _row_to_summary(row)
    return PatternDetail(
        **base.model_dump(),
        description=row["description"],
        tags=[t["name"] for t in tags],
        difficulty=row["difficulty"],
        fabric_type=row["fabric_type"],
        fabric_count=row["fabric_count"],
        floss_brand=row["floss_brand"],
        checksum_sha256=row["checksum_sha256"],
        has_normalized=bool(row["normalized_path"]),
        project_status=ProjectStatus(proj["status"]) if proj else None,
        file_count=int(files["c"]) if files else 0,
    )


def delete_pattern(pattern_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute("SELECT id, source FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        source = row["source"] or ""
        if source not in ("user_import", "manual"):
            raise PermissionError("Only uploads imported via Library can be deleted")
        conn.execute(
            "DELETE FROM dedupe_candidates WHERE pattern_id_a = ? OR pattern_id_b = ?",
            (pattern_id, pattern_id),
        )
        conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
    lib_dir = settings.library_dir / str(pattern_id)
    if lib_dir.is_dir():
        shutil.rmtree(lib_dir, ignore_errors=True)


_PRIMARY_RANK = {
    ".oxs": 0,
    ".saga": 1,
    ".xps": 2,
    ".oxps": 3,
    ".pdf": 4,
    ".xsp": 5,
}


def _upload_primary_path(conn, pattern_id: int, lib_dir: Path) -> Path:
    files = conn.execute(
        """
        SELECT path, filename FROM pattern_files
        WHERE pattern_id = ? AND role = 'original'
        ORDER BY id
        """,
        (pattern_id,),
    ).fetchall()
    if not files:
        raise ValueError("No original file found")
    files = sorted(files, key=lambda row: _PRIMARY_RANK.get(Path(row["filename"]).suffix.lower(), 99))
    primary = Path(files[0]["path"])
    if not primary.is_file():
        primary = lib_dir / files[0]["filename"]
    return primary


def _write_thumb_from_image(src: Path, dest: Path) -> bool:
    from PIL import Image

    from knitarr.services.image_to_oxs import document_filetype, raster_preview_image

    try:
        if document_filetype(src):
            im = raster_preview_image(src, max_side=320)
        else:
            with Image.open(src) as opened:
                im = opened.convert("RGB")
                im.thumbnail((320, 320))
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.convert("RGB").save(dest, format="JPEG", quality=85)
        return dest.is_file()
    except Exception:
        return False


def ensure_thumbnail(pattern_id: int) -> Path | None:
    """Create thumb.jpg from a chart preview or the original file if missing."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT thumbnail_path FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
        if not row:
            raise KeyError(pattern_id)
        current = Path(row["thumbnail_path"]) if row["thumbnail_path"] else None
        if current and current.is_file():
            return current
        lib_dir = settings.library_dir / str(pattern_id)
        dest = lib_dir / "thumb.jpg"
        candidates: list[Path] = []
        for name in ("recognition.png",):
            p = lib_dir / name
            if p.is_file():
                candidates.append(p)
        for extra in sorted(lib_dir.glob("*preview*.jpg")):
            candidates.append(extra)
        try:
            candidates.append(_upload_primary_path(conn, pattern_id, lib_dir))
        except ValueError:
            pass
        for src in candidates:
            if src.is_file() and _write_thumb_from_image(src, dest):
                conn.execute(
                    "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                    (str(dest), pattern_id),
                )
                return dest
    return None


def pdf_info(pattern_id: int) -> dict:
    from knitarr.services.image_to_oxs import document_filetype, pdf_page_count

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        lib_dir = settings.library_dir / str(pattern_id)
        primary = _upload_primary_path(conn, pattern_id, lib_dir)
    filetype = document_filetype(primary)
    is_paged = filetype is not None
    pages = pdf_page_count(primary) if is_paged else 1
    return {
        "is_pdf": primary.suffix.lower() == ".pdf",
        "is_paged": is_paged,
        "page_count": pages,
    }


def raster_preview_jpeg(pattern_id: int, *, pdf_page: int = 1) -> bytes:
    from io import BytesIO

    from knitarr.services.image_to_oxs import RASTER_SUFFIXES, document_filetype, raster_preview_image

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        lib_dir = settings.library_dir / str(pattern_id)
        primary = _upload_primary_path(conn, pattern_id, lib_dir)
    if primary.suffix.lower() not in RASTER_SUFFIXES and not document_filetype(primary):
        raise ValueError("No raster preview for this format")
    page_idx = max(0, pdf_page - 1)
    im = raster_preview_image(primary, pdf_page=page_idx)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def convert_pattern_to_chart(pattern_id: int, *, crop=None, pdf_page: int | None = None) -> str:
    from knitarr.models import CropRect
    from knitarr.services.chart_conversion import try_convert_upload_to_chart

    crop_rect: CropRect | None = None
    if crop is not None:
        crop_rect = crop if isinstance(crop, CropRect) else CropRect.model_validate(crop)
        crop_rect = crop_rect.clamped()
    page_idx = max(0, (pdf_page or 1) - 1)

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        if (row["source"] or "") not in ("user_import", "manual"):
            raise PermissionError("Conversion only applies to library uploads")
        craft = row["craft"] or "cross_stitch"
        lib_dir = settings.library_dir / str(pattern_id)
        primary = _upload_primary_path(conn, pattern_id, lib_dir)
        msg = try_convert_upload_to_chart(
            conn,
            pattern_id,
            lib_dir,
            primary,
            title=row["title"],
            craft=craft,
            crop=crop_rect,
            pdf_page=page_idx,
        )
        if not msg:
            raise ValueError(
                "Could not convert this file (needs a readable .saga, XPS/PDF, or cross-stitch JPG/PNG)"
            )
        return msg


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._()\[\] -]+")


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = _UNSAFE_FILENAME.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or name in {".", ".."}:
        raise ValueError("Invalid filename")
    if len(name) > 180:
        stem, ext = Path(name).stem[:150], Path(name).suffix[:20]
        name = f"{stem}{ext}" if ext else stem
    return name


def update_pattern(pattern_id: int, *, title: str | None = None, description: str | None = None) -> PatternDetail:
    with get_conn() as conn:
        row = conn.execute("SELECT id, title, normalized_path FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        new_title = title.strip() if title is not None else row["title"]
        if not new_title:
            raise ValueError("Title cannot be empty")
        fields = ["title = ?"]
        values: list = [new_title]
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        values.append(pattern_id)
        conn.execute(f"UPDATE patterns SET {', '.join(fields)} WHERE id = ?", values)
        npath = Path(row["normalized_path"]) if row["normalized_path"] else None
        if title is not None and npath and npath.is_file():
            from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, write_oxs

            raw = json.loads(npath.read_text(encoding="utf-8"))
            raw["title"] = new_title
            npath.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            oxs = _chart_oxs_path(conn, pattern_id, npath.parent)
            if oxs:
                pal = [PaletteEntry(**p) for p in raw.get("palette") or []]
                norm = NormalizedPattern(
                    title=new_title,
                    width_stitches=int(raw.get("width_stitches") or 0),
                    height_stitches=int(raw.get("height_stitches") or 0),
                    fabric_count=raw.get("fabric_count"),
                    palette=pal,
                    full_stitches=raw.get("full_stitches") or [],
                    backstitches=raw.get("backstitches") or [],
                    recognition=raw.get("recognition"),
                )
                write_oxs(oxs, norm)
    detail = get_pattern_detail(pattern_id)
    if not detail:
        raise KeyError(pattern_id)
    return detail


def rename_pattern_file(pattern_id: int, file_id: int, filename: str) -> dict:
    new_name = sanitize_filename(filename)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, path, filename FROM pattern_files WHERE id = ? AND pattern_id = ?",
            (file_id, pattern_id),
        ).fetchone()
        if not row:
            raise KeyError(file_id)
        src = Path(row["path"])
        if not src.is_file():
            src = settings.library_dir / str(pattern_id) / row["filename"]
        if not src.is_file():
            raise FileNotFoundError("File missing on disk")
        dest = src.parent / new_name
        if dest.resolve() != src.resolve() and dest.exists():
            raise ValueError("A file with that name already exists")
        if dest.resolve() != src.resolve():
            src.rename(dest)
        conn.execute(
            "UPDATE pattern_files SET path = ?, filename = ? WHERE id = ?",
            (str(dest), new_name, file_id),
        )
        pat = conn.execute(
            "SELECT normalized_path, thumbnail_path FROM patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        if pat and pat["normalized_path"] and Path(pat["normalized_path"]).resolve() == src.resolve():
            conn.execute("UPDATE patterns SET normalized_path = ? WHERE id = ?", (str(dest), pattern_id))
        if pat and pat["thumbnail_path"] and Path(pat["thumbnail_path"]).resolve() == src.resolve():
            conn.execute("UPDATE patterns SET thumbnail_path = ? WHERE id = ?", (str(dest), pattern_id))
        out = conn.execute(
            "SELECT id, filename, mime_type, role, size_bytes FROM pattern_files WHERE id = ?",
            (file_id,),
        ).fetchone()
    return dict(out)


def _chart_oxs_path(conn, pattern_id: int, lib_dir: Path) -> Path | None:
    rows = conn.execute(
        "SELECT path, filename, role FROM pattern_files WHERE pattern_id = ? ORDER BY id",
        (pattern_id,),
    ).fetchall()
    converted = lib_dir / "converted.oxs"
    for row in rows:
        name = (row["filename"] or "").lower()
        if name == "converted.oxs":
            return Path(row["path"]) if row["path"] else converted
    for row in rows:
        name = (row["filename"] or "").lower()
        if name.endswith(".oxs") and (row["role"] or "") == "original":
            return Path(row["path"]) if row["path"] else lib_dir / row["filename"]
    return converted if converted.is_file() else None


def save_chart(pattern_id: int, body) -> PatternDetail:
    from knitarr.parsers.oxs import (
        NormalizedPattern,
        PaletteEntry,
        metadata_from_oxs,
        write_normalized,
        write_oxs,
    )
    from knitarr.services import dedupe
    from knitarr.services.checksum import sha256_file

    pal_ids = {p.index for p in body.palette}
    if not pal_ids:
        raise ValueError("Chart needs a palette")
    stitches: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for st in body.full_stitches:
        if st.palindex not in pal_ids or st.palindex <= 0:
            continue
        if not (0 <= st.x < body.width_stitches and 0 <= st.y < body.height_stitches):
            continue
        key = (st.x, st.y)
        if key in seen:
            continue
        seen.add(key)
        stitches.append({"x": st.x, "y": st.y, "palindex": st.palindex})
        if len(stitches) > 200_000:
            raise ValueError("Too many stitches")
    backs: list[dict] = []
    bseen: set[tuple[int, int, int, int, int]] = set()
    for b in body.backstitches:
        if b.palindex not in pal_ids:
            continue
        if (b.x1, b.y1) == (b.x2, b.y2):
            continue
        if not (
            0 <= b.x1 <= body.width_stitches
            and 0 <= b.x2 <= body.width_stitches
            and 0 <= b.y1 <= body.height_stitches
            and 0 <= b.y2 <= body.height_stitches
        ):
            continue
        key = (b.x1, b.y1, b.x2, b.y2, b.palindex)
        if key in bseen:
            continue
        bseen.add(key)
        backs.append({"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "palindex": b.palindex})
        if len(backs) > 20_000:
            raise ValueError("Too many backstitches")
    counts: dict[int, int] = {}
    for st in stitches:
        counts[st["palindex"]] = counts.get(st["palindex"], 0) + 1
    from knitarr.services.image_to_oxs import looks_like_dmc_label, nearest_dmc, parse_hex_rgb

    palette = []
    for p in body.palette:
        color = p.color.replace("#", "").upper()
        if len(color) != 6:
            raise ValueError(f"Invalid colour for palette {p.index}")
        number = (p.number or "").strip()
        name = (p.name or "").strip()
        if p.index > 0 and not looks_like_dmc_label(number) and not looks_like_dmc_label(name):
            number, name, color = nearest_dmc(parse_hex_rgb(color))
        elif not number:
            number = name or f"Colour {p.index}"
        if not name:
            name = number
        palette.append(
            PaletteEntry(
                index=p.index,
                number=number,
                name=name,
                color=color,
                symbol=p.symbol,
                stitch_count=counts.get(p.index, 0),
            )
        )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title, normalized_path FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
        if not row:
            raise KeyError(pattern_id)
        lib_dir = settings.library_dir / str(pattern_id)
        lib_dir.mkdir(parents=True, exist_ok=True)
        npath = Path(row["normalized_path"]) if row["normalized_path"] else lib_dir / "normalized.json"
        title = (body.title or row["title"] or "Chart").strip()
        existing = {}
        if npath.is_file():
            try:
                existing = json.loads(npath.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        norm = NormalizedPattern(
            title=title,
            width_stitches=body.width_stitches,
            height_stitches=body.height_stitches,
            fabric_count=existing.get("fabric_count") or 14,
            palette=palette,
            full_stitches=stitches,
            backstitches=backs,
            recognition=existing.get("recognition"),
        )
        write_normalized(npath, norm)
        oxs_path = _chart_oxs_path(conn, pattern_id, lib_dir) or (lib_dir / "converted.oxs")
        write_oxs(oxs_path, norm)
        meta = metadata_from_oxs(norm)
        conn.execute(
            """
            UPDATE patterns SET
                title = ?,
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
                title,
                str(npath),
                meta.get("width_stitches"),
                meta.get("height_stitches"),
                meta.get("stitch_count"),
                meta.get("color_count"),
                dedupe.fingerprint_from_normalized(norm),
                meta.get("floss_brand"),
                pattern_id,
            ),
        )
        existing_oxs = conn.execute(
            "SELECT id FROM pattern_files WHERE pattern_id = ? AND filename = ?",
            (pattern_id, oxs_path.name),
        ).fetchone()
        if not existing_oxs:
            mime = "application/xml"
            conn.execute(
                """
                INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
                VALUES (?, 'derived', ?, ?, ?, ?, ?)
                """,
                (pattern_id, str(oxs_path), oxs_path.name, mime, sha256_file(oxs_path), oxs_path.stat().st_size),
            )
        else:
            conn.execute(
                "UPDATE pattern_files SET path = ?, checksum_sha256 = ?, size_bytes = ? WHERE id = ?",
                (str(oxs_path), sha256_file(oxs_path), oxs_path.stat().st_size, existing_oxs["id"]),
            )
        if not conn.execute("SELECT 1 FROM pattern_files WHERE pattern_id = ? AND filename = ?", (pattern_id, npath.name)).fetchone():
            conn.execute(
                """
                INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
                VALUES (?, 'derived', ?, ?, ?, ?, ?)
                """,
                (
                    pattern_id,
                    str(npath),
                    npath.name,
                    "application/json",
                    sha256_file(npath),
                    npath.stat().st_size,
                ),
            )
    detail = get_pattern_detail(pattern_id)
    if not detail:
        raise KeyError(pattern_id)
    return detail

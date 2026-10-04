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
    craft: str | None = None,
    limit: int = 100,
) -> list[PatternSummary]:
    q = "SELECT * FROM patterns WHERE 1=1"
    params: list = []
    if downloaded_only is True:
        q += " AND downloaded = 1"
    elif downloaded_only is False:
        q += " AND downloaded = 0"
    if craft:
        q += " AND craft = ?"
        params.append(craft)
    q += " ORDER BY COALESCE(date_downloaded, date_discovered) DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_row_to_summary(r) for r in rows]


def ensure_chart_export(pattern_id: int) -> None:
    """Create Chart Export.pdf when a normalized chart exists but the PDF is missing."""
    from knitarr.services.chart_export import CHART_EXPORT_FILENAME, upsert_chart_export

    with get_conn() as conn:
        row = conn.execute(
            "SELECT normalized_path FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
        if not row or not row["normalized_path"]:
            return
        npath = Path(row["normalized_path"])
        if not npath.is_file():
            return
        existing = conn.execute(
            "SELECT path FROM pattern_files WHERE pattern_id = ? AND filename = ?",
            (pattern_id, CHART_EXPORT_FILENAME),
        ).fetchone()
        if existing and Path(existing["path"]).is_file():
            return
        try:
            raw = json.loads(npath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        from knitarr.parsers.oxs import normalized_from_dict

        norm = normalized_from_dict(raw)
        upsert_chart_export(conn, pattern_id, npath.parent, norm)


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
            "SELECT thumbnail_path, normalized_path, pattern_format FROM patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        if not row:
            raise KeyError(pattern_id)
        current = Path(row["thumbnail_path"]) if row["thumbnail_path"] else None
        if current and current.is_file():
            return current
        lib_dir = settings.library_dir / str(pattern_id)
        dest = lib_dir / "thumb.jpg"
        candidates: list[Path] = []
        for name in ("recognition.png", "chart_preview.jpg"):
            p = lib_dir / name
            if p.is_file():
                candidates.append(p)
        for extra in sorted(lib_dir.glob("*preview*.jpg")):
            if extra not in candidates:
                candidates.append(extra)

        # OXS (and other normalized charts) without a source image: synthesize from stitches.
        preview = lib_dir / "chart_preview.jpg"
        if not preview.is_file() and row["normalized_path"]:
            npath = Path(row["normalized_path"])
            if npath.is_file():
                try:
                    from knitarr.parsers.oxs import normalized_from_dict
                    from knitarr.services.chart_export import (
                        upsert_chart_preview,
                        write_chart_preview_image,
                    )

                    raw = json.loads(npath.read_text(encoding="utf-8"))
                    norm = normalized_from_dict(raw)
                    write_chart_preview_image(preview, norm)
                    upsert_chart_preview(conn, pattern_id, lib_dir, norm)
                except Exception:
                    pass
        if preview.is_file() and preview not in candidates:
            candidates.insert(0, preview)

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
            # chart_preview.jpg is already a JPEG — copy directly if PIL open fails oddly
            if src.name == "chart_preview.jpg" and src.is_file():
                try:
                    import shutil

                    shutil.copy2(src, dest)
                    if dest.is_file():
                        conn.execute(
                            "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                            (str(dest), pattern_id),
                        )
                        return dest
                except OSError:
                    pass
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


def convert_pattern_to_chart(
    pattern_id: int,
    *,
    crop=None,
    pdf_page: int | None = None,
    symbol_mode: str | None = None,
) -> str:
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
            symbol_mode=symbol_mode,
        )
        if not msg:
            raise ValueError(
                "Could not convert this file (needs a readable .saga, XPS/PDF, or cross-stitch JPG/PNG)"
            )
        return msg


def regenerate_pattern_package(pattern_id: int, *, symbol_mode: str | None = None) -> str:
    """Rebuild derived preview/export files from the saved normalized chart (no reprocess)."""
    from knitarr.parsers.oxs import normalized_from_dict, write_normalized
    from knitarr.services.chart_export import upsert_chart_export, upsert_chart_preview
    from knitarr.services.chart_symbol_modes import normalize_symbol_mode
    import shutil

    mode = normalize_symbol_mode(symbol_mode) if symbol_mode is not None else None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT normalized_path, thumbnail_path FROM patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        if not row or not row["normalized_path"]:
            raise ValueError("No stitch chart to package — generate or reprocess a chart first")
        npath = Path(row["normalized_path"])
        if not npath.is_file():
            raise ValueError("Normalized chart file is missing")
        lib_dir = settings.library_dir / str(pattern_id)
        try:
            raw = json.loads(npath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Normalized chart unreadable") from exc
        if mode is not None:
            recog = dict(raw.get("recognition") or {})
            recog["symbol_mode"] = mode
            raw["recognition"] = recog
            npath.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        norm = normalized_from_dict(raw)
        if mode is not None:
            recog2 = dict(norm.recognition or {})
            recog2["symbol_mode"] = mode
            norm.recognition = recog2
            write_normalized(npath, norm)
        preview = upsert_chart_preview(conn, pattern_id, lib_dir, norm)
        export = upsert_chart_export(conn, pattern_id, lib_dir, norm, symbol_mode=mode)
        thumb = lib_dir / "thumb.jpg"
        if preview and preview.is_file():
            try:
                shutil.copy2(preview, thumb)
                conn.execute(
                    "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                    (str(thumb), pattern_id),
                )
            except OSError:
                pass
        bits = []
        if preview:
            bits.append("chart preview")
        if export:
            bits.append("Chart Export.pdf")
        if not bits:
            raise ValueError("Failed to regenerate derived files")
        return f"Regenerated {', '.join(bits)}."


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
            from knitarr.parsers.oxs import normalized_from_dict, write_oxs

            raw = json.loads(npath.read_text(encoding="utf-8"))
            raw["title"] = new_title
            npath.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            oxs = _chart_oxs_path(conn, pattern_id, npath.parent)
            if oxs:
                write_oxs(oxs, normalized_from_dict(raw))
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
    parts: list[dict] = []
    pseen: set[tuple[int, int, int, int, int]] = set()
    for ps in body.part_stitches:
        p1 = int(ps.palindex1 or 0)
        p2 = int(ps.palindex2 or 0)
        if p1 <= 0 and p2 <= 0:
            continue
        if p1 > 0 and p1 not in pal_ids:
            continue
        if p2 > 0 and p2 not in pal_ids:
            continue
        if not (0 <= ps.x < body.width_stitches and 0 <= ps.y < body.height_stitches):
            continue
        direction = int(ps.direction or 1)
        if direction not in (1, 2, 3, 4):
            direction = 1
        key = (ps.x, ps.y, p1, p2, direction)
        if key in pseen:
            continue
        pseen.add(key)
        entry = {"x": ps.x, "y": ps.y, "palindex1": p1, "palindex2": p2, "direction": direction}
        if ps.major not in (None, 0):
            entry["major"] = int(ps.major)
        parts.append(entry)
        if len(parts) > 100_000:
            raise ValueError("Too many part stitches")
    backs: list[dict] = []
    bseen: set[tuple[float, float, float, float, int]] = set()
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
        key = (float(b.x1), float(b.y1), float(b.x2), float(b.y2), b.palindex)
        if key in bseen:
            continue
        bseen.add(key)
        backs.append({"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "palindex": b.palindex})
        if len(backs) > 20_000:
            raise ValueError("Too many backstitches")
    orns: list[dict] = []
    oseen: set[tuple[float, float, int, str]] = set()
    for o in body.ornaments:
        if o.palindex not in pal_ids or o.palindex <= 0:
            continue
        if not (
            -1 <= o.x <= body.width_stitches + 1 and -1 <= o.y <= body.height_stitches + 1
        ):
            continue
        otype = (o.objecttype or "knot").strip() or "knot"
        if len(otype) > 40:
            otype = otype[:40]
        key = (round(float(o.x), 4), round(float(o.y), 4), o.palindex, otype)
        if key in oseen:
            continue
        oseen.add(key)
        entry = {"x": float(o.x), "y": float(o.y), "palindex": o.palindex, "objecttype": otype}
        if o.direction is not None:
            entry["direction"] = int(o.direction)
        orns.append(entry)
        if len(orns) > 50_000:
            raise ValueError("Too many ornaments")
    counts: dict[int, int] = {}
    for st in stitches:
        counts[st["palindex"]] = counts.get(st["palindex"], 0) + 1
    for ps in parts:
        if ps["palindex1"] > 0:
            counts[ps["palindex1"]] = counts.get(ps["palindex1"], 0) + 1
        if ps["palindex2"] > 0:
            counts[ps["palindex2"]] = counts.get(ps["palindex2"], 0) + 1
    for o in orns:
        counts[o["palindex"]] = counts.get(o["palindex"], 0) + 1
    for b in backs:
        counts[b["palindex"]] = counts.get(b["palindex"], 0) + 1
    from knitarr.services.floss_catalog import looks_like_floss_label, nearest_floss, parse_hex_rgb
    from knitarr.services.supplies import get_preferred_floss_brand

    floss_brand = get_preferred_floss_brand()
    palette = []
    for p in body.palette:
        color = p.color.replace("#", "").upper()
        if len(color) != 6:
            raise ValueError(f"Invalid colour for palette {p.index}")
        number = (p.number or "").strip()
        name = (p.name or "").strip()
        if p.index > 0 and not looks_like_floss_label(number) and not looks_like_floss_label(name):
            number, name, color = nearest_floss(parse_hex_rgb(color), brand=floss_brand)
        elif not number:
            number = name or f"Colour {p.index}"
        if not name:
            name = number
        strands = max(1, min(6, int(getattr(p, "strands", 2) or 2)))
        palette.append(
            PaletteEntry(
                index=p.index,
                number=number,
                name=name,
                color=color,
                symbol=p.symbol,
                stitch_count=counts.get(p.index, 0),
                strands=strands,
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
        recog = dict(existing.get("recognition") or {})
        if getattr(body, "symbol_mode", None) is not None:
            from knitarr.services.chart_symbol_modes import normalize_symbol_mode

            recog["symbol_mode"] = normalize_symbol_mode(body.symbol_mode)
        fabric_count = body.fabric_count if body.fabric_count is not None else existing.get("fabric_count") or 14
        try:
            fabric_count = max(6, min(40, int(fabric_count)))
        except (TypeError, ValueError):
            fabric_count = 14
        norm = NormalizedPattern(
            title=title,
            width_stitches=body.width_stitches,
            height_stitches=body.height_stitches,
            fabric_count=fabric_count,
            palette=palette,
            full_stitches=stitches,
            backstitches=backs,
            part_stitches=parts,
            ornaments=orns,
            recognition=recog or None,
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
                fabric_count = ?,
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
                meta.get("fabric_count"),
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
        from knitarr.services.chart_export import upsert_chart_export, upsert_chart_preview

        upsert_chart_preview(conn, pattern_id, lib_dir, norm)
        upsert_chart_export(
            conn,
            pattern_id,
            lib_dir,
            norm,
            symbol_mode=recog.get("symbol_mode") if recog else None,
        )
    detail = get_pattern_detail(pattern_id)
    if not detail:
        raise KeyError(pattern_id)
    return detail


def create_blank_pattern(
    *,
    title: str | None = None,
    width: int = 20,
    height: int = 20,
    craft: str = "cross_stitch",
) -> PatternDetail:
    """Create an empty cross-stitch OXS project in the library."""
    import hashlib
    import uuid

    from knitarr.parsers.oxs import (
        NormalizedPattern,
        PaletteEntry,
        metadata_from_oxs,
        write_normalized,
        write_oxs,
    )
    from knitarr.services.checksum import sha256_file
    from knitarr.services.chart_export import upsert_chart_export, upsert_chart_preview

    width = max(1, min(800, int(width)))
    height = max(1, min(800, int(height)))
    craft = (craft or "cross_stitch").strip() or "cross_stitch"
    blank_id = uuid.uuid4().hex
    name = (title or "").strip() or f"Untitled {blank_id[:8]}"
    if len(name) > 200:
        name = name[:200]

    norm = NormalizedPattern(
        title=name,
        width_stitches=width,
        height_stitches=height,
        fabric_count=14,
        palette=[
            PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF", symbol="100"),
            PaletteEntry(index=1, number="DMC 310", name="Black", color="000000", symbol="33"),
        ],
        full_stitches=[],
        backstitches=[],
        part_stitches=[],
        ornaments=[],
        recognition={"blank_id": blank_id},
    )
    # Unique fingerprint so empty canvases of the same size never collide.
    structure_fp = hashlib.sha256(f"blank|{blank_id}|{width}x{height}".encode()).hexdigest()
    meta = metadata_from_oxs(norm)
    now = _utc_now()

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO patterns (
                external_release_id, title, designer, source, source_url, pattern_url,
                craft, description, license_class, redistribution_allowed, downloaded,
                checksum_sha256, structure_fingerprint, pattern_format,
                width_stitches, height_stitches, stitch_count, color_count, fabric_count,
                floss_brand, date_discovered, date_downloaded, thumbnail_path, normalized_path
            ) VALUES (NULL, ?, NULL, 'user_import', '', NULL, ?, '', ?, 0, 1,
                      NULL, ?, 'oxs', ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)
            """,
            (
                name,
                craft,
                LicenseClass.USER_OWNED.value,
                structure_fp,
                meta.get("width_stitches"),
                meta.get("height_stitches"),
                meta.get("stitch_count"),
                meta.get("color_count"),
                meta.get("fabric_count"),
                now,
                now,
            ),
        )
        pattern_id = int(cur.lastrowid)
        lib_dir = settings.library_dir / str(pattern_id)
        lib_dir.mkdir(parents=True, exist_ok=True)
        oxs_path = lib_dir / "design.oxs"
        npath = lib_dir / "normalized.json"
        write_oxs(oxs_path, norm)
        write_normalized(npath, norm)
        checksum = sha256_file(oxs_path)
        conn.execute(
            """
            UPDATE patterns SET checksum_sha256 = ?, normalized_path = ? WHERE id = ?
            """,
            (checksum, str(npath), pattern_id),
        )
        conn.execute(
            """
            INSERT INTO pattern_files (pattern_id, role, path, filename, mime_type, checksum_sha256, size_bytes)
            VALUES (?, 'original', ?, ?, ?, ?, ?)
            """,
            (pattern_id, str(oxs_path), oxs_path.name, "application/xml", checksum, oxs_path.stat().st_size),
        )
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
        conn.execute(
            """
            INSERT INTO projects (pattern_id, status, progress_json, updated_at)
            VALUES (?, 'not_started', '{}', ?)
            """,
            (pattern_id, now),
        )
        preview = upsert_chart_preview(conn, pattern_id, lib_dir, norm)
        thumb = lib_dir / "thumb.jpg"
        if preview and preview.is_file():
            try:
                shutil.copy2(preview, thumb)
            except OSError:
                pass
            if thumb.is_file():
                conn.execute(
                    "UPDATE patterns SET thumbnail_path = ? WHERE id = ?",
                    (str(thumb), pattern_id),
                )
        upsert_chart_export(conn, pattern_id, lib_dir, norm)

    detail = get_pattern_detail(pattern_id)
    if not detail:
        raise RuntimeError("Blank pattern created but could not be loaded")
    return detail


def pattern_share_files(pattern_id: int) -> list[tuple[str, Path]]:
    """Files to include in a share torrent (originals + useful derived exports)."""
    ensure_chart_export(pattern_id)
    with get_conn() as conn:
        row = conn.execute("SELECT id, title FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        files = conn.execute(
            """
            SELECT path, filename, role FROM pattern_files
            WHERE pattern_id = ?
            ORDER BY id
            """,
            (pattern_id,),
        ).fetchall()
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for f in files:
        path = Path(f["path"]) if f["path"] else None
        name = f["filename"] or (path.name if path else "")
        if not path or not path.is_file() or not name:
            continue
        # Skip huge internal JSON; keep chart files people can open elsewhere.
        if name.lower() == "normalized.json":
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((name, path))
    if not out:
        raise ValueError("No shareable files for this pattern")
    return out


def build_pattern_torrent(pattern_id: int) -> tuple[bytes, str, str, int]:
    """Return (torrent_bytes, filename, info_hash_hex, total_size)."""
    from knitarr.services.torrent import build_torrent_bytes

    with get_conn() as conn:
        row = conn.execute("SELECT title FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        title = (row["title"] or f"pattern-{pattern_id}").strip()
    files = pattern_share_files(pattern_id)
    safe = re.sub(r"[^\w.\- ]+", "", title).strip() or f"pattern-{pattern_id}"
    folder = f"{safe}-{pattern_id}"
    # Single-file torrents use the filename as info.name; multi-file uses a folder name
    # with paths relative to that folder.
    torrent_name = files[0][0] if len(files) == 1 else folder
    payload, info_hash, total = build_torrent_bytes(files, name=torrent_name)
    return payload, f"{safe}.torrent", info_hash, total


def build_pattern_magnet(pattern_id: int) -> dict[str, str | int]:
    from knitarr.services.torrent import magnet_uri

    _payload, _fname, info_hash, total = build_pattern_torrent(pattern_id)
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        title = (row["title"] or f"pattern-{pattern_id}").strip()
    return {
        "magnet": magnet_uri(info_hash, name=title, size=total),
        "info_hash": info_hash,
        "size_bytes": total,
        "title": title,
    }


def build_pattern_zip(pattern_id: int) -> tuple[bytes, str]:
    """Return (zip_bytes, filename) for the same shareable files as torrent/magnet."""
    import io
    import zipfile

    with get_conn() as conn:
        row = conn.execute("SELECT title FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise KeyError(pattern_id)
        title = (row["title"] or f"pattern-{pattern_id}").strip()
    files = pattern_share_files(pattern_id)
    safe = re.sub(r"[^\w.\- ]+", "", title).strip() or f"pattern-{pattern_id}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            zf.write(path, arcname=name)
    return buf.getvalue(), f"{safe}.zip"

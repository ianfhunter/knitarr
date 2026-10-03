"""DB helpers for wanted list and pattern queries."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from knitarr.db import get_conn
from knitarr.indexers.registry import get_indexer
from knitarr.models import (
    ExternalHit,
    LicenseClass,
    PatternDetail,
    PatternFormat,
    PatternSummary,
    ProjectStatus,
    WantedStatus,
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
                json.dumps(hit.metadata),
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


def add_to_wanted(indexer_id: str, external_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM external_releases WHERE indexer_id = ? AND external_id = ?",
            (indexer_id, external_id),
        ).fetchone()
        if not row:
            raise ValueError("Release not found; fetch detail first or search again")
        release_id = int(row["id"])
        existing = conn.execute(
            "SELECT id FROM wanted_items WHERE external_release_id = ? AND status != ?",
            (release_id, WantedStatus.IMPORTED.value),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO wanted_items (external_release_id, status, added_at)
            VALUES (?, ?, ?)
            """,
            (release_id, WantedStatus.WANTED.value, _utc_now()),
        )
        return int(cur.lastrowid)


def _row_to_summary(row) -> PatternSummary:
    thumb = row["thumbnail_path"]
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
        thumbnail_url=f"/api/patterns/{row['id']}/thumbnail" if thumb else None,
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


def list_wanted() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT w.id, w.status, w.added_at, w.error, w.pattern_id,
                   e.title, e.external_id, e.indexer_id, e.source_url, e.license_class
            FROM wanted_items w
            JOIN external_releases e ON e.id = w.external_release_id
            ORDER BY w.added_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


async def ensure_release_from_indexer(indexer_id: str, external_id: str) -> int:
    indexer = get_indexer(indexer_id)
    detail = await indexer.get_pattern(external_id)
    return await upsert_external_release(detail)

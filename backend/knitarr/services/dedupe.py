from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from knitarr.parsers.oxs import NormalizedPattern, structure_fingerprint


def find_checksum_duplicate(conn: sqlite3.Connection, checksum: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM patterns WHERE checksum_sha256 = ? LIMIT 1",
        (checksum,),
    ).fetchone()
    return int(row["id"]) if row else None


def find_structure_duplicate(conn: sqlite3.Connection, fp: str, exclude_id: int | None = None) -> int | None:
    q = "SELECT id FROM patterns WHERE structure_fingerprint = ?"
    params: list = [fp]
    if exclude_id:
        q += " AND id != ?"
        params.append(exclude_id)
    q += " LIMIT 1"
    row = conn.execute(q, params).fetchone()
    return int(row["id"]) if row else None


def suggest_metadata_duplicates(
    conn: sqlite3.Connection,
    pattern_id: int,
    title: str,
    width: int | None,
    height: int | None,
    color_count: int | None,
) -> None:
    if not width or not height:
        return
    rows = conn.execute(
        """
        SELECT id, title FROM patterns
        WHERE id != ? AND width_stitches = ? AND height_stitches = ?
          AND (color_count IS NULL OR color_count BETWEEN ? AND ?)
        LIMIT 10
        """,
        (pattern_id, width, height, (color_count or 0) - 1, (color_count or 0) + 1),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        other_id = int(row["id"])
        score = 0.5
        if title and row["title"] and title.lower()[:20] == str(row["title"]).lower()[:20]:
            score = 0.75
        conn.execute(
            """
            INSERT OR IGNORE INTO dedupe_candidates
            (pattern_id_a, pattern_id_b, score, reason, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (min(pattern_id, other_id), max(pattern_id, other_id), score, "metadata_similarity", now),
        )


def fingerprint_from_normalized(norm: NormalizedPattern) -> str:
    return structure_fingerprint(norm)

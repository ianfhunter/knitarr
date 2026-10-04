"""Craft types and allowed pattern file extensions (user-configurable)."""

from __future__ import annotations

import json
from pathlib import Path

from knitarr.db import get_conn

DEFAULT_CRAFTS: dict[str, dict] = {
    "cross_stitch": {
        "label": "Cross-stitch",
        "extensions": [
            ".oxs",
            ".pdf",
            ".pat",
            ".xsd",
            ".saga",
            ".xps",
            ".oxps",
            ".xsp",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
        ],
    },
    "crochet": {
        "label": "Crochet",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".fcjson", ".md"],
    },
    "knitting": {
        "label": "Knitting",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".knt", ".skp", ".md"],
    },
    "diamond_painting": {
        "label": "Diamond Painting",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "embroidery": {
        "label": "Embroidery",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".dst", ".pes", ".jef", ".exp"],
    },
    "sewing": {
        "label": "Sewing",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "quilting": {
        "label": "Quilting",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "other": {
        "label": "Other",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".zip"],
    },
}

# Stable UI / API ordering.
CRAFT_ORDER = (
    "cross_stitch",
    "crochet",
    "knitting",
    "diamond_painting",
    "embroidery",
    "sewing",
    "quilting",
    "other",
)

_REMOVED_CRAFTS = ("pixel_art",)


def normalize_ext(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


def normalize_extensions(extensions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in extensions:
        e = normalize_ext(raw)
        if e and e not in seen:
            seen.add(e)
            out.append(e)
    return out


def init_craft_files() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS craft_files (
                craft_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                extensions_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        for craft_id, spec in DEFAULT_CRAFTS.items():
            conn.execute(
                """
                INSERT INTO craft_files (craft_id, label, extensions_json, enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(craft_id) DO NOTHING
                """,
                (craft_id, spec["label"], json.dumps(spec["extensions"])),
            )
            # Keep labels in sync with defaults; leave user-edited extensions alone.
            conn.execute(
                "UPDATE craft_files SET label = ? WHERE craft_id = ?",
                (spec["label"], craft_id),
            )
            row = conn.execute(
                "SELECT extensions_json FROM craft_files WHERE craft_id = ?",
                (craft_id,),
            ).fetchone()
            current = json.loads(row["extensions_json"]) if row else []
            extra = [e for e in spec["extensions"] if e in {".saga", ".xps", ".oxps", ".xsp", ".dst", ".pes", ".jef", ".exp"}]
            merged = normalize_extensions(list(current) + extra)
            if merged != normalize_extensions(current):
                conn.execute(
                    "UPDATE craft_files SET extensions_json = ? WHERE craft_id = ?",
                    (json.dumps(merged), craft_id),
                )

        for removed in _REMOVED_CRAFTS:
            conn.execute("DELETE FROM craft_files WHERE craft_id = ?", (removed,))
            try:
                conn.execute("DELETE FROM indexer_craft WHERE craft_id = ?", (removed,))
            except Exception:
                pass
            # Keep old library rows visible under Embroidery rather than orphaning them.
            try:
                conn.execute(
                    "UPDATE patterns SET craft = 'embroidery' WHERE craft = ?",
                    (removed,),
                )
            except Exception:
                pass


def _sort_key(craft_id: str) -> tuple[int, str]:
    try:
        return (CRAFT_ORDER.index(craft_id), craft_id)
    except ValueError:
        return (len(CRAFT_ORDER), craft_id)


def list_crafts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT craft_id, label, extensions_json, enabled FROM craft_files"
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "craft_id": row["craft_id"],
                "label": row["label"],
                "extensions": json.loads(row["extensions_json"]),
                "enabled": bool(row["enabled"]),
            }
        )
    result.sort(key=lambda c: _sort_key(c["craft_id"]))
    return result


def get_craft(craft_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT craft_id, label, extensions_json, enabled FROM craft_files WHERE craft_id = ?",
            (craft_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "craft_id": row["craft_id"],
        "label": row["label"],
        "extensions": json.loads(row["extensions_json"]),
        "enabled": bool(row["enabled"]),
    }


def extensions_for_craft(craft_id: str) -> list[str]:
    craft = get_craft(craft_id)
    if not craft or not craft["enabled"]:
        return normalize_extensions(DEFAULT_CRAFTS.get(craft_id, DEFAULT_CRAFTS["cross_stitch"])["extensions"])
    return normalize_extensions(craft["extensions"])


def update_craft(
    craft_id: str,
    *,
    label: str | None = None,
    extensions: list[str] | None = None,
    enabled: bool | None = None,
) -> dict:
    if craft_id not in DEFAULT_CRAFTS and get_craft(craft_id) is None:
        raise KeyError(craft_id)
    current = get_craft(craft_id) or {
        "craft_id": craft_id,
        "label": craft_id,
        "extensions": [],
        "enabled": True,
    }
    new_label = label if label is not None else current["label"]
    new_ext = normalize_extensions(extensions if extensions is not None else current["extensions"])
    new_enabled = enabled if enabled is not None else current["enabled"]
    if not new_ext:
        raise ValueError("At least one file extension is required")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO craft_files (craft_id, label, extensions_json, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(craft_id) DO UPDATE SET
                label = excluded.label,
                extensions_json = excluded.extensions_json,
                enabled = excluded.enabled
            """,
            (craft_id, new_label, json.dumps(new_ext), 1 if new_enabled else 0),
        )
    return get_craft(craft_id)  # type: ignore[return-value]


def file_matches_craft(filename: str, craft_id: str) -> bool:
    ext = Path(filename).suffix.lower()
    if not ext:
        return False
    return ext in extensions_for_craft(craft_id)


def filter_filenames(filenames: list[str], craft_id: str) -> list[str]:
    allowed = set(extensions_for_craft(craft_id))
    return [n for n in filenames if Path(n).suffix.lower() in allowed]

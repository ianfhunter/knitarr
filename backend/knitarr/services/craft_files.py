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
    "beading": {
        "label": "Beading",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "iron_beading": {
        "label": "Iron Beading",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "embroidery": {
        "label": "Embroidery",
        "extensions": [
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".dst",
            ".pes",
            ".pec",
            ".jef",
            ".exp",
            ".vp3",
            ".xxx",
            ".csq",
            ".sew",
            ".pcs",
            ".10o",
        ],
    },
    "sewing": {
        "label": "Sewing",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "quilting": {
        "label": "Quilting",
        "extensions": [
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".hqf",
            ".hqv",
            ".iqp",
            ".plt",
            ".dst",
            ".exp",
            ".csq",
        ],
    },
    "origami": {
        "label": "Origami",
        "extensions": [".fold", ".json", ".opx", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".webp"],
    },
    "other": {
        "label": "Other",
        "extensions": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".zip"],
    },
}

# Stable UI / API ordering (matches Library nav groups).
CRAFT_ORDER = (
    "embroidery",
    "cross_stitch",
    "knitting",
    "crochet",
    "diamond_painting",
    "beading",
    "iron_beading",
    "sewing",
    "quilting",
    "origami",
    "other",
)

PIXEL_CRAFTS = frozenset({"diamond_painting", "beading", "iron_beading"})
CHART_CRAFTS = frozenset({"cross_stitch", *PIXEL_CRAFTS})
MACHINE_CRAFTS = frozenset({"embroidery", "quilting"})

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
            # Merge newly added default extensions into existing rows (additive).
            if row:
                try:
                    current = set(json.loads(row["extensions_json"] or "[]"))
                except json.JSONDecodeError:
                    current = set()
                merged = normalize_extensions(list(current) + list(spec["extensions"]))
                if set(merged) != current:
                    # Only add missing defaults; don't remove user choices.
                    added = [e for e in spec["extensions"] if e not in current]
                    if added:
                        conn.execute(
                            "UPDATE craft_files SET extensions_json = ? WHERE craft_id = ?",
                            (json.dumps(normalize_extensions(list(current) + added)), craft_id),
                        )
        for craft_id in _REMOVED_CRAFTS:
            conn.execute("DELETE FROM craft_files WHERE craft_id = ?", (craft_id,))


def list_crafts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT craft_id, label, extensions_json, enabled FROM craft_files"
        ).fetchall()
    by_id = {r["craft_id"]: r for r in rows}
    out: list[dict] = []
    for craft_id in CRAFT_ORDER:
        r = by_id.get(craft_id)
        if not r:
            continue
        try:
            exts = json.loads(r["extensions_json"] or "[]")
        except json.JSONDecodeError:
            exts = []
        out.append(
            {
                "craft_id": craft_id,
                "label": r["label"],
                "extensions": normalize_extensions(exts),
                "enabled": bool(r["enabled"]),
            }
        )
    # Any unexpected crafts last
    for craft_id, r in by_id.items():
        if craft_id in CRAFT_ORDER:
            continue
        try:
            exts = json.loads(r["extensions_json"] or "[]")
        except json.JSONDecodeError:
            exts = []
        out.append(
            {
                "craft_id": craft_id,
                "label": r["label"],
                "extensions": normalize_extensions(exts),
                "enabled": bool(r["enabled"]),
            }
        )
    return out


def get_craft(craft_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT craft_id, label, extensions_json, enabled FROM craft_files WHERE craft_id = ?",
            (craft_id,),
        ).fetchone()
    if not row:
        return None
    try:
        exts = json.loads(row["extensions_json"] or "[]")
    except json.JSONDecodeError:
        exts = []
    return {
        "craft_id": row["craft_id"],
        "label": row["label"],
        "extensions": normalize_extensions(exts),
        "enabled": bool(row["enabled"]),
    }


def update_craft(
    craft_id: str,
    *,
    label: str | None = None,
    extensions: list[str] | None = None,
    enabled: bool | None = None,
) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT craft_id FROM craft_files WHERE craft_id = ?", (craft_id,)
        ).fetchone()
        if not row:
            raise KeyError(craft_id)
        fields: list[str] = []
        values: list = []
        if label is not None:
            fields.append("label = ?")
            values.append(label.strip() or craft_id)
        if extensions is not None:
            fields.append("extensions_json = ?")
            values.append(json.dumps(normalize_extensions(extensions)))
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(1 if enabled else 0)
        if fields:
            values.append(craft_id)
            conn.execute(f"UPDATE craft_files SET {', '.join(fields)} WHERE craft_id = ?", values)
    detail = get_craft(craft_id)
    if not detail:
        raise KeyError(craft_id)
    return detail


def extensions_for_craft(craft_id: str) -> list[str]:
    c = get_craft(craft_id)
    if c:
        return c["extensions"]
    return normalize_extensions(DEFAULT_CRAFTS.get(craft_id, DEFAULT_CRAFTS["cross_stitch"])["extensions"])


def default_fabric_count(craft_id: str) -> int:
    if craft_id in PIXEL_CRAFTS:
        return 10
    return 14


def file_matches_craft(filename: str, craft_id: str) -> bool:
    """True if filename's extension is allowed for the craft."""
    name = (filename or "").strip().lower()
    if not name:
        return False
    # Strip query strings from URLs
    name = name.split("?", 1)[0]
    suf = Path(name).suffix.lower()
    if not suf:
        return False
    allowed = set(extensions_for_craft(craft_id))
    return suf in allowed

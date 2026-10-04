"""User supplies preferences (preferred floss brand, etc.)."""

from __future__ import annotations

from knitarr.db import get_conn
from knitarr.services.floss_catalog import (
    DEFAULT_FLOSS_BRAND,
    list_floss_brands,
    normalize_floss_brand,
)


def init_supplies() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS supplies_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                floss_brand TEXT NOT NULL DEFAULT 'dmc'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO supplies_settings (id, floss_brand)
            VALUES (1, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (DEFAULT_FLOSS_BRAND,),
        )


def get_preferred_floss_brand() -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT floss_brand FROM supplies_settings WHERE id = 1").fetchone()
        if not row:
            return DEFAULT_FLOSS_BRAND
        return normalize_floss_brand(row["floss_brand"])


def get_supplies() -> dict:
    brand = get_preferred_floss_brand()
    brands = list_floss_brands()
    return {
        "floss_brand": brand,
        "floss_brands": brands,
    }


def update_supplies(*, floss_brand: str | None = None) -> dict:
    if floss_brand is not None:
        brand = normalize_floss_brand(floss_brand)
        brands = {b["id"]: b for b in list_floss_brands()}
        meta = brands.get(brand)
        if not meta or not meta.get("available"):
            raise ValueError(f"Unknown or unavailable floss brand: {floss_brand}")
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO supplies_settings (id, floss_brand)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET floss_brand = excluded.floss_brand
                """,
                (brand,),
            )
    return get_supplies()

from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timezone

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.indexers.registry import get_indexer
from knitarr.models import WantedStatus
from knitarr.services.import_service import download_urls, import_downloaded_files

log = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def process_one_wanted(wanted_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT w.id, w.status, e.external_id, e.indexer_id, e.id AS release_id
            FROM wanted_items w
            JOIN external_releases e ON e.id = w.external_release_id
            WHERE w.id = ? AND w.status IN ('wanted', 'failed')
            """,
            (wanted_id,),
        ).fetchone()
        if not row:
            return
        job = dict(row)
        conn.execute(
            "UPDATE wanted_items SET status = ?, last_checked_at = ?, error = NULL WHERE id = ?",
            (WantedStatus.DOWNLOADING.value, _utc_now(), wanted_id),
        )

    try:
        indexer = get_indexer(job["indexer_id"])
        detail = await indexer.get_pattern(job["external_id"])
        spec = await indexer.get_download(job["external_id"])
        if not spec:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE wanted_items SET status = ?, error = ?, last_checked_at = ? WHERE id = ?",
                    (WantedStatus.UNAVAILABLE.value, "No downloadable file", _utc_now(), wanted_id),
                )
            return

        urls = spec.all_urls if spec.all_urls else [(spec.url, spec.filename)]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = __import__("pathlib").Path(tmp)
            paths = await download_urls(urls, tmp_path, settings.ia_user_agent)
            with get_conn() as conn:
                pattern_id, dup, msg = import_downloaded_files(
                    conn, detail, paths, int(job["release_id"])
                )
                if dup:
                    conn.execute(
                        "UPDATE wanted_items SET status = ?, pattern_id = ?, error = ?, last_checked_at = ? WHERE id = ?",
                        (WantedStatus.IMPORTED.value, dup, msg, _utc_now(), wanted_id),
                    )
                elif pattern_id:
                    conn.execute(
                        "UPDATE wanted_items SET status = ?, pattern_id = ?, error = NULL, last_checked_at = ? WHERE id = ?",
                        (WantedStatus.IMPORTED.value, pattern_id, _utc_now(), wanted_id),
                    )
                else:
                    conn.execute(
                        "UPDATE wanted_items SET status = ?, error = ?, last_checked_at = ? WHERE id = ?",
                        (WantedStatus.FAILED.value, msg, _utc_now(), wanted_id),
                    )
    except Exception as e:
        log.exception("wanted %s failed", wanted_id)
        with get_conn() as conn:
            conn.execute(
                "UPDATE wanted_items SET status = ?, error = ?, last_checked_at = ? WHERE id = ?",
                (WantedStatus.FAILED.value, str(e)[:500], _utc_now(), wanted_id),
            )


async def process_wanted_queue() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id FROM wanted_items
            WHERE status IN ('wanted', 'failed')
            ORDER BY added_at ASC
            LIMIT 3
            """
        ).fetchall()
    for row in rows:
        await process_one_wanted(int(row["id"]))


async def worker_loop(stop: asyncio.Event) -> None:
    log.info("Wanted worker started (interval=%ss)", settings.worker_interval_sec)
    while not stop.is_set():
        try:
            await process_wanted_queue()
        except Exception:
            log.exception("worker tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_interval_sec)
        except asyncio.TimeoutError:
            pass

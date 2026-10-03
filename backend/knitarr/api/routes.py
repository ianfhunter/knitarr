import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.indexers.registry import get_indexer, list_indexers
from knitarr.models import (
    ImportResult,
    LicenseClass,
    ProjectStatus,
    ProjectUpdate,
    SearchResponse,
    WantedCreate,
)
from knitarr.services import catalog
from knitarr.services.import_service import import_local_file

router = APIRouter(prefix="/api")


@router.get("/indexers")
def api_indexers():
    return [
        {
            "id": idx.id,
            "name": idx.name,
            "capabilities": idx.capabilities.model_dump(),
        }
        for idx in list_indexers()
    ]


@router.get("/search", response_model=SearchResponse)
async def api_search(
    q: str = Query("", min_length=0),
    indexer_id: str = "internet_archive",
    limit: int = Query(30, ge=1, le=50),
):
    try:
        indexer = get_indexer(indexer_id)
    except KeyError:
        raise HTTPException(404, "Indexer not found")
    results = await indexer.search(q, limit=limit)
    return SearchResponse(query=q, indexer_id=indexer_id, results=results)


@router.get("/external/{indexer_id}/{external_id}")
async def api_external_detail(indexer_id: str, external_id: str):
    try:
        indexer = get_indexer(indexer_id)
    except KeyError:
        raise HTTPException(404, "Indexer not found")
    return await indexer.get_pattern(external_id)


@router.post("/wanted")
async def api_add_wanted(body: WantedCreate):
    await catalog.ensure_release_from_indexer(body.indexer_id, body.external_id)
    try:
        wid = catalog.add_to_wanted(body.indexer_id, body.external_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"wanted_id": wid}


@router.get("/wanted")
def api_list_wanted():
    return catalog.list_wanted()


@router.get("/patterns")
def api_list_patterns(
    downloaded: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    return catalog.list_patterns(downloaded_only=downloaded, limit=limit)


@router.get("/patterns/{pattern_id}")
def api_pattern_detail(pattern_id: int):
    detail = catalog.get_pattern_detail(pattern_id)
    if not detail:
        raise HTTPException(404, "Pattern not found")
    return detail


@router.get("/patterns/{pattern_id}/thumbnail")
def api_pattern_thumbnail(pattern_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT thumbnail_path FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
    if not row or not row["thumbnail_path"]:
        raise HTTPException(404, "No thumbnail")
    path = Path(row["thumbnail_path"])
    if not path.is_file():
        raise HTTPException(404, "Thumbnail missing")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/patterns/{pattern_id}/files")
def api_pattern_files(pattern_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, mime_type, role, size_bytes FROM pattern_files WHERE pattern_id = ?",
            (pattern_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/patterns/{pattern_id}/file/{file_id}")
def api_pattern_file(pattern_id: int, file_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT path, mime_type, filename FROM pattern_files WHERE id = ? AND pattern_id = ?",
            (file_id, pattern_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "File not found")
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(404, "File missing on disk")
    return FileResponse(path, media_type=row["mime_type"] or "application/octet-stream", filename=row["filename"])


@router.get("/patterns/{pattern_id}/normalized")
def api_pattern_normalized(pattern_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT normalized_path FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
    if not row or not row["normalized_path"]:
        raise HTTPException(404, "No normalized pattern")
    path = Path(row["normalized_path"])
    if not path.is_file():
        raise HTTPException(404, "Normalized file missing")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@router.get("/patterns/{pattern_id}/project")
def api_get_project(pattern_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status, progress_json, started_at, finished_at, updated_at FROM projects WHERE pattern_id = ?",
            (pattern_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return {
        "pattern_id": pattern_id,
        "status": row["status"],
        "progress_json": json.loads(row["progress_json"] or "{}"),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
    }


@router.patch("/patterns/{pattern_id}/project")
def api_update_project(pattern_id: int, body: ProjectUpdate):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM projects WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        status = body.status.value if body.status else row["status"]
        progress = body.progress_json
        if progress is None:
            progress = json.loads(
                conn.execute(
                    "SELECT progress_json FROM projects WHERE pattern_id = ?", (pattern_id,)
                ).fetchone()["progress_json"]
                or "{}"
            )
        started = conn.execute(
            "SELECT started_at FROM projects WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()["started_at"]
        finished_at = conn.execute(
            "SELECT finished_at FROM projects WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()["finished_at"]
        if status == ProjectStatus.IN_PROGRESS.value and not started:
            started = now
        if status == ProjectStatus.FINISHED.value:
            finished_at = now
        conn.execute(
            """
            UPDATE projects SET status = ?, progress_json = ?, started_at = ?, finished_at = ?, updated_at = ?
            WHERE pattern_id = ?
            """,
            (status, json.dumps(progress), started, finished_at, now, pattern_id),
        )
    return api_get_project(pattern_id)


@router.post("/import/upload", response_model=ImportResult)
async def api_upload(file: UploadFile = File(...)):
    import tempfile

    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    with get_conn() as conn:
        pid, dup, msg = import_local_file(conn, tmp_path, title=Path(file.filename or "").stem)
    tmp_path.unlink(missing_ok=True)
    if dup:
        return ImportResult(pattern_id=None, duplicate_of=dup, message=msg)
    return ImportResult(pattern_id=pid, duplicate_of=None, message=msg)


@router.post("/import/sample-oxs", response_model=ImportResult)
def api_import_sample_oxs():
    sample = settings.samples_dir / "sample.oxs"
    if not sample.is_file():
        raise HTTPException(404, "Sample OXS not bundled")
    with get_conn() as conn:
        pid, dup, msg = import_local_file(
            conn, sample, title="Knitarr Sample (OXS)", license_class=LicenseClass.UNKNOWN
        )
    if dup:
        return ImportResult(pattern_id=None, duplicate_of=dup, message=msg)
    return ImportResult(pattern_id=pid, duplicate_of=None, message=msg)

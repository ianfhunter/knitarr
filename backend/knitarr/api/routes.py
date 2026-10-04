import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from knitarr.config import settings
from knitarr.db import get_conn
from knitarr.indexers.registry import get_indexer, list_indexers
from knitarr.models import (
    BlankPatternRequest,
    ChartSaveRequest,
    ConvertChartRequest,
    CraftFilesUpdate,
    YarnSaveRequest,
    FileRenameRequest,
    RegeneratePackageRequest,
    ImportResult,
    IndexerCraftUpdate,
    LicenseClass,
    ImportFromIndexer,
    PatternUpdate,
    ProjectStatus,
    ProjectUpdate,
    SearchResponse,
    SuppliesUpdate,
)
from knitarr.services import catalog
from knitarr.services.craft_files import get_craft, list_crafts, update_craft
from knitarr.services.indexer_craft import (
    is_indexer_enabled_for_craft,
    list_indexer_craft_matrix,
    set_indexer_craft_enabled,
)
from knitarr.services.search_merge import fair_merge_hits
from knitarr.services.import_service import import_from_indexer, import_local_file
from knitarr.services.supplies import get_preferred_floss_brand, get_supplies, update_supplies

router = APIRouter(prefix="/api")


@router.get("/indexers")
def api_indexers():
    matrix = list_indexer_craft_matrix()
    return [
        {
            "id": idx.id,
            "name": idx.name,
            "capabilities": idx.capabilities.model_dump(),
            "craft_enabled": matrix.get(idx.id, {}),
        }
        for idx in list_indexers()
    ]


@router.put("/indexers/{indexer_id}/craft")
def api_set_indexer_craft(indexer_id: str, body: IndexerCraftUpdate):
    try:
        craft_enabled = set_indexer_craft_enabled(indexer_id, body.craft_id, body.enabled)
    except KeyError:
        raise HTTPException(404, "Indexer or craft not found")
    return {"indexer_id": indexer_id, "craft_enabled": craft_enabled}


@router.get("/about")
async def api_about():
    from knitarr.services.about import about_info

    return await about_info()


@router.get("/craft-files")
def api_list_craft_files():
    return list_crafts()


@router.put("/craft-files/{craft_id}")
def api_update_craft_files(craft_id: str, body: CraftFilesUpdate):
    try:
        return update_craft(
            craft_id,
            label=body.label,
            extensions=body.extensions,
            enabled=body.enabled,
        )
    except KeyError:
        raise HTTPException(404, "Craft not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/supplies")
def api_get_supplies():
    return get_supplies()


@router.put("/supplies")
def api_update_supplies(body: SuppliesUpdate):
    try:
        return update_supplies(floss_brand=body.floss_brand)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/floss/nearest")
def api_nearest_floss(
    hex: str = Query(..., min_length=6, max_length=7),
    brand: str | None = Query(default=None, description="Floss brand id; defaults to Supplies preference"),
):
    from knitarr.services.floss_catalog import nearest_floss, normalize_floss_brand, parse_hex_rgb

    try:
        rgb = parse_hex_rgb(hex)
        brand_id = normalize_floss_brand(brand) if brand else get_preferred_floss_brand()
        number, name, color = nearest_floss(rgb, brand=brand_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "number": number,
        "name": name,
        "color": color,
        "brand": brand_id,
        "rgb": [int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)],
    }


@router.get("/dmc/nearest")
def api_nearest_dmc(hex: str = Query(..., min_length=6, max_length=7)):
    """Back-compat alias — uses preferred Supplies brand (not hard-coded DMC)."""
    return api_nearest_floss(hex=hex, brand=None)


@router.get("/search", response_model=SearchResponse)
async def api_search(
    q: str = Query("", min_length=0),
    indexer_id: str = Query("internet_archive"),
    craft: str = Query("cross_stitch"),
    limit: int = Query(30, ge=1, le=50),
):
    if get_craft(craft) is None:
        raise HTTPException(400, "Unknown craft")
    if indexer_id == "all":
        per_source = max(1, limit)
        sources = [
            idx
            for idx in list_indexers()
            if idx.capabilities.search_enabled
            and idx.capabilities.status.value != "planned"
            and is_indexer_enabled_for_craft(idx.id, craft)
        ]

        async def _one(idx):
            try:
                return await idx.search(q, limit=per_source, craft=craft)
            except Exception:
                return []

        hit_lists = await asyncio.gather(*[_one(idx) for idx in sources])
        merged = fair_merge_hits(list(hit_lists), limit)
        return SearchResponse(query=q, indexer_id="all", craft=craft, results=merged)

    try:
        indexer = get_indexer(indexer_id)
    except KeyError:
        raise HTTPException(404, "Indexer not found")
    if not indexer.capabilities.search_enabled:
        raise HTTPException(400, "This indexer does not support search")
    if not is_indexer_enabled_for_craft(indexer_id, craft):
        raise HTTPException(400, "This indexer is disabled for the selected craft")
    try:
        results = await indexer.search(q, limit=limit, craft=craft)
    except Exception as e:
        raise HTTPException(502, f"Search failed: {e}") from e
    return SearchResponse(query=q, indexer_id=indexer_id, craft=craft, results=results)


@router.get("/external/{indexer_id}/{external_id:path}")
async def api_external_detail(
    indexer_id: str,
    external_id: str,
    craft: str = Query("cross_stitch"),
):
    try:
        indexer = get_indexer(indexer_id)
    except KeyError:
        raise HTTPException(404, "Indexer not found")
    return await indexer.get_pattern(external_id, craft=craft)


@router.get("/patterns")
def api_list_patterns(
    downloaded: bool | None = None,
    craft: str | None = Query(None, description="Craft id, or 'other' for non primary crafts"),
    limit: int = Query(100, ge=1, le=500),
):
    return catalog.list_patterns(downloaded_only=downloaded, craft=craft, limit=limit)


@router.delete("/patterns/{pattern_id}")
def api_delete_pattern(pattern_id: int):
    try:
        catalog.delete_pattern(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"deleted": True, "pattern_id": pattern_id}


@router.get("/patterns/{pattern_id}/pdf-info")
def api_pdf_info(pattern_id: int):
    try:
        return catalog.pdf_info(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/patterns/{pattern_id}/raster-preview")
def api_raster_preview(pattern_id: int, page: int = Query(1, ge=1)):
    try:
        data = catalog.raster_preview_jpeg(pattern_id, pdf_page=page)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, media_type="image/jpeg")


@router.post("/patterns/{pattern_id}/convert-chart")
def api_convert_pattern_chart(pattern_id: int, body: ConvertChartRequest | None = None):
    crop = body.crop if body else None
    pdf_page = body.pdf_page if body else None
    symbol_mode = body.symbol_mode if body else None
    try:
        message = catalog.convert_pattern_to_chart(
            pattern_id, crop=crop, pdf_page=pdf_page, symbol_mode=symbol_mode
        )
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"pattern_id": pattern_id, "message": message}


@router.post("/patterns/{pattern_id}/regenerate-package")
def api_regenerate_package(pattern_id: int, body: RegeneratePackageRequest | None = None):
    symbol_mode = body.symbol_mode if body else None
    try:
        message = catalog.regenerate_pattern_package(pattern_id, symbol_mode=symbol_mode)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"pattern_id": pattern_id, "message": message}


@router.post("/patterns/blank")
def api_create_blank_pattern(body: BlankPatternRequest):
    """Create an empty chart or yarn-craft instruction project."""
    craft = (body.craft or "cross_stitch").strip() or "cross_stitch"
    from knitarr.services.craft_files import CHART_CRAFTS

    if craft not in CHART_CRAFTS and craft not in ("crochet", "knitting"):
        raise HTTPException(
            400,
            "Blank projects are only supported for chart crafts (incl. pixel crafts), crochet, and knitting",
        )
    try:
        detail = catalog.create_blank_pattern(
            title=body.title,
            width=body.width,
            height=body.height,
            craft=craft,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return detail


def _yarn_craft_or_404(pattern_id: int, expected: str):
    from knitarr.services import yarn_pattern as yarn_svc

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, craft FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Pattern not found")
    if row["craft"] != expected:
        raise HTTPException(400, f"This editor is only available for {expected} patterns")
    return row, yarn_svc


@router.get("/patterns/{pattern_id}/embroidery")
def api_get_embroidery(pattern_id: int):
    from knitarr.services import embroidery as emb_svc

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, craft FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Pattern not found")
    if row["craft"] not in ("embroidery", "quilting"):
        raise HTTPException(400, "Embroidery viewer is only for embroidery/quilting patterns")
    try:
        meta = emb_svc.get_or_process(pattern_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    lib = settings.library_dir / str(pattern_id)
    return {
        **meta,
        "preview_png_url": f"/api/patterns/{pattern_id}/embroidery/preview.png"
        if (lib / emb_svc.PREVIEW_PNG).is_file()
        else None,
        "preview_svg_url": f"/api/patterns/{pattern_id}/embroidery/preview.svg"
        if (lib / emb_svc.PREVIEW_SVG).is_file()
        else None,
    }


@router.get("/patterns/{pattern_id}/embroidery/preview.png")
def api_embroidery_preview_png(pattern_id: int):
    from knitarr.services import embroidery as emb_svc

    path = settings.library_dir / str(pattern_id) / emb_svc.PREVIEW_PNG
    if not path.is_file():
        try:
            emb_svc.get_or_process(pattern_id)
        except Exception:
            pass
    if not path.is_file():
        raise HTTPException(404, "No embroidery preview")
    return FileResponse(path, media_type="image/png")


@router.get("/patterns/{pattern_id}/embroidery/preview.svg")
def api_embroidery_preview_svg(pattern_id: int):
    from knitarr.services import embroidery as emb_svc

    path = settings.library_dir / str(pattern_id) / emb_svc.PREVIEW_SVG
    if not path.is_file():
        try:
            emb_svc.get_or_process(pattern_id)
        except Exception:
            pass
    if not path.is_file():
        raise HTTPException(404, "No embroidery SVG preview")
    return FileResponse(path, media_type="image/svg+xml")


@router.post("/patterns/{pattern_id}/embroidery/extract")
def api_embroidery_extract(pattern_id: int):
    from knitarr.services import embroidery as emb_svc

    with get_conn() as conn:
        row = conn.execute("SELECT id, craft FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Pattern not found")
    if row["craft"] not in ("embroidery", "quilting"):
        raise HTTPException(400, "Only embroidery/quilting patterns support machine parse")
    try:
        return emb_svc.process_machine_file(pattern_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/patterns/{pattern_id}/origami")
def api_get_origami(pattern_id: int):
    from knitarr.services import origami as ori_svc

    with get_conn() as conn:
        row = conn.execute("SELECT id, craft FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Pattern not found")
    if row["craft"] != "origami":
        raise HTTPException(400, "Origami viewer is only for origami patterns")
    try:
        meta = ori_svc.get_or_process(pattern_id)
        fold_path = ori_svc.find_fold_file(pattern_id)
        fold = ori_svc.load_fold(fold_path) if fold_path else None
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "meta": meta,
        "fold": fold,
        "preview_svg_url": f"/api/patterns/{pattern_id}/origami/preview.svg",
    }


@router.get("/patterns/{pattern_id}/origami/preview.svg")
def api_origami_preview_svg(pattern_id: int):
    from knitarr.services import origami as ori_svc

    path = settings.library_dir / str(pattern_id) / ori_svc.PREVIEW_SVG
    if not path.is_file():
        try:
            ori_svc.get_or_process(pattern_id)
        except Exception:
            pass
    if not path.is_file():
        raise HTTPException(404, "No origami preview")
    return FileResponse(path, media_type="image/svg+xml")


@router.post("/patterns/{pattern_id}/origami/extract")
def api_origami_extract(pattern_id: int):
    from knitarr.services import origami as ori_svc

    with get_conn() as conn:
        row = conn.execute("SELECT id, craft FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Pattern not found")
    if row["craft"] != "origami":
        raise HTTPException(400, "Only origami patterns support FOLD extract")
    try:
        return ori_svc.process_fold(pattern_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/patterns/{pattern_id}/crochet")
def api_get_crochet(pattern_id: int):
    from knitarr.services import yarn_pattern as yarn_svc

    try:
        return yarn_svc.get_or_extract(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/patterns/{pattern_id}/crochet/extract")
def api_extract_crochet(pattern_id: int):
    from knitarr.services import yarn_pattern as yarn_svc

    try:
        _yarn_craft_or_404(pattern_id, "crochet")
        return yarn_svc.extract_from_pdf(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.put("/patterns/{pattern_id}/crochet")
def api_save_crochet(pattern_id: int, body: YarnSaveRequest):
    row, yarn_svc = _yarn_craft_or_404(pattern_id, "crochet")
    existing = yarn_svc.load_document(pattern_id, "crochet") or yarn_svc.empty_document("crochet")
    supplies = body.supplies.model_dump() if body.supplies is not None else existing.get("supplies")
    dialect = (supplies or {}).get("terminology") or body.dialect or "US"
    doc = {
        **existing,
        "title": body.title or row["title"] or existing.get("title") or "Untitled",
        "dialect": dialect,
        "lines": body.lines,
        "supplies": supplies,
    }
    return yarn_svc.save_document(pattern_id, "crochet", doc)


@router.get("/patterns/{pattern_id}/knitting")
def api_get_knitting(pattern_id: int):
    from knitarr.services import yarn_pattern as yarn_svc

    try:
        return yarn_svc.get_or_extract(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/patterns/{pattern_id}/knitting/extract")
def api_extract_knitting(pattern_id: int):
    from knitarr.services import yarn_pattern as yarn_svc

    try:
        _yarn_craft_or_404(pattern_id, "knitting")
        return yarn_svc.extract_from_pdf(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.put("/patterns/{pattern_id}/knitting")
def api_save_knitting(pattern_id: int, body: YarnSaveRequest):
    row, yarn_svc = _yarn_craft_or_404(pattern_id, "knitting")
    existing = yarn_svc.load_document(pattern_id, "knitting") or yarn_svc.empty_document("knitting")
    supplies = body.supplies.model_dump() if body.supplies is not None else existing.get("supplies")
    dialect = (supplies or {}).get("terminology") or body.dialect or "US"
    doc = {
        **existing,
        "title": body.title or row["title"] or existing.get("title") or "Untitled",
        "dialect": dialect,
        "lines": body.lines,
        "supplies": supplies,
    }
    return yarn_svc.save_document(pattern_id, "knitting", doc)


@router.get("/patterns/{pattern_id}")
def api_pattern_detail(pattern_id: int):
    detail = catalog.get_pattern_detail(pattern_id)
    if not detail:
        raise HTTPException(404, "Pattern not found")
    return detail


@router.get("/patterns/{pattern_id}/torrent")
def api_pattern_torrent(pattern_id: int):
    try:
        payload, filename, _info_hash, _total = catalog.build_pattern_torrent(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(
        content=payload,
        media_type="application/x-bittorrent",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/patterns/{pattern_id}/magnet")
def api_pattern_magnet(pattern_id: int):
    try:
        return catalog.build_pattern_magnet(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/patterns/{pattern_id}/zip")
def api_pattern_zip(pattern_id: int):
    try:
        payload, filename = catalog.build_pattern_zip(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/patterns/{pattern_id}")
def api_update_pattern(pattern_id: int, body: PatternUpdate):
    try:
        return catalog.update_pattern(
            pattern_id,
            title=body.title,
            description=body.description,
            license_class=body.license_class,
            source_url=body.source_url,
        )
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/patterns/{pattern_id}/chart")
def api_save_chart(pattern_id: int, body: ChartSaveRequest):
    try:
        return catalog.save_chart(pattern_id, body)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/patterns/{pattern_id}/thumbnail")
def api_pattern_thumbnail(pattern_id: int):
    from knitarr.main import STATIC_DIR

    try:
        path = catalog.ensure_thumbnail(pattern_id)
    except KeyError:
        raise HTTPException(404, "Pattern not found")
    if path and path.is_file():
        return FileResponse(path, media_type="image/jpeg")
    # Fall back to Knitarr logo so library cards never show a broken image.
    placeholder = STATIC_DIR / "placeholder.svg"
    if placeholder.is_file():
        return FileResponse(placeholder, media_type="image/svg+xml")
    raise HTTPException(404, "No thumbnail")


@router.get("/patterns/{pattern_id}/files")
def api_pattern_files(pattern_id: int):
    catalog.ensure_chart_export(pattern_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, mime_type, role, size_bytes FROM pattern_files WHERE pattern_id = ?",
            (pattern_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/patterns/{pattern_id}/files/{file_id}")
def api_rename_pattern_file(pattern_id: int, file_id: int, body: FileRenameRequest):
    try:
        return catalog.rename_pattern_file(pattern_id, file_id, body.filename)
    except KeyError:
        raise HTTPException(404, "File not found")
    except FileNotFoundError:
        raise HTTPException(404, "File missing on disk")
    except ValueError as e:
        raise HTTPException(400, str(e))


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
    from knitarr.parsers.oxs import normalized_from_dict

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, "Normalized file unreadable") from exc
    # Expand implied TR/BR companions (Ursa often stores only the left half of a peak).
    return JSONResponse(normalized_from_dict(raw).to_dict())


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


async def _import_upload_file(
    file: UploadFile,
    *,
    craft: str,
) -> ImportResult:
    import tempfile

    if get_craft(craft) is None:
        raise HTTPException(400, "Unknown craft")
    filename = file.filename or "upload"
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        if not content:
            tmp_path = Path(tmp.name)
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(400, "Empty file")
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        with get_conn() as conn:
            pid, dup, msg = import_local_file(
                conn,
                tmp_path,
                title=Path(filename).stem,
                craft=craft,
            )
    finally:
        tmp_path.unlink(missing_ok=True)
    if dup:
        return ImportResult(pattern_id=None, duplicate_of=dup, message=msg)
    return ImportResult(pattern_id=pid, duplicate_of=None, message=msg)


@router.post("/import/upload", response_model=ImportResult)
async def api_upload(
    file: UploadFile = File(...),
    craft: str = Form("cross_stitch"),
):
    return await _import_upload_file(file, craft=craft)


@router.post("/import/upload-many")
async def api_upload_many(
    files: list[UploadFile] = File(...),
    craft: str = Form("cross_stitch"),
):
    if not files:
        raise HTTPException(400, "No files provided")
    results: list[ImportResult] = []
    for file in files:
        results.append(await _import_upload_file(file, craft=craft))
    return results


@router.post("/import/from-indexer", response_model=ImportResult)
async def api_import_from_indexer(body: ImportFromIndexer):
    if get_craft(body.craft) is None:
        raise HTTPException(400, "Unknown craft")
    try:
        get_indexer(body.indexer_id)
    except KeyError:
        raise HTTPException(404, "Indexer not found")
    try:
        return await import_from_indexer(body.indexer_id, body.external_id, craft=body.craft)
    except KeyError:
        raise HTTPException(404, "Pattern not found on source")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Import failed: {e}") from e


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

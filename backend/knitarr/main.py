import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from knitarr.api.routes import router as api_router
from knitarr.db import init_db
from knitarr.indexers.registry import bootstrap_indexers, shutdown_indexers
from knitarr.services import catalog
from knitarr.services.craft_files import init_craft_files
from knitarr.services.indexer_craft import init_indexer_craft

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("knitarr")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_craft_files()
    bootstrap_indexers()
    init_indexer_craft()
    catalog.seed_indexers()
    log.info("Knitarr started")
    yield
    await shutdown_indexers()


app = FastAPI(title="Knitarr", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "Knitarr API — build frontend into knitarr/static"}


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

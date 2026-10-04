import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from knitarr import __version__
from knitarr.api.routes import router as api_router
from knitarr.db import init_db
from knitarr.indexers.registry import bootstrap_indexers, shutdown_indexers
from knitarr.services import catalog
from knitarr.services.craft_files import init_craft_files
from knitarr.services.indexer_craft import init_indexer_craft
from knitarr.services.supplies import init_supplies

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("knitarr")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_craft_files()
    init_supplies()
    bootstrap_indexers()
    init_indexer_craft()
    catalog.seed_indexers()
    log.info("Knitarr %s started", __version__)
    yield
    await shutdown_indexers()


app = FastAPI(title="Knitarr", version=__version__, lifespan=lifespan)
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


def _static_file(name: str, media_type: str | None = None) -> FileResponse:
    path = STATIC_DIR / name
    if not path.is_file():
        from fastapi import HTTPException

        raise HTTPException(404, f"{name} not found")
    return FileResponse(path, media_type=media_type)


@app.get("/favicon.svg")
def favicon_svg():
    return _static_file("favicon.svg", "image/svg+xml")


@app.get("/favicon.ico")
def favicon_ico():
    return _static_file("favicon.ico", "image/x-icon")


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    return _static_file("apple-touch-icon.png", "image/png")


@app.get("/favicon-32.png")
def favicon_32():
    return _static_file("favicon-32.png", "image/png")


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

"""Raster (image/PDF) → cross-stitch grid → OXS (PIL + preferred floss palette)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from PIL import Image

from knitarr.config import settings
from knitarr.models import CropRect
from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, write_oxs, write_normalized
from knitarr.services.chart_recognize import RecognitionResult, recognize_chart_image
from knitarr.services.floss_catalog import (
    looks_like_dmc_label,
    looks_like_floss_label,
    nearest_dmc,
    nearest_floss,
    parse_hex_rgb,
)

log = logging.getLogger(__name__)

_BACKGROUND_MIN = 248
DOCUMENT_SUFFIXES = {".pdf", ".xps", ".oxps"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
RASTER_SUFFIXES = IMAGE_SUFFIXES | DOCUMENT_SUFFIXES
_DOC_FILETYPES = {".pdf": "pdf", ".xps": "xps", ".oxps": "oxps"}


def looks_like_xps(path: Path) -> bool:
    try:
        if path.read_bytes()[:2] != b"PK":
            return False
        with zipfile.ZipFile(path) as zf:
            names = " ".join(zf.namelist()).lower()
        return any(token in names for token in ("fixeddocument", "fixedpage", ".fpage", ".fdseq", ".oxps"))
    except Exception:
        return False


def document_filetype(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _DOC_FILETYPES:
        return _DOC_FILETYPES[suffix]
    if suffix == ".xsp" and looks_like_xps(path):
        return "xps"
    return None


def _apply_crop(im: Image.Image, crop: CropRect | None) -> Image.Image:
    if crop is None:
        return im
    c = crop.clamped()
    w, h = im.size
    left = int(c.x * w)
    top = int(c.y * h)
    right = int(min(w, (c.x + c.w) * w))
    bottom = int(min(h, (c.y + c.h) * h))
    if right - left < 2 or bottom - top < 2:
        raise ValueError("Crop region is too small")
    return im.crop((left, top, right, bottom))


def pdf_page_count(path: Path) -> int:
    filetype = document_filetype(path)
    if not filetype:
        return 1
    import fitz

    with fitz.open(path, filetype=filetype) as doc:
        return doc.page_count


def raster_preview_image(path: Path, *, max_side: int = 1200, pdf_page: int = 0) -> Image.Image:
    im = _load_raster(path, pdf_page=pdf_page)
    w, h = im.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    return im


def _load_raster(path: Path, *, pdf_page: int = 0, pdf_zoom: float = 2.0) -> Image.Image:
    filetype = document_filetype(path)
    if filetype:
        import fitz

        with fitz.open(path, filetype=filetype) as doc:
            if pdf_page < 0 or pdf_page >= doc.page_count:
                raise ValueError(f"Page {pdf_page + 1} out of range (1–{doc.page_count})")
            page = doc[pdf_page]
            pix = page.get_pixmap(matrix=fitz.Matrix(pdf_zoom, pdf_zoom), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(path) as im:
        return im.convert("RGB")


def _preferred_brand() -> str:
    try:
        from knitarr.services.supplies import get_preferred_floss_brand

        return get_preferred_floss_brand()
    except Exception:
        return "dmc"


def _nearest_preferred(rgb: tuple[int, int, int]) -> tuple[str, str, str]:
    return nearest_floss(rgb, brand=_preferred_brand())


def convert_raster_to_normalized(
    path: Path,
    *,
    title: str,
    max_width: int | None = None,
    max_colors: int | None = None,
    crop: CropRect | None = None,
    pdf_page: int = 0,
) -> NormalizedPattern:
    max_width = max_width or settings.convert_max_width
    max_colors = max_colors or settings.convert_max_colors
    im = _apply_crop(_load_raster(path, pdf_page=pdf_page, pdf_zoom=3.0), crop)
    result = recognize_chart_image(im, max_width=max_width, max_colors=max_colors)
    return _normalized_from_recognition(result, title=title)


def _normalized_from_recognition(result: RecognitionResult, *, title: str) -> NormalizedPattern:
    palette_map: dict[tuple[str, str, str], int] = {}
    norm = NormalizedPattern(
        title=title,
        width_stitches=result.width,
        height_stitches=result.height,
        fabric_count=14,
        palette=[
            PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF", symbol="32", stitch_count=0)
        ],
        recognition={
            "mode": result.mode,
            "clusters": result.clusters,
            "low_confidence": result.low_confidence,
        },
    )

    def pal_index(rgb: tuple[int, int, int]) -> int:
        key = _nearest_preferred(rgb)
        if key not in palette_map:
            idx = len(norm.palette)
            number, name, color = key
            norm.palette.append(
                PaletteEntry(
                    index=idx,
                    number=number,
                    name=name,
                    color=color,
                    symbol=str(33 + (idx % 90)),
                    stitch_count=0,
                )
            )
            palette_map[key] = idx
        return palette_map[key]

    for st in result.stitches:
        if min(st.rgb) >= _BACKGROUND_MIN:
            continue
        idx = pal_index(st.rgb)
        stitch = {"x": st.x, "y": st.y, "palindex": idx, "kind": st.kind}
        if result.mode == "symbols":
            stitch["confidence"] = round(st.confidence, 3)
            if st.cluster_id >= 0:
                stitch["symbol_id"] = st.cluster_id
        norm.full_stitches.append(stitch)
        for pe in norm.palette:
            if pe.index == idx:
                pe.stitch_count += 1
                break

    if not norm.full_stitches:
        raise ValueError("No stitch pixels detected (image may be blank or all white)")

    norm.chart_source = result.source
    if result.annotated is not None:
        norm.annotated_image = result.annotated
    return norm


def write_conversion_artifacts(pattern_dir: Path, norm: NormalizedPattern) -> tuple[Path, Path]:
    oxs_path = pattern_dir / "converted.oxs"
    json_path = pattern_dir / "normalized.json"
    write_oxs(oxs_path, norm)
    write_normalized(json_path, norm)
    annotated = getattr(norm, "annotated_image", None)
    if annotated is not None:
        preview = pattern_dir / "recognition.png"
        annotated.save(preview, format="PNG")
    return oxs_path, json_path

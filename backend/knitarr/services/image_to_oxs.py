"""Raster (image/PDF) → cross-stitch grid → OXS (PIL + DMC palette; tarraz tested but failed on small charts)."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from PIL import Image

from knitarr.config import settings
from knitarr.models import CropRect
from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, write_oxs, write_normalized
from knitarr.services.chart_recognize import RecognitionResult, recognize_chart_image

log = logging.getLogger(__name__)

_DMC_PATH = Path(__file__).resolve().parent.parent / "data" / "dmc_floss.json"
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


@lru_cache(maxsize=1)
def _dmc_colors() -> list[dict]:
    raw = json.loads(_DMC_PATH.read_text(encoding="utf-8"))
    return raw


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


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def _lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _lin(rgb[0]), _lin(rgb[1]), _lin(rgb[2])
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def _f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)

    fx, fy, fz = _f(x / xn), _f(y / yn), _f(z / zn)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


@lru_cache(maxsize=1)
def _dmc_labs() -> list[tuple[dict, tuple[float, float, float]]]:
    return [(entry, _srgb_to_lab(tuple(entry["rgb"]))) for entry in _dmc_colors()]


def parse_hex_rgb(color: str) -> tuple[int, int, int]:
    raw = color.strip().lstrip("#")
    if len(raw) != 6:
        raise ValueError("Colour must be 6-digit hex")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def nearest_dmc(rgb: tuple[int, int, int]) -> tuple[str, str, str]:
    return _nearest_dmc(rgb)


def looks_like_dmc_label(text: str | None) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if re.match(r"^colour\s+\d+$", raw, re.I):
        return False
    return bool(re.match(r"^(DMC\s+)?(\d{1,4}|Blanc|Ecru|B5200|White|Ecru)$", raw, re.I)) or raw.upper().startswith(
        "DMC "
    )


def _nearest_dmc(rgb: tuple[int, int, int]) -> tuple[str, str, str]:
    sl, sa, sb = _srgb_to_lab(rgb)
    best = _dmc_colors()[0]
    best_dist = 1e18
    for entry, (ll, aa, bb) in _dmc_labs():
        # Hue/chroma outweigh lightness so gold does not snap to olive-black.
        dist = (sl - ll) ** 2 + 1.6 * (sa - aa) ** 2 + 1.6 * (sb - bb) ** 2
        if dist < best_dist:
            best_dist = dist
            best = entry
    r, g, b = best["rgb"]
    return f"DMC {best['number']}", best["name"], f"{r:02X}{g:02X}{b:02X}"


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
        key = _nearest_dmc(rgb)
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

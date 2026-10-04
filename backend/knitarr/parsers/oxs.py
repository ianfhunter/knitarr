"""Parse Open Cross Stitch (.oxs) XML into normalized JSON."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PaletteEntry:
    index: int
    number: str
    name: str
    color: str
    symbol: str | None = None
    stitch_count: int = 0


@dataclass
class NormalizedPattern:
    format: str = "oxs"
    title: str | None = None
    width_stitches: int = 0
    height_stitches: int = 0
    fabric_count: int | None = None
    palette: list[PaletteEntry] = field(default_factory=list)
    full_stitches: list[dict[str, Any]] = field(default_factory=list)
    backstitches: list[dict[str, Any]] = field(default_factory=list)
    recognition: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("recognition"):
            d.pop("recognition", None)
        return d

    def color_count(self) -> int:
        used = {s["palindex"] for s in self.full_stitches if s.get("palindex", 0) > 0}
        used |= {s["palindex"] for s in self.backstitches if s.get("palindex", 0) > 0}
        return len(used)


def _int_attr(el: ET.Element, name: str, default: int = 0) -> int:
    val = el.get(name)
    if val is None:
        return default
    try:
        return int(float(val))
    except ValueError:
        return default


def _parse_dmc(number: str) -> tuple[str | None, str | None]:
    m = re.match(r"^\s*(DMC|Anchor|Madeira)\s+(\S+)", number, re.I)
    if m:
        return m.group(1).upper(), m.group(2)
    if number.lower() == "cloth":
        return None, None
    return None, number.strip()


def parse_oxs(path: Path | str) -> NormalizedPattern:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(text)
    norm = NormalizedPattern()

    props = root.find("properties")
    if props is not None:
        norm.title = props.get("title") or props.get("name")
        norm.width_stitches = _int_attr(props, "width") or _int_attr(props, "chartwidth")
        norm.height_stitches = _int_attr(props, "height") or _int_attr(props, "chartheight")
        fc = props.get("stitchesperinch") or props.get("fabriccount")
        if fc:
            try:
                norm.fabric_count = int(float(fc))
            except ValueError:
                pass

    palette_el = root.find("palette")
    if palette_el is not None:
        for item in palette_el.findall("palette_item"):
            idx = _int_attr(item, "index")
            number = item.get("number") or ""
            norm.palette.append(
                PaletteEntry(
                    index=idx,
                    number=number,
                    name=item.get("name") or "",
                    color=item.get("color") or "FFFFFF",
                    symbol=item.get("symbol"),
                )
            )

    full = root.find("fullstitches")
    if full is not None:
        max_x = max_y = 0
        for stitch in full.findall("stitch"):
            x = _int_attr(stitch, "x")
            y = _int_attr(stitch, "y")
            pal = _int_attr(stitch, "palindex")
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            norm.full_stitches.append({"x": x, "y": y, "palindex": pal})
            for pe in norm.palette:
                if pe.index == pal:
                    pe.stitch_count += 1
        if not norm.width_stitches:
            norm.width_stitches = max_x + 1
        if not norm.height_stitches:
            norm.height_stitches = max_y + 1

    back = root.find("backstitches")
    if back is not None:
        for bs in back.findall("backstitch"):
            norm.backstitches.append(
                {
                    "x1": _int_attr(bs, "x1"),
                    "y1": _int_attr(bs, "y1"),
                    "x2": _int_attr(bs, "x2"),
                    "y2": _int_attr(bs, "y2"),
                    "palindex": _int_attr(bs, "palindex"),
                }
            )

    return norm


def write_normalized(path: Path, norm: NormalizedPattern) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(norm.to_dict(), indent=2), encoding="utf-8")


def write_oxs(path: Path, norm: NormalizedPattern) -> None:
    """Write Ursa-style OXS XML from normalized pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    title = norm.title or "Converted pattern"
    w = norm.width_stitches or 1
    h = norm.height_stitches or 1
    spi = norm.fabric_count or 14
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<chart>",
        f'  <properties title="{_xml_escape(title)}" width="{w}" height="{h}" stitchesperinch="{spi}"/>',
        "  <palette>",
    ]
    for pe in sorted(norm.palette, key=lambda p: p.index):
        sym = pe.symbol or str(33 + (pe.index % 90))
        lines.append(
            f'    <palette_item index="{pe.index}" number="{_xml_escape(pe.number)}" '
            f'name="{_xml_escape(pe.name)}" color="{pe.color.lstrip("#")}" strands="2" symbol="{_xml_escape(sym)}"/>'
        )
    lines.append("  </palette>")
    lines.append("  <fullstitches>")
    for s in norm.full_stitches:
        lines.append(f'    <stitch x="{s["x"]}" y="{s["y"]}" palindex="{s["palindex"]}"/>')
    lines.append("  </fullstitches>")
    lines.append("  <backstitches>")
    for b in norm.backstitches:
        lines.append(
            f'    <backstitch x1="{int(b["x1"])}" y1="{int(b["y1"])}" '
            f'x2="{int(b["x2"])}" y2="{int(b["y2"])}" palindex="{int(b["palindex"])}"/>'
        )
    lines.append("  </backstitches>")
    lines.append("  <ornaments_inc_knots_and_beads/>")
    lines.append("</chart>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def structure_fingerprint(norm: NormalizedPattern) -> str:
    import hashlib

    stitches = sorted(
        (s["x"], s["y"], s["palindex"]) for s in norm.full_stitches
    )
    backs = sorted(
        (int(b["x1"]), int(b["y1"]), int(b["x2"]), int(b["y2"]), int(b["palindex"]))
        for b in norm.backstitches
    )
    codes = sorted(p.number for p in norm.palette if p.index > 0)
    payload = f"{norm.width_stitches}x{norm.height_stitches}|{stitches}|{backs}|{codes}"
    return hashlib.sha256(payload.encode()).hexdigest()


def metadata_from_oxs(norm: NormalizedPattern) -> dict[str, Any]:
    brands = set()
    for p in norm.palette:
        brand, _ = _parse_dmc(p.number)
        if brand:
            brands.add(brand)
    return {
        "width_stitches": norm.width_stitches,
        "height_stitches": norm.height_stitches,
        "stitch_count": len(norm.full_stitches),
        "color_count": norm.color_count(),
        "fabric_count": norm.fabric_count,
        "floss_brand": next(iter(brands), None),
        "title": norm.title,
    }

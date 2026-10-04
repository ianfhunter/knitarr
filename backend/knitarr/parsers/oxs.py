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
    strands: int = 2


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
    part_stitches: list[dict[str, Any]] = field(default_factory=list)
    ornaments: list[dict[str, Any]] = field(default_factory=list)
    recognition: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d.get("recognition"):
            d.pop("recognition", None)
        return d

    def color_count(self) -> int:
        used = {s["palindex"] for s in self.full_stitches if s.get("palindex", 0) > 0}
        used |= {s["palindex"] for s in self.backstitches if s.get("palindex", 0) > 0}
        for s in self.part_stitches:
            if int(s.get("palindex1") or 0) > 0:
                used.add(int(s["palindex1"]))
            if int(s.get("palindex2") or 0) > 0:
                used.add(int(s["palindex2"]))
        used |= {int(o["palindex"]) for o in self.ornaments if int(o.get("palindex") or 0) > 0}
        return len(used)


def _palette_entry_from_dict(raw: dict[str, Any]) -> PaletteEntry:
    strands_raw = raw.get("strands", 2)
    try:
        strands = int(strands_raw)
    except (TypeError, ValueError):
        strands = 2
    strands = max(1, min(6, strands))
    return PaletteEntry(
        index=int(raw.get("index") or 0),
        number=str(raw.get("number") or ""),
        name=str(raw.get("name") or ""),
        color=str(raw.get("color") or "FFFFFF"),
        symbol=raw.get("symbol"),
        stitch_count=int(raw.get("stitch_count") or 0),
        strands=strands,
    )


def normalized_from_dict(raw: dict[str, Any]) -> NormalizedPattern:
    pal = [_palette_entry_from_dict(p) for p in (raw.get("palette") or [])]
    norm = NormalizedPattern(
        format=raw.get("format") or "oxs",
        title=raw.get("title"),
        width_stitches=int(raw.get("width_stitches") or 0),
        height_stitches=int(raw.get("height_stitches") or 0),
        fabric_count=raw.get("fabric_count"),
        palette=pal,
        full_stitches=list(raw.get("full_stitches") or []),
        backstitches=list(raw.get("backstitches") or []),
        part_stitches=list(raw.get("part_stitches") or []),
        ornaments=list(raw.get("ornaments") or []),
        recognition=raw.get("recognition"),
    )
    expand_implied_part_halves(norm)
    return norm


def _backstitch_endpoints(norm: NormalizedPattern) -> set[tuple[float, float, float, float]]:
    """Undirected segment set with integer-ish coords for exact cell diagonals."""
    segs: set[tuple[float, float, float, float]] = set()
    for b in norm.backstitches:
        x1 = float(b.get("x1") or 0)
        y1 = float(b.get("y1") or 0)
        x2 = float(b.get("x2") or 0)
        y2 = float(b.get("y2") or 0)
        segs.add((x1, y1, x2, y2))
        segs.add((x2, y2, x1, y1))
    return segs


def _has_segment(
    segs: set[tuple[float, float, float, float]],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    eps: float = 0.01,
) -> bool:
    if (x1, y1, x2, y2) in segs or (x2, y2, x1, y1) in segs:
        return True
    for a, b, c, d in segs:
        if (
            abs(a - x1) <= eps
            and abs(b - y1) <= eps
            and abs(c - x2) <= eps
            and abs(d - y2) <= eps
        ):
            return True
    return False


def _half_to_fields(half: str, colour: int) -> tuple[int, int, int]:
    """Return (palindex1, palindex2, direction) for a single coloured half."""
    if half == "bl":
        return colour, 0, 1
    if half == "tr":
        return 0, colour, 1
    if half == "tl":
        return colour, 0, 2
    if half == "br":
        return 0, colour, 2
    raise ValueError(half)


def _fields_to_halves(p1: int, p2: int, direction: int) -> dict[str, int]:
    out: dict[str, int] = {}
    if direction == 1:
        if p1 > 0:
            out["bl"] = p1
        if p2 > 0:
            out["tr"] = p2
    elif direction == 2:
        if p1 > 0:
            out["tl"] = p1
        if p2 > 0:
            out["br"] = p2
    return out


def _edge_color(
    fulls: dict[tuple[int, int], int],
    parts_at: dict[tuple[int, int], list[dict[str, Any]]],
    x: int,
    y: int,
    edge: str,
) -> int:
    """Colour along one edge of cell (x,y), from a full stitch or covering part half."""
    if (x, y) in fulls:
        return fulls[(x, y)]
    halves: dict[str, int] = {}
    for ps in parts_at.get((x, y), []):
        halves.update(
            _fields_to_halves(
                int(ps.get("palindex1") or 0),
                int(ps.get("palindex2") or 0),
                int(ps.get("direction") or 1),
            )
        )
    touch = {
        "left": ("tl", "bl"),
        "right": ("tr", "br"),
        "top": ("tl", "tr"),
        "bottom": ("bl", "br"),
    }.get(edge, ())
    colors = {halves[h] for h in touch if halves.get(h)}
    if len(colors) == 1:
        return next(iter(colors))
    return 0


def _neighbor_color_for_half(
    fulls: dict[tuple[int, int], int],
    parts_at: dict[tuple[int, int], list[dict[str, Any]]],
    x: int,
    y: int,
    half: str,
) -> int:
    """If an orthogonal neighbour stitch touches this half, return its colour."""
    checks: list[tuple[int, int, str]] = []
    if half == "bl":
        checks = [(x - 1, y, "right"), (x, y + 1, "top")]
    elif half == "tr":
        checks = [(x + 1, y, "left"), (x, y - 1, "bottom")]
    elif half == "tl":
        checks = [(x - 1, y, "right"), (x, y - 1, "bottom")]
    elif half == "br":
        checks = [(x + 1, y, "left"), (x, y + 1, "top")]
    colors = []
    for nx, ny, edge in checks:
        c = _edge_color(fulls, parts_at, nx, ny, edge)
        if c > 0:
            colors.append(c)
    if not colors:
        return 0
    # Prefer a unanimous colour; otherwise the first neighbour wins.
    if len(set(colors)) == 1:
        return colors[0]
    return colors[0]


def _ensure_part_half(
    norm: NormalizedPattern,
    parts_at: dict[tuple[int, int], list[dict[str, Any]]],
    fulls: dict[tuple[int, int], int],
    x: int,
    y: int,
    half: str,
    colour: int,
) -> bool:
    """Ensure cell (x,y) shows ``half`` in ``colour``. Returns True if modified."""
    if colour <= 0 or (x, y) in fulls:
        return False
    existing = parts_at.get((x, y), [])
    have: dict[str, int] = {}
    for ps in existing:
        have.update(
            _fields_to_halves(
                int(ps.get("palindex1") or 0),
                int(ps.get("palindex2") or 0),
                int(ps.get("direction") or 1),
            )
        )
    if have.get(half) == colour:
        return False
    if half in have and have[half] != colour:
        return False

    p1, p2, direction = _half_to_fields(half, colour)
    # Merge into an existing partstitch on the same diagonal when possible.
    for ps in existing:
        d = int(ps.get("direction") or 1)
        if d != direction:
            continue
        cur1 = int(ps.get("palindex1") or 0)
        cur2 = int(ps.get("palindex2") or 0)
        if p1 and cur1 and cur1 != p1:
            continue
        if p2 and cur2 and cur2 != p2:
            continue
        if p1 and not cur1:
            ps["palindex1"] = p1
            _bump_palette_count(norm.palette, colour)
            return True
        if p2 and not cur2:
            ps["palindex2"] = p2
            _bump_palette_count(norm.palette, colour)
            return True
        return False

    # Same cell already has the other diagonal — append a second partstitch entry.
    entry: dict[str, Any] = {
        "x": x,
        "y": y,
        "palindex1": p1,
        "palindex2": p2,
        "direction": direction,
    }
    norm.part_stitches.append(entry)
    parts_at.setdefault((x, y), []).append(entry)
    _bump_palette_count(norm.palette, colour)
    return True


def expand_implied_part_halves(norm: NormalizedPattern) -> int:
    """Materialise TR/BR (and other) halves that Ursa omits from partstitches.

    Two sources, iterated to a fixed point (new companions can unlock further peaks):
    1. Peak companions — left-only part + diagonal backstitch through the empty neighbour.
    2. Backstitch-clipped cells — unit diagonal through an empty cell next to a full/part stitch
       (MacStitch fills the triangle on the stitch side even when no partstitch is stored).
    """
    if not norm.backstitches:
        return 0

    fulls = {
        (int(s["x"]), int(s["y"])): int(s["palindex"])
        for s in norm.full_stitches
        if int(s.get("palindex") or 0) > 0
    }
    parts_at: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for ps in norm.part_stitches:
        parts_at.setdefault((int(ps["x"]), int(ps["y"])), []).append(ps)

    added = 0
    segs = _backstitch_endpoints(norm)

    def _peak_pass() -> int:
        n = 0
        for ps in list(norm.part_stitches):
            x = int(ps.get("x") or 0)
            y = int(ps.get("y") or 0)
            p1 = int(ps.get("palindex1") or 0)
            p2 = int(ps.get("palindex2") or 0)
            direction = int(ps.get("direction") or 1)
            if direction not in (1, 2):
                continue
            if p1 > 0 and p2 <= 0 and direction == 1 and _has_segment(segs, x - 1, y + 1, x, y):
                if _ensure_part_half(norm, parts_at, fulls, x - 1, y, "br", p1):
                    n += 1
            if p1 > 0 and p2 <= 0 and direction == 2 and _has_segment(segs, x - 1, y, x, y + 1):
                if _ensure_part_half(norm, parts_at, fulls, x - 1, y, "tr", p1):
                    n += 1
            if p2 > 0 and p1 <= 0 and direction == 2 and _has_segment(segs, x, y + 1, x + 1, y):
                if _ensure_part_half(norm, parts_at, fulls, x + 1, y, "bl", p2):
                    n += 1
            if p2 > 0 and p1 <= 0 and direction == 1 and _has_segment(segs, x, y, x + 1, y + 1):
                if _ensure_part_half(norm, parts_at, fulls, x + 1, y, "tl", p2):
                    n += 1
        return n

    def _neighbor_pass() -> int:
        n = 0
        seen_diag: set[tuple[int, int, str]] = set()
        for b in norm.backstitches:
            x1 = float(b.get("x1") or 0)
            y1 = float(b.get("y1") or 0)
            x2 = float(b.get("x2") or 0)
            y2 = float(b.get("y2") or 0)
            dx, dy = x2 - x1, y2 - y1
            if abs(abs(dx) - 1) > 0.01 or abs(abs(dy) - 1) > 0.01:
                continue
            cx = int(min(x1, x2))
            cy = int(min(y1, y2))
            kind = "backslash" if dx * dy > 0 else "slash"
            key = (cx, cy, kind)
            if key in seen_diag:
                continue
            seen_diag.add(key)
            if (cx, cy) in fulls:
                continue
            # Existing colours on this cell — avoid inventing a second colour on the
            # opposite half (MacStitch leaves that exterior triangle empty).
            have: dict[str, int] = {}
            for ps in parts_at.get((cx, cy), []):
                have.update(
                    _fields_to_halves(
                        int(ps.get("palindex1") or 0),
                        int(ps.get("palindex2") or 0),
                        int(ps.get("direction") or 1),
                    )
                )
            existing_colours = {c for c in have.values() if c > 0}
            halves = ("bl", "tr") if kind == "backslash" else ("tl", "br")
            for half in halves:
                if half in have:
                    continue
                colour = _neighbor_color_for_half(fulls, parts_at, cx, cy, half)
                if not colour:
                    continue
                if existing_colours and colour not in existing_colours:
                    continue
                if _ensure_part_half(norm, parts_at, fulls, cx, cy, half, colour):
                    n += 1
                    have[half] = colour
                    existing_colours.add(colour)
        return n

    # Alternate passes until stable — newly materialised halves unlock further peaks.
    for _ in range(16):
        wave = _peak_pass() + _neighbor_pass()
        if wave == 0:
            break
        added += wave

    return added


def _int_attr(el: ET.Element, name: str, default: int = 0) -> int:
    val = el.get(name)
    if val is None:
        return default
    try:
        return int(float(val))
    except ValueError:
        return default


def _float_attr(el: ET.Element, name: str, default: float = 0.0) -> float:
    val = el.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _parse_dmc(number: str) -> tuple[str | None, str | None]:
    m = re.match(
        r"^\s*(DMC|Anchor|Madeira|Cosmo|Sullivans|CXC|J&P\s*Coats|JP\s*Coats)\s+(\S+)",
        number,
        re.I,
    )
    if m:
        brand = re.sub(r"\s+", " ", m.group(1)).strip().upper()
        if brand in {"JP COATS", "J&P COATS"}:
            brand = "J&P COATS"
        return brand, m.group(2)
    if number.lower() == "cloth":
        return None, None
    return None, number.strip()


def _bump_palette_count(palette: list[PaletteEntry], pal: int, n: int = 1) -> None:
    if pal <= 0:
        return
    for pe in palette:
        if pe.index == pal:
            pe.stitch_count += n
            return


def parse_oxs(path: Path | str) -> NormalizedPattern:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(text)
    norm = NormalizedPattern()

    props = root.find("properties")
    if props is not None:
        norm.title = props.get("title") or props.get("charttitle") or props.get("name")
        if isinstance(norm.title, str):
            norm.title = norm.title.strip() or None
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
            strands = _int_attr(item, "strands", 2) or 2
            strands = max(1, min(6, strands))
            norm.palette.append(
                PaletteEntry(
                    index=idx,
                    number=number,
                    name=item.get("name") or "",
                    color=item.get("color") or "FFFFFF",
                    symbol=item.get("symbol"),
                    strands=strands,
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
            _bump_palette_count(norm.palette, pal)
        if not norm.width_stitches:
            norm.width_stitches = max_x + 1
        if not norm.height_stitches:
            norm.height_stitches = max_y + 1

    parts = root.find("partstitches")
    if parts is not None:
        for ps in parts.findall("partstitch"):
            x = _int_attr(ps, "x")
            y = _int_attr(ps, "y")
            p1 = _int_attr(ps, "palindex1")
            p2 = _int_attr(ps, "palindex2")
            direction = _int_attr(ps, "direction", 1) or 1
            if direction not in (1, 2, 3, 4):
                direction = 1
            if p1 <= 0 and p2 <= 0:
                continue
            entry: dict[str, Any] = {
                "x": x,
                "y": y,
                "palindex1": p1,
                "palindex2": p2,
                "direction": direction,
            }
            major = ps.get("major")
            if major is not None and str(major).strip() not in ("", "0"):
                try:
                    entry["major"] = int(float(major))
                except ValueError:
                    pass
            norm.part_stitches.append(entry)
            _bump_palette_count(norm.palette, p1)
            _bump_palette_count(norm.palette, p2)

    back = root.find("backstitches")
    if back is not None:
        for bs in back.findall("backstitch"):
            norm.backstitches.append(
                {
                    "x1": _float_attr(bs, "x1"),
                    "y1": _float_attr(bs, "y1"),
                    "x2": _float_attr(bs, "x2"),
                    "y2": _float_attr(bs, "y2"),
                    "palindex": _int_attr(bs, "palindex"),
                }
            )
            _bump_palette_count(norm.palette, _int_attr(bs, "palindex"))

    orns = root.find("ornaments_inc_knots_and_beads")
    if orns is not None:
        for obj in orns.findall("object"):
            otype = (obj.get("objecttype") or "").strip() or "knot"
            pal = _int_attr(obj, "palindex")
            x = _float_attr(obj, "x1", _float_attr(obj, "x"))
            y = _float_attr(obj, "y1", _float_attr(obj, "y"))
            entry = {"x": x, "y": y, "palindex": pal, "objecttype": otype}
            direction = obj.get("direction")
            if direction is not None and str(direction).strip() != "":
                try:
                    entry["direction"] = int(float(direction))
                except ValueError:
                    pass
            norm.ornaments.append(entry)
            _bump_palette_count(norm.palette, pal)

    expand_implied_part_halves(norm)
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
        strands = max(1, min(6, int(pe.strands or 2)))
        lines.append(
            f'    <palette_item index="{pe.index}" number="{_xml_escape(pe.number)}" '
            f'name="{_xml_escape(pe.name)}" color="{pe.color.lstrip("#")}" strands="{strands}" '
            f'symbol="{_xml_escape(sym)}"/>'
        )
    lines.append("  </palette>")
    lines.append("  <fullstitches>")
    for s in norm.full_stitches:
        lines.append(f'    <stitch x="{s["x"]}" y="{s["y"]}" palindex="{s["palindex"]}"/>')
    lines.append("  </fullstitches>")
    lines.append("  <partstitches>")
    for s in norm.part_stitches:
        major = s.get("major")
        major_attr = f' major="{int(major)}"' if major not in (None, 0, "0") else ""
        lines.append(
            f'    <partstitch x="{int(s["x"])}" y="{int(s["y"])}" '
            f'palindex1="{int(s.get("palindex1") or 0)}" palindex2="{int(s.get("palindex2") or 0)}" '
            f'direction="{int(s.get("direction") or 1)}"{major_attr}/>'
        )
    lines.append("  </partstitches>")
    lines.append("  <backstitches>")
    for b in norm.backstitches:
        lines.append(
            f'    <backstitch x1="{_fmt_num(b["x1"])}" y1="{_fmt_num(b["y1"])}" '
            f'x2="{_fmt_num(b["x2"])}" y2="{_fmt_num(b["y2"])}" palindex="{int(b["palindex"])}"/>'
        )
    lines.append("  </backstitches>")
    lines.append("  <ornaments_inc_knots_and_beads>")
    for o in norm.ornaments:
        otype = _xml_escape(str(o.get("objecttype") or "knot"))
        extra = ""
        if o.get("direction") is not None:
            extra = f' direction="{int(o["direction"])}"'
        lines.append(
            f'    <object x1="{_fmt_num(o["x"])}" y1="{_fmt_num(o["y"])}" '
            f'palindex="{int(o.get("palindex") or 0)}" objecttype="{otype}"{extra}/>'
        )
    lines.append("  </ornaments_inc_knots_and_beads>")
    lines.append("</chart>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt_num(val: Any) -> str:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "0"
    if f.is_integer():
        return str(int(f))
    return f"{f:.6g}"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def structure_fingerprint(norm: NormalizedPattern) -> str:
    import hashlib

    stitches = sorted((s["x"], s["y"], s["palindex"]) for s in norm.full_stitches)
    backs = sorted(
        (
            float(b["x1"]),
            float(b["y1"]),
            float(b["x2"]),
            float(b["y2"]),
            int(b["palindex"]),
        )
        for b in norm.backstitches
    )
    parts = sorted(
        (
            int(s["x"]),
            int(s["y"]),
            int(s.get("palindex1") or 0),
            int(s.get("palindex2") or 0),
            int(s.get("direction") or 1),
        )
        for s in norm.part_stitches
    )
    orns = sorted(
        (
            round(float(o["x"]), 4),
            round(float(o["y"]), 4),
            int(o.get("palindex") or 0),
            str(o.get("objecttype") or ""),
        )
        for o in norm.ornaments
    )
    codes = sorted(p.number for p in norm.palette if p.index > 0)
    payload = f"{norm.width_stitches}x{norm.height_stitches}|{stitches}|{backs}|{parts}|{orns}|{codes}"
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
        "stitch_count": len(norm.full_stitches) + len(norm.part_stitches),
        "color_count": norm.color_count(),
        "fabric_count": norm.fabric_count,
        "floss_brand": next(iter(brands), None),
        "title": norm.title,
    }

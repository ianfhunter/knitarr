"""Parse Cross Stitch Saga (.saga) when the archive contains readable chart data."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from knitarr.parsers.oxs import NormalizedPattern, parse_oxs

_XML_HINTS = (b"<?xml", b"<chart", b"<fullstitches", b"<palette")


def parse_saga(path: Path | str, *, title: str | None = None) -> NormalizedPattern:
    src = Path(path)
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            candidates = sorted(
                names,
                key=lambda n: (
                    0 if n.lower().endswith(".oxs") else 1 if n.lower().endswith(".xml") else 2,
                    n.lower(),
                ),
            )
            last_err: Exception | None = None
            for name in candidates:
                raw = zf.read(name)
                xml = _as_chart_xml(raw)
                if xml is None:
                    continue
                try:
                    norm = _parse_chart_xml(xml)
                    if title:
                        norm.title = title
                    elif not norm.title:
                        norm.title = src.stem
                    return norm
                except Exception as e:
                    last_err = e
            if any(n.lower().endswith(".xpub") for n in names):
                raise ValueError(
                    "This .saga file is encrypted (Cross Stitch Saga designer format) "
                    "and cannot be converted to OXS"
                )
            if last_err:
                raise ValueError(f"Could not parse chart data inside this .saga file: {last_err}") from last_err
            raise ValueError("No readable stitch chart inside this .saga file")

    raw = src.read_bytes()
    xml = _as_chart_xml(raw)
    if xml is None:
        raise ValueError("This .saga file is not a readable stitch chart")
    norm = _parse_chart_xml(xml)
    if title:
        norm.title = title
    return norm


def _as_chart_xml(raw: bytes) -> bytes | None:
    stripped = raw.lstrip()
    if stripped.startswith(_XML_HINTS):
        return stripped
    try:
        dec = base64.b64decode(raw + b"===", validate=False)
    except Exception:
        return None
    dec = dec.lstrip()
    if dec.startswith(_XML_HINTS):
        return dec
    return None


def _parse_chart_xml(xml: bytes) -> NormalizedPattern:
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(suffix=".oxs", delete=True) as tmp:
        tmp.write(xml)
        tmp.flush()
        return parse_oxs(tmp.name)

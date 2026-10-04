"""Characterize Cross Stitch Saga .saga containers without decrypting payloads."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path
from typing import Any


def characterize_saga(path: Path | str) -> dict[str, Any]:
    src = Path(path)
    data = src.read_bytes()
    report: dict[str, Any] = {
        "path": str(src),
        "size": len(data),
        "is_zip": data[:2] == b"PK",
        "members": [],
        "common_prefixes": [],
        "readable_chart_xml": False,
        "notes": [],
    }
    if not zipfile.is_zipfile(src):
        report["notes"].append("Not a ZIP archive")
        return report

    decoded: dict[str, bytes] = {}
    with zipfile.ZipFile(src) as zf:
        report["zip_comment"] = zf.comment.decode("utf-8", errors="replace")
        for info in zf.infolist():
            raw = zf.read(info.filename)
            member: dict[str, Any] = {
                "name": info.filename,
                "compress_type": info.compress_type,
                "flag_bits": info.flag_bits,
                "crc": info.CRC,
                "compress_size": info.compress_size,
                "file_size": info.file_size,
                "date_time": info.date_time,
            }
            if info.filename.lower().endswith(".ttf"):
                member["kind"] = "truetype_font"
                member["ttf_magic"] = raw[:4].hex()
            elif info.filename.lower().endswith(".xpub"):
                member["kind"] = "xpub"
                member.update(_xpub_fields(raw))
                if member.get("base64") and not member.get("starts_with_xml"):
                    decoded[info.filename] = base64.b64decode(raw + b"=" * (-len(raw) % 4), validate=False)
                if member.get("starts_with_xml"):
                    report["readable_chart_xml"] = True
            elif raw.lstrip().startswith((b"<?xml", b"<chart", b"<fullstitches")):
                member["kind"] = "chart_xml"
                report["readable_chart_xml"] = True
            else:
                member["kind"] = "other"
            report["members"].append(member)

    names = list(decoded)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            n = _lcp(decoded[a], decoded[b])
            report["common_prefixes"].append({"a": a, "b": b, "bytes": n})

    kinds = {m["kind"] for m in report["members"]}
    if "xpub" in kinds and not report["readable_chart_xml"]:
        report["notes"].append(
            "Designer-style pack: ZIP of a symbol font plus Base64 .xpub members. "
            "No public specification; inner bytes after Base64 are not XML."
        )
    if report["readable_chart_xml"]:
        report["notes"].append("Archive contains readable chart XML/OXS and can be imported.")
    return report


def _xpub_fields(raw: bytes) -> dict[str, Any]:
    padded = raw + b"=" * (-len(raw) % 4)
    try:
        dec = base64.b64decode(padded, validate=False)
    except Exception as e:
        return {"base64": False, "error": str(e)}
    return {
        "base64": True,
        "base64_len": len(raw),
        "base64_mod4": len(raw) % 4,
        "decoded_len": len(dec),
        "decoded_mod8": len(dec) % 8,
        "decoded_mod16": len(dec) % 16,
        "decoded_head_hex": dec[:32].hex(),
        "decoded_tail_hex": dec[-16:].hex(),
        "pkcs7_like": _pkcs7_like(dec),
        "starts_with_xml": dec.lstrip().startswith((b"<?xml", b"<chart")),
    }


def _pkcs7_like(data: bytes) -> bool:
    if not data:
        return False
    pad = data[-1]
    return 1 <= pad <= 16 and len(data) >= pad and data[-pad:] == bytes([pad]) * pad


def _lcp(a: bytes, b: bytes) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n

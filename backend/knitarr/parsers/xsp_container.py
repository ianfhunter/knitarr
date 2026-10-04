"""Characterize XSPro Platinum .xsp containers without decrypting payloads."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path
from typing import Any

XSPPLAT_MAGIC = b"XSPPLAT\x00"
# Custom local header:
#  0:8   magic XSPPLAT\0
#  8:10  ZIP method (observed 8 = deflate)
# 10:14  DOS time/date
# 14:18  CRC-32
# 18:22  compressed size
# 22:26  uncompressed size
# 26:30  name length (uint32le; ZIP local headers use uint16)
# 30:    name
# then compressed payload, then standard ZIP central directory + EOCD.


def characterize_xsp(path: Path | str) -> dict[str, Any]:
    src = Path(path)
    data = src.read_bytes()
    report: dict[str, Any] = {
        "path": str(src),
        "size": len(data),
        "magic": data[:8],
        "is_xspplat": data.startswith(XSPPLAT_MAGIC),
        "notes": [],
    }
    if not data.startswith(XSPPLAT_MAGIC):
        report["notes"].append("Missing XSPPLAT magic")
        return report

    method, dos_dt, crc, csize, usize, namelen = struct.unpack_from("<HIIII I", data, 8)
    name = data[30 : 30 + namelen]
    payload_off = 30 + namelen
    payload = data[payload_off : payload_off + csize]
    report.update(
        {
            "method": method,
            "method_name": {0: "store", 8: "deflate"}.get(method, f"unknown({method})"),
            "dos_datetime": dos_dt,
            "crc32": crc,
            "compressed_size": csize,
            "uncompressed_size": usize,
            "name_length": namelen,
            "member_name": name.decode("ascii", errors="replace"),
            "payload_offset": payload_off,
            "payload_len": len(payload),
            "central_directory_offset": payload_off + csize,
        }
    )

    eocd = data.rfind(b"PK\x05\x06")
    report["eocd_offset"] = eocd
    zip_info: dict[str, Any] = {}
    if eocd >= 0:
        disk, start, n_disk, n, cd_size, cd_off, clen = struct.unpack_from("<HHHHIIH", data, eocd + 4)
        zip_info = {
            "entries": n,
            "cd_size": cd_size,
            "cd_offset": cd_off,
            "comment_len": clen,
        }
        if cd_off + 10 <= len(data):
            flag = struct.unpack_from("<H", data, cd_off + 8)[0]
            zip_info["central_flag_bits"] = flag
            zip_info["traditional_zip_encryption_bit"] = bool(flag & 0x1)
            zip_info["flag_bit2"] = bool(flag & 0x4)
            zip_info["data_descriptor_bit"] = bool(flag & 0x8)
            zip_info["aes_extra_field_present"] = b"\x01\x99" in data[cd_off : cd_off + cd_size]
    report["zip"] = zip_info

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        info = zf.infolist()[0] if zf.infolist() else None
        report["zipfile_namelist"] = zf.namelist()
        if info:
            report["zipfile_encrypted"] = bool(info.flag_bits & 0x1)
            report["zipfile_flag_bits"] = info.flag_bits
            report["zipfile_header_offset"] = info.header_offset
    except Exception as e:
        report["zipfile_error"] = f"{type(e).__name__}: {e}"

    report["notes"].append(
        "XSPPLAT is a ZIP whose local file header magic is replaced with XSPPLAT\\0; "
        "the central directory still names adesignfile.xsu. "
        "The encryption bit is set in the ZIP flags; there is no public layout for the inner .xsu."
    )
    return report

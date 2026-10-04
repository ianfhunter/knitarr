"""Minimal BitTorrent v1 .torrent + magnet helpers (no external deps)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote


def bencode(obj: Any) -> bytes:
    if isinstance(obj, int):
        return f"i{obj}e".encode("ascii")
    if isinstance(obj, bytes):
        return f"{len(obj)}:".encode("ascii") + obj
    if isinstance(obj, str):
        raw = obj.encode("utf-8")
        return f"{len(raw)}:".encode("ascii") + raw
    if isinstance(obj, list):
        return b"l" + b"".join(bencode(x) for x in obj) + b"e"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0] if isinstance(kv[0], bytes) else str(kv[0]).encode())
        out = bytearray(b"d")
        for key, value in items:
            k = key if isinstance(key, bytes) else str(key).encode("utf-8")
            out.extend(bencode(k))
            out.extend(bencode(value))
        out.extend(b"e")
        return bytes(out)
    raise TypeError(f"Cannot bencode {type(obj)!r}")


def _piece_hashes(paths: list[Path], piece_length: int = 256 * 1024) -> bytes:
    """Hash the concatenated file stream into fixed-size pieces (BEP 3)."""
    digests = bytearray()
    h = hashlib.sha1()
    filled = 0
    for path in paths:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(piece_length - filled)
                if not chunk:
                    break
                h.update(chunk)
                filled += len(chunk)
                if filled == piece_length:
                    digests.extend(h.digest())
                    h = hashlib.sha1()
                    filled = 0
    if filled:
        digests.extend(h.digest())
    return bytes(digests)


def build_torrent_bytes(
    files: list[tuple[str, Path]],
    *,
    name: str,
    piece_length: int = 256 * 1024,
    announce: str = "udp://tracker.opentrackr.org:1337/announce",
) -> tuple[bytes, str, int]:
    """Return (torrent_bytes, info_hash_hex, total_size).

    ``files`` is an ordered list of (relative_path_inside_torrent, absolute_path).
    """
    if not files:
        raise ValueError("No files to share")
    paths = [p for _, p in files]
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(str(p))
    total = sum(p.stat().st_size for p in paths)
    pieces = _piece_hashes(paths, piece_length)
    info: dict[str, Any] = {
        "name": name,
        "piece length": piece_length,
        "pieces": pieces,
    }
    if len(files) == 1:
        info["length"] = total
    else:
        info["files"] = [
            {"length": path.stat().st_size, "path": rel.replace("\\", "/").split("/")}
            for rel, path in files
        ]
    torrent = {
        "announce": announce,
        "info": info,
        "creation date": __import__("time").time().__trunc__(),
        "created by": "Knitarr",
        "encoding": "UTF-8",
    }
    # Encode info dict alone for the info-hash.
    info_bytes = bencode(info)
    info_hash = hashlib.sha1(info_bytes).hexdigest()
    return bencode(torrent), info_hash, total


def magnet_uri(info_hash_hex: str, *, name: str, size: int | None = None) -> str:
    parts = [f"magnet:?xt=urn:btih:{info_hash_hex}", f"dn={quote(name)}"]
    if size is not None and size >= 0:
        parts.append(f"xl={int(size)}")
    # Public trackers help peers find each other for small personal shares.
    for tr in (
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
    ):
        parts.append(f"tr={quote(tr)}")
    return "&".join(parts)

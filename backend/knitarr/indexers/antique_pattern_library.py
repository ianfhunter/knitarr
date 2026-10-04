"""Antique Pattern Library — public-domain vintage cross-stitch scans."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

BASE = "https://www.antiquepatternlibrary.org"
CATALOG_URL = f"{BASE}/html/warm/xstitch.htm"
_CACHE_TTL = 6 * 3600

_TR_RE = re.compile(r'<tr class="(?:odd|even)">(.*?)</tr>', re.IGNORECASE | re.DOTALL)
_NAME_RE = re.compile(r'<a name="([^"]+)"', re.IGNORECASE)
_PDF_RE = re.compile(r'href="([^"]*pub/PDF/[^"]+\.pdf)"', re.IGNORECASE)
_THUMB_RE = re.compile(r'src="([^"]*pub/Thumbnails/[^"]+)"', re.IGNORECASE)
_P_RE = re.compile(r'<P class="([^"]+)">\s*(.*?)</P>', re.IGNORECASE | re.DOTALL)


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _pclass(block: str, name: str) -> str:
    for cls, body in _P_RE.findall(block):
        if cls.lower() == name.lower():
            return _clean(body)
    return ""


def parse_catalog(html: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _TR_RE.findall(html):
        name_m = _NAME_RE.search(block)
        code = _pclass(block, "code_") or (name_m.group(1) if name_m else "")
        code = code.strip()
        title = _pclass(block, "title")
        if not code or not title or code in seen:
            continue
        seen.add(code)
        pdfs = [urljoin(CATALOG_URL, href) for href in _PDF_RE.findall(block)]
        thumbs = [urljoin(CATALOG_URL, src) for src in _THUMB_RE.findall(block)]
        entries.append(
            {
                "code": code,
                "title": title.rstrip(","),
                "author": _pclass(block, "author"),
                "description": _pclass(block, "descr"),
                "pdfs": pdfs,
                "thumbnail": thumbs[0] if thumbs else None,
            }
        )
    return entries


def _matches(entry: dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    hay = " ".join(
        filter(
            None,
            (entry.get("title"), entry.get("author"), entry.get("description"), entry.get("code")),
        )
    ).lower()
    return all(tok in hay for tok in q.split())


class AntiquePatternLibraryIndexer:
    id = "antique_pattern_library"
    name = "Antique Pattern Library"

    capabilities = IndexerCapabilities(
        source="Antique Pattern Library",
        access_method="scrape",
        authentication="none",
        automated_access_policy="Public catalog page and PDF scans; polite fetch, cached.",
        license_default=LicenseClass.PUBLIC_DOMAIN,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url=CATALOG_URL,
        description="Public-domain vintage cross-stitch books and charts from antiquepatternlibrary.org.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._catalog: list[dict[str, Any]] | None = None
        self._catalog_at = 0.0

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={"User-Agent": settings.ia_user_agent},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _load_catalog(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._catalog is not None and now - self._catalog_at < _CACHE_TTL:
            return self._catalog
        client = await self._client_get()
        async with self._lock:
            if self._catalog is not None and time.monotonic() - self._catalog_at < _CACHE_TTL:
                return self._catalog
            resp = await client.get(CATALOG_URL)
            resp.raise_for_status()
            html = resp.content.decode("latin-1", errors="replace")
            self._catalog = parse_catalog(html)
            self._catalog_at = time.monotonic()
            log.info("APL catalog: %s entries", len(self._catalog))
        return self._catalog

    def _by_code(self, catalog: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
        code = code.strip()
        for entry in catalog:
            if entry["code"] == code:
                return entry
        return None

    def _hit(self, entry: dict[str, Any], craft: str) -> ExternalHit:
        pdfs = entry.get("pdfs") or []
        return ExternalHit(
            indexer_id=self.id,
            external_id=entry["code"],
            title=entry["title"],
            designer=entry.get("author") or None,
            description=entry.get("description") or None,
            source_url=f"{CATALOG_URL}#{entry['code']}",
            pattern_url=pdfs[0] if pdfs else f"{CATALOG_URL}#{entry['code']}",
            craft=craft,
            license_class=LicenseClass.PUBLIC_DOMAIN,
            redistribution_allowed=True,
            thumbnail_url=entry.get("thumbnail"),
            metadata={"code": entry["code"], "pdf_count": len(pdfs)},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        catalog = await self._load_catalog()
        hits: list[ExternalHit] = []
        for entry in catalog:
            if not _matches(entry, query):
                continue
            if not entry.get("pdfs"):
                continue
            hits.append(self._hit(entry, craft))
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        entry = self._by_code(await self._load_catalog(), external_id)
        if not entry:
            raise KeyError(external_id)
        hit = self._hit(entry, craft)
        pdfs = entry.get("pdfs") or []
        names = [u.rsplit("/", 1)[-1] for u in pdfs]
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(pdfs),
            suggested_filename=names[0] if names else None,
            all_files=names,
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        entry = self._by_code(await self._load_catalog(), external_id)
        if not entry:
            raise KeyError(external_id)
        return entry

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        entry = self._by_code(await self._load_catalog(), external_id)
        if not entry or not entry.get("pdfs"):
            return None
        pairs = [(u, u.rsplit("/", 1)[-1]) for u in entry["pdfs"]]
        return DownloadSpec(url=pairs[0][0], filename=pairs[0][1], all_urls=pairs)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass
from knitarr.services.craft_files import file_matches_craft

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.si.edu/openaccess/api/v1.0/search"
DETAIL_BASE = "https://www.si.edu/object"

_CRAFT_QUERY = {
    "cross_stitch": "cross stitch OR embroidery OR needlework",
    "crochet": "crochet",
    "knitting": "knitting",
    "pixel_art": "textile OR embroidery OR cross stitch",
}


def _filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = Path(path).name.split("?")[0]
    return name if name else fallback


def _media_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    content = row.get("content") or {}
    dnr = content.get("descriptiveNonRepeating") or {}
    om = dnr.get("online_media") or {}
    for media in om.get("media") or []:
        ids_id = media.get("idsId")
        if ids_id:
            urls.append(f"https://ids.si.edu/ids/iiif/{ids_id}/full/full/0/default.jpg")
            continue
        raw = media.get("content") or media.get("thumbnail")
        if isinstance(raw, str) and raw.startswith("http"):
            urls.append(raw)
    return urls


class SmithsonianIndexer:
    id = "smithsonian"
    name = "Smithsonian Open Access"

    capabilities = IndexerCapabilities(
        source="Smithsonian",
        access_method="api",
        authentication="api_key",
        automated_access_policy="Smithsonian Open Access API (free key at api.data.gov); set KNITARR_SI_API_KEY.",
        license_default=LicenseClass.CC0,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://www.si.edu/openaccess",
        description="Historical embroidery, textiles, and pattern books from Smithsonian collections.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={"User-Agent": settings.ia_user_agent},
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _api_key(self) -> str:
        key = (settings.si_api_key or "").strip()
        if not key:
            raise RuntimeError("KNITARR_SI_API_KEY is not set")
        return key

    def _search_query(self, query: str, craft: str) -> str:
        craft_term = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
        q = query.strip()
        return f"{craft_term} {q}".strip()

    def _hit_from_row(self, row: dict[str, Any], *, craft: str) -> ExternalHit | None:
        ext_id = row.get("id") or row.get("url")
        if not ext_id:
            return None
        urls = _media_urls(row)
        if not urls:
            return None
        fname = _filename_from_url(urls[0], f"{ext_id}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        title = row.get("title") or str(ext_id)
        guid = row.get("guid") or f"{DETAIL_BASE}/{quote(str(ext_id), safe='')}"
        return ExternalHit(
            indexer_id=self.id,
            external_id=str(ext_id),
            title=str(title),
            source_url=guid if guid.startswith("http") else DETAIL_BASE,
            pattern_url=guid if guid.startswith("http") else DETAIL_BASE,
            craft=craft,
            license_class=LicenseClass.CC0,
            redistribution_allowed=False,
            thumbnail_url=urls[0],
            metadata={"unitCode": row.get("unitCode"), "type": row.get("type")},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        client = await self._client_get()
        params = {
            "api_key": self._api_key(),
            "q": self._search_query(query, craft),
            "start": 0,
            "rows": min(max(limit, 1), 100),
            "sort": "relevancy",
        }
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        rows = (data.get("response") or {}).get("rows") or []
        hits: list[ExternalHit] = []
        for row in rows:
            hit = self._hit_from_row(row, craft=craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_row(self, external_id: str) -> dict[str, Any]:
        client = await self._client_get()
        params = {
            "api_key": self._api_key(),
            "q": external_id,
            "start": 0,
            "rows": 5,
        }
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        for row in (data.get("response") or {}).get("rows") or []:
            if str(row.get("id")) == external_id or str(row.get("url")) == external_id:
                return row
        raise KeyError(external_id)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        row = await self._fetch_row(external_id)
        hit = self._hit_from_row(row, craft=craft)
        if not hit:
            raise KeyError(external_id)
        urls = _media_urls(row)
        fname = _filename_from_url(urls[0], f"{external_id}.jpg") if urls else None
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(urls),
            suggested_filename=fname,
            all_files=[_filename_from_url(u, f"file{i}.jpg") for i, u in enumerate(urls[:10])],
        )

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_row(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        row = await self._fetch_row(external_id)
        urls = _media_urls(row)
        if not urls:
            return None
        fname = _filename_from_url(urls[0], f"{external_id}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        if len(urls) > 1:
            pairs = [(u, _filename_from_url(u, f"page{i}.jpg")) for i, u in enumerate(urls)]
            return DownloadSpec(url=pairs[0][0], filename=pairs[0][1], all_urls=pairs)
        return DownloadSpec(url=urls[0], filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass
from knitarr.services.craft_files import file_matches_craft

log = logging.getLogger(__name__)

API = "https://pixabay.com/api/"

_CRAFT_QUERY = {
    "pixel_art": "pixel art",
    "cross_stitch": "pixel art cross stitch",
    "crochet": "pixel art",
    "knitting": "pixel art",
}


def _filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = Path(path).name.split("?")[0]
    return name if name else fallback


class PixabayIndexer:
    id = "pixabay"
    name = "Pixabay"

    capabilities = IndexerCapabilities(
        source="Pixabay",
        access_method="api",
        authentication="api_key",
        automated_access_policy="Pixabay API; set KNITARR_PIXABAY_API_KEY (free at pixabay.com/api/docs).",
        license_default=LicenseClass.CREATIVE_COMMONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://pixabay.com",
        description="Royalty-free pixel art and illustrations (Pixabay license — no redistribution as stock).",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={"User-Agent": settings.ia_user_agent},
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _api_key(self) -> str:
        key = (settings.pixabay_api_key or "").strip()
        if not key:
            raise RuntimeError("KNITARR_PIXABAY_API_KEY is not set")
        return key

    def _search_q(self, query: str, craft: str) -> str:
        q = query.strip()
        base = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["pixel_art"])
        return f"{q} {base}".strip() if q else base

    def _hit_from_hit(self, item: dict[str, Any], *, craft: str) -> ExternalHit | None:
        ext_id = str(item.get("id") or "")
        page = item.get("pageURL") or ""
        url = item.get("largeImageURL") or item.get("webformatURL") or ""
        if not ext_id or not url:
            return None
        fname = _filename_from_url(url, f"pixabay-{ext_id}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        tags = item.get("tags") or ""
        return ExternalHit(
            indexer_id=self.id,
            external_id=ext_id,
            title=tags.split(",")[0].strip() if tags else f"Pixabay {ext_id}",
            description=tags[:500] if tags else None,
            source_url=page or url,
            pattern_url=page or url,
            craft=craft,
            license_class=LicenseClass.CREATIVE_COMMONS,
            redistribution_allowed=False,
            thumbnail_url=item.get("previewURL") or url,
            metadata={"tags": tags, "user": item.get("user"), "image_url": url},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        client = await self._client_get()
        params = {
            "key": self._api_key(),
            "q": self._search_q(query, craft),
            "image_type": "all",
            "per_page": min(max(limit, 3), 50),
            "safesearch": "true",
        }
        resp = await client.get(API, params=params)
        resp.raise_for_status()
        data = resp.json()
        hits: list[ExternalHit] = []
        for item in data.get("hits") or []:
            hit = self._hit_from_hit(item, craft=craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_by_id(self, external_id: str) -> dict[str, Any]:
        client = await self._client_get()
        resp = await client.get(API, params={"key": self._api_key(), "id": external_id})
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
        if not hits:
            raise KeyError(external_id)
        return hits[0]

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        item = await self._fetch_by_id(external_id)
        hit = self._hit_from_hit(item, craft=craft)
        if not hit:
            raise KeyError(external_id)
        url = hit.metadata.get("image_url") or ""
        fname = _filename_from_url(url, f"pixabay-{external_id}.jpg")
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(url),
            suggested_filename=fname,
            all_files=[fname] if url else [],
        )

    async def get_metadata(self, external_id: str) -> dict:
        return {"id": external_id}

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        try:
            detail = await self.get_pattern(external_id, craft=craft)
        except KeyError:
            return None
        url = detail.metadata.get("image_url") or ""
        if not url:
            return None
        fname = detail.suggested_filename or _filename_from_url(url, "pixabay.jpg")
        return DownloadSpec(url=url, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

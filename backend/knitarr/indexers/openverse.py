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

API = "https://api.openverse.org/v1/images/"

_CRAFT_QUERY = {
    "cross_stitch": "cross stitch OR cross-stitch OR crossstitch",
    "crochet": "crochet",
    "knitting": "knitting OR knit pattern",
    "diamond_painting": "diamond painting OR diamond art",
    "embroidery": "embroidery OR needlework",
    "sewing": "sewing pattern OR dressmaking",
    "quilting": "quilting OR quilt pattern",
    "other": "craft pattern OR handicraft",
}


def _license_class(license_str: str | None) -> LicenseClass:
    if not license_str:
        return LicenseClass.UNKNOWN
    lic = license_str.lower().strip()
    if lic in ("cc0",):
        return LicenseClass.CC0
    if lic in ("pdm", "public domain", "publicdomain"):
        return LicenseClass.PUBLIC_DOMAIN
    if lic.startswith("by"):
        return LicenseClass.CREATIVE_COMMONS
    return LicenseClass.UNKNOWN


def _filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = Path(path).name.split("?")[0]
    return name if name else fallback


class OpenverseIndexer:
    id = "openverse"
    name = "Openverse"

    capabilities = IndexerCapabilities(
        source="Openverse",
        access_method="api",
        authentication="none",
        automated_access_policy="Openverse API; honor rate limits and attribution on each item.",
        license_default=LicenseClass.CREATIVE_COMMONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://openverse.org",
        description="CC-licensed photos and scans; verify each hit is a usable chart, not just inspiration.",
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

    def _search_query(self, query: str, craft: str) -> str:
        craft_term = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
        q = query.strip()
        return f"{craft_term} {q}".strip()

    def _hit_from_result(self, item: dict[str, Any], *, craft: str) -> ExternalHit | None:
        ext_id = item.get("id")
        url = item.get("url")
        if not ext_id or not url:
            return None
        fname = _filename_from_url(url, f"{ext_id}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        title = item.get("title") or fname
        landing = item.get("foreign_landing_url") or f"https://openverse.org/image/{ext_id}"
        return ExternalHit(
            indexer_id=self.id,
            external_id=str(ext_id),
            title=str(title),
            designer=item.get("creator"),
            description=item.get("attribution"),
            source_url=landing,
            pattern_url=landing,
            craft=craft,
            license_class=_license_class(item.get("license")),
            redistribution_allowed=False,
            thumbnail_url=item.get("thumbnail") or url,
            metadata={
                "license": item.get("license"),
                "license_url": item.get("license_url"),
                "provider": item.get("provider"),
                "openverse_url": url,
            },
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        client = await self._client_get()
        params = {
            "q": self._search_query(query, craft),
            "page_size": min(max(limit, 1), 20),
            "mature": "false",
        }
        resp = await client.get(API, params=params)
        resp.raise_for_status()
        data = resp.json()
        hits: list[ExternalHit] = []
        for item in data.get("results") or []:
            hit = self._hit_from_result(item, craft=craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_one(self, external_id: str) -> dict[str, Any]:
        client = await self._client_get()
        resp = await client.get(f"{API}{external_id}/")
        resp.raise_for_status()
        return resp.json()

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        item = await self._fetch_one(external_id)
        hit = self._hit_from_result(item, craft=craft)
        if not hit:
            raise KeyError(external_id)
        url = item.get("url") or ""
        fname = _filename_from_url(url, f"{external_id}.jpg")
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(url),
            suggested_filename=fname,
            all_files=[fname] if url else [],
        )

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_one(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        item = await self._fetch_one(external_id)
        url = item.get("url")
        if not url:
            return None
        fname = _filename_from_url(url, f"{external_id}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        return DownloadSpec(url=url, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

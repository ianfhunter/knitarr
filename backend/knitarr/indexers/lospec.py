"""Lospec community art via Openverse (items hosted or linked from lospec.com)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from knitarr.config import settings
from knitarr.indexers.openverse import OpenverseIndexer, _filename_from_url, _license_class
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass
from knitarr.services.craft_files import file_matches_craft

log = logging.getLogger(__name__)

API = "https://api.openverse.org/v1/images/"


class LospecIndexer:
    id = "lospec"
    name = "Lospec"

    capabilities = IndexerCapabilities(
        source="Lospec",
        access_method="api",
        authentication="none",
        automated_access_policy="Openverse API filtered to lospec.com landing pages.",
        license_default=LicenseClass.CREATIVE_COMMONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://lospec.com/pixel-art-gallery",
        description="Pixel art gallery — search uses Openverse entries tied to Lospec.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._ov = OpenverseIndexer()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        await self._ov.close()

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={"User-Agent": settings.ia_user_agent},
            )
        return self._client

    def _craft_q(self, query: str, craft: str) -> str:
        q = query.strip()
        # Lospec is a pixel-palette gallery; craft terms just bias the Openverse query.
        bases = {
            "cross_stitch": "pixel art cross stitch",
            "crochet": "pixel art crochet",
            "knitting": "pixel art knitting",
            "diamond_painting": "pixel art mosaic",
            "beading": "pixel art bead",
            "iron_beading": "pixel art perler",
            "origami": "origami crease",
            "embroidery": "pixel art embroidery",
            "sewing": "pixel art pattern",
            "quilting": "pixel art quilt",
            "other": "pixel art craft pattern",
        }
        base = bases.get(craft, "pixel art craft pattern")
        return f"{q} {base}".strip() if q else base

    def _hit_from_result(self, item: dict[str, Any], *, craft: str) -> ExternalHit | None:
        landing = (item.get("foreign_landing_url") or "").lower()
        url = item.get("url") or ""
        if "lospec.com" not in landing and "lospec.com" not in url.lower():
            return None
        ext_id = item.get("id")
        if not ext_id or not url:
            return None
        fname = _filename_from_url(url, f"{ext_id}.png")
        if not file_matches_craft(fname, craft):
            return None
        title = item.get("title") or fname
        return ExternalHit(
            indexer_id=self.id,
            external_id=str(ext_id),
            title=str(title),
            designer=item.get("creator"),
            source_url=item.get("foreign_landing_url") or landing or "https://lospec.com/pixel-art-gallery",
            pattern_url=item.get("foreign_landing_url") or url,
            craft=craft,
            license_class=_license_class(item.get("license")),
            redistribution_allowed=False,
            thumbnail_url=item.get("thumbnail") or url,
            metadata={"openverse_id": ext_id, "image_url": url, "license_url": item.get("license_url")},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        client = await self._client_get()
        params = {
            "q": self._craft_q(query, craft),
            "page_size": min(max(limit * 3, 10), 20),
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
        fname = _filename_from_url(url, f"{external_id}.png")
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
        hit = self._hit_from_result(item, craft=craft)
        if not hit:
            return None
        url = item.get("url") or ""
        fname = _filename_from_url(url, f"{external_id}.png")
        return DownloadSpec(url=url, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

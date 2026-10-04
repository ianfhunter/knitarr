"""Cross-Stitch.com free catalog via public JSON APIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse, unquote

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

SITE = "https://cross-stitch.com"
DESIGNS_URL = f"{SITE}/api/designs"
SEMANTIC_URL = f"{SITE}/api/semantic-search"


def _filename_from_url(url: str, fallback: str) -> str:
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1]
    return name or fallback


def design_to_fields(design: dict[str, Any]) -> dict[str, Any]:
    did = design.get("DesignID") or design.get("id")
    caption = (design.get("Caption") or "").strip()
    desc = (design.get("Description") or design.get("SeoDescription") or "").strip()
    return {
        "id": str(did) if did is not None else "",
        "title": caption or (f"Design {did}" if did is not None else ""),
        "description": desc or None,
        "thumbnail": design.get("ImageUrl") or None,
        "pdf": design.get("PdfUrl") or None,
        "width": design.get("Width"),
        "height": design.get("Height"),
        "colors": design.get("NColors"),
        "subject": design.get("subject") or None,
    }


class CrossStitchComIndexer:
    id = "cross_stitch_com"
    name = "Cross-Stitch.com"

    capabilities = IndexerCapabilities(
        source="Cross-Stitch.com",
        access_method="api",
        authentication="none",
        automated_access_policy="Public /api/designs and /api/semantic-search; PDF URLs are hosted on their CDN.",
        license_default=LicenseClass.FREE_DOWNLOAD_NONREDISTRIBUTABLE,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url=SITE,
        description="Free cross-stitch PDFs from cross-stitch.com (personal use; site asks you to register).",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={
                    "User-Agent": settings.ia_user_agent,
                    "Accept": "application/json",
                    "Referer": SITE + "/",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        client = await self._client_get()
        async with self._lock:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            await asyncio.sleep(0.2)
            return resp.json()

    def _hit(self, fields: dict[str, Any], craft: str) -> ExternalHit | None:
        did = fields.get("id") or ""
        if not did or not fields.get("title"):
            return None
        return ExternalHit(
            indexer_id=self.id,
            external_id=did,
            title=fields["title"],
            designer="Cross-Stitch.com",
            description=fields.get("description"),
            source_url=f"{SITE}/photo-to-cross-stitch?source=design_list_catalog&catalogPatternId={did}",
            pattern_url=fields.get("pdf") or f"{SITE}/",
            craft=craft,
            license_class=LicenseClass.FREE_DOWNLOAD_NONREDISTRIBUTABLE,
            redistribution_allowed=False,
            thumbnail_url=fields.get("thumbnail"),
            metadata={
                "width": fields.get("width"),
                "height": fields.get("height"),
                "colors": fields.get("colors"),
                "subject": fields.get("subject"),
            },
        )

    async def _fetch_design(self, design_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"{DESIGNS_URL}/{design_id.strip()}")
        if not isinstance(data, dict) or not (data.get("DesignID") or data.get("id")):
            raise KeyError(design_id)
        return data

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        q = query.strip()
        designs: list[dict[str, Any]] = []
        if q:
            data = await self._request("POST", SEMANTIC_URL, json={"query": q})
            ids = data.get("designIds") if isinstance(data, dict) else None
            for did in (ids or [])[:limit]:
                try:
                    designs.append(await self._fetch_design(str(did)))
                except Exception as e:
                    log.info("cross-stitch.com design %s: %s", did, e)
        else:
            data = await self._request("GET", DESIGNS_URL, params={"pageSize": min(max(limit, 10), 40)})
            designs = list(data.get("designs") or [])[:limit]
        hits: list[ExternalHit] = []
        for design in designs:
            hit = self._hit(design_to_fields(design), craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        fields = design_to_fields(await self._fetch_design(external_id))
        hit = self._hit(fields, craft)
        if not hit:
            raise KeyError(external_id)
        pdf = fields.get("pdf")
        name = _filename_from_url(pdf, f"Stitch{fields['id']}.pdf") if pdf else None
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(pdf),
            suggested_filename=name,
            all_files=[name] if name else [],
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        return await self._fetch_design(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        fields = design_to_fields(await self._fetch_design(external_id))
        pdf = fields.get("pdf")
        if not pdf:
            return None
        name = _filename_from_url(pdf, f"Stitch{fields['id']}.pdf")
        return DownloadSpec(url=pdf, filename=name, all_urls=[(pdf, name)])

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

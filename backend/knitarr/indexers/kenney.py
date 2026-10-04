from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass
from knitarr.services.craft_files import file_matches_craft

log = logging.getLogger(__name__)

BASE = "https://kenney.nl"
ASSETS = f"{BASE}/assets"
ASSET_PAGE = f"{BASE}/assets/{{slug}}"

_SLUG_RE = re.compile(r"href=['\"]https://kenney\.nl/assets/([a-z0-9-]+)['\"]")
_ZIP_RE = re.compile(r"https://kenney\.nl/media/pages/assets/[^\"'\s]+\.zip", re.IGNORECASE)
_COVER_RE = re.compile(
    r'background-image:url\(["\']?(https://kenney\.nl/media/pages/assets/[^"\')]+)["\']?\)',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"<h2>\s*<a href='https://kenney\.nl/assets/[^']+'>([^<]+)</a>\s*</h2>",
    re.IGNORECASE,
)


class KenneyIndexer:
    id = "kenney"
    name = "Kenney (CC0)"

    capabilities = IndexerCapabilities(
        source="Kenney",
        access_method="scrape",
        authentication="none",
        automated_access_policy="Public Kenney.nl asset pages; CC0 game art packs.",
        license_default=LicenseClass.CC0,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://kenney.nl/assets",
        description="CC0 pixel and game asset packs (ZIP downloads from kenney.nl).",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

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

    async def _get_html(self, url: str) -> str:
        client = await self._client_get()
        async with self._lock:
            resp = await client.get(url)
            resp.raise_for_status()
            await asyncio.sleep(0.25)
            return resp.text

    async def _parse_asset(self, slug: str, *, craft: str) -> ExternalHit | None:
        html = await self._get_html(ASSET_PAGE.format(slug=quote(slug, safe="")))
        zips = _ZIP_RE.findall(html)
        if not zips:
            return None
        download = zips[0]
        fname = download.rsplit("/", 1)[-1]
        if not file_matches_craft(fname, craft):
            return None
        title_m = _TITLE_RE.search(html)
        title = title_m.group(1).strip() if title_m else slug.replace("-", " ").title()
        cover_m = _COVER_RE.search(html)
        thumb = cover_m.group(1) if cover_m else None
        return ExternalHit(
            indexer_id=self.id,
            external_id=slug,
            title=title,
            designer="Kenney",
            source_url=ASSET_PAGE.format(slug=quote(slug, safe="")),
            pattern_url=ASSET_PAGE.format(slug=quote(slug, safe="")),
            craft=craft,
            license_class=LicenseClass.CC0,
            redistribution_allowed=False,
            thumbnail_url=thumb,
            metadata={"primary_file": fname},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        q = query.strip()
        url = f"{ASSETS}?q={quote(q)}" if q else ASSETS
        html = await self._get_html(url)
        slugs: list[str] = []
        for slug in _SLUG_RE.findall(html):
            if slug in slugs:
                continue
            slugs.append(slug)
            if len(slugs) >= min(limit * 2, 40):
                break
        hits: list[ExternalHit] = []
        for slug in slugs:
            try:
                hit = await self._parse_asset(slug, craft=craft)
                if hit:
                    hits.append(hit)
            except httpx.HTTPError as e:
                log.debug("Kenney skip %s: %s", slug, e)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        slug = external_id.strip().strip("/")
        hit = await self._parse_asset(slug, craft=craft)
        if not hit:
            raise KeyError(external_id)
        html = await self._get_html(ASSET_PAGE.format(slug=quote(slug, safe="")))
        zips = _ZIP_RE.findall(html)
        fname = zips[0].rsplit("/", 1)[-1] if zips else None
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(zips),
            suggested_filename=fname,
            all_files=[z.rsplit("/", 1)[-1] for z in zips[:5]],
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        slug = external_id.strip().strip("/")
        html = await self._get_html(ASSET_PAGE.format(slug=quote(slug, safe="")))
        return {"slug": slug, "zip_urls": _ZIP_RE.findall(html)}

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        slug = external_id.strip().strip("/")
        html = await self._get_html(ASSET_PAGE.format(slug=quote(slug, safe="")))
        zips = _ZIP_RE.findall(html)
        if not zips:
            return None
        url = zips[0]
        fname = url.rsplit("/", 1)[-1]
        if not file_matches_craft(fname, craft):
            return None
        return DownloadSpec(url=url, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

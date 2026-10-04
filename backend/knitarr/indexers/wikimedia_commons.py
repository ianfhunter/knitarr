from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from knitarr.config import settings
from knitarr.services.craft_files import file_matches_craft
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
FILE_NS = 6


class WikimediaCommonsIndexer:
    id = "wikimedia_commons"
    name = "Wikimedia Commons"

    capabilities = IndexerCapabilities(
        source="Wikimedia Commons",
        access_method="api",
        authentication="none",
        automated_access_policy="MediaWiki API with descriptive User-Agent; respect rate limits.",
        license_default=LicenseClass.CREATIVE_COMMONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://commons.wikimedia.org/wiki/Category:Cross-stitched_patterns",
        description="Openly licensed images and scans; check each file's license on Commons.",
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

    def _file_title(self, external_id: str) -> str:
        if external_id.startswith("File:"):
            return external_id
        return f"File:{external_id}"

    async def _fetch_titles(self, titles: str) -> dict[str, Any]:
        client = await self._client_get()
        resp = await client.get(
            API,
            params={
                "action": "query",
                "titles": titles,
                "prop": "imageinfo|info",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 320,
                "format": "json",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def _hit_from_page(self, page: dict[str, Any], *, craft: str = "cross_stitch") -> ExternalHit | None:
        title = page.get("title") or ""
        if not title.startswith("File:"):
            return None
        pageid = page.get("pageid")
        if not pageid or pageid == -1:
            return None
        info = (page.get("imageinfo") or [{}])[0]
        file_url = info.get("url") or ""
        fname = file_url.split("/")[-1].split("?")[0] or title
        if not file_matches_craft(fname, craft):
            return None
        url = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{quote(title.replace(' ', '_'))}"
        thumb = info.get("thumburl")
        ext = (info.get("extmetadata") or {}).get("LicenseShortName", {}).get("value")
        return ExternalHit(
            indexer_id=self.id,
            external_id=title.removeprefix("File:"),
            title=title.removeprefix("File:"),
            source_url=url,
            pattern_url=url,
            craft=craft,
            license_class=LicenseClass.CREATIVE_COMMONS,
            redistribution_allowed=False,
            thumbnail_url=thumb,
            metadata={"license": ext},
        )

    _CRAFT_QUERY = {
        "cross_stitch": 'cross-stitch OR "cross stitch"',
        "crochet": "crochet",
        "knitting": "knitting OR knit",
        "pixel_art": '"pixel art" OR sprite OR spritesheet OR tileset',
    }

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        q = query.strip()
        craft_term = self._CRAFT_QUERY.get(craft, self._CRAFT_QUERY["cross_stitch"])
        srsearch = f"{craft_term} {q}".strip()
        client = await self._client_get()
        resp = await client.get(
            API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": srsearch,
                "srnamespace": str(FILE_NS),
                "srlimit": str(min(limit, 50)),
                "format": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        hits: list[ExternalHit] = []
        for item in data.get("query", {}).get("search", []):
            title = item.get("title")
            if not title:
                continue
            detail = await self._fetch_titles(title)
            pages = detail.get("query", {}).get("pages", {})
            for page in pages.values():
                hit = self._hit_from_page(page, craft=craft)
                if hit:
                    hits.append(hit)
            if len(hits) >= limit:
                break
        return hits[:limit]

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        title = self._file_title(external_id)
        data = await self._fetch_titles(title)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            hit = self._hit_from_page(page, craft=craft)
            if hit:
                info = (page.get("imageinfo") or [{}])[0]
                fname = info.get("url", "").split("/")[-1] or "image"
                return ExternalDetail(
                    **hit.model_dump(),
                    download_available=bool(info.get("url")),
                    suggested_filename=fname,
                    all_files=[fname] if info.get("url") else [],
                )
        raise KeyError(external_id)

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_titles(self._file_title(external_id))

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        await self.get_pattern(external_id, craft=craft)
        data = await self._fetch_titles(self._file_title(external_id))
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("url")
            if not url:
                return None
            fname = url.split("/")[-1].split("?")[0] or "commons-image.jpg"
            return DownloadSpec(url=url, filename=fname)
        return None

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

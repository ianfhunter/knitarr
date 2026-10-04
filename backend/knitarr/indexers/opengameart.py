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

BASE = "https://opengameart.org"
SEARCH_URL = f"{BASE}/art-search-advanced"
CONTENT_URL = f"{BASE}/content/{{slug}}"

_FILE_RE = re.compile(
    r'href="(https://opengameart\.org/sites/default/files/[^"]+\.(?:zip|png|gif|webp))"',
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r'href="/content/([a-z0-9-]+)"')
_TITLE_RE = re.compile(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h1>', re.IGNORECASE | re.DOTALL)

_SKIP_SLUGS = frozenset(
    {
        "faq",
        "about",
        "legal",
        "privacy",
        "statistics",
        "donate",
        "register",
        "login",
    }
)

_CRAFT_QUERY = {
    "cross_stitch": "pixel sprite cross-stitch",
    "crochet": "pixel crochet",
    "knitting": "pixel knit",
    "diamond_painting": "pixel mosaic",
    "embroidery": "pixel embroidery",
    "sewing": "pixel pattern",
    "quilting": "pixel quilt",
    "other": "pixel craft pattern",
}


def _search_keys(query: str, craft: str) -> str:
    q = query.strip()
    prefix = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
    if not q:
        return prefix
    return f"{q} {prefix}".strip()


def _parse_title(html: str, slug: str) -> str:
    m = _TITLE_RE.search(html)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return slug.replace("-", " ").title()


def _parse_files(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in _FILE_RE.findall(html):
        low = url.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(url)
    return out


def _pick_files(urls: list[str], craft: str) -> tuple[str | None, str | None, list[str]]:
    """Return (download_url, thumbnail_url, all_matching_names)."""
    allowed: list[str] = []
    for url in urls:
        name = url.rsplit("/", 1)[-1].split("?")[0]
        if file_matches_craft(name, craft):
            allowed.append(url)
    if not allowed:
        return None, None, []
    thumb = next((u for u in allowed if "preview" in u.lower()), allowed[0])
    download = next(
        (u for u in allowed if u.lower().endswith(".zip")),
        next((u for u in allowed if "preview" not in u.lower()), allowed[0]),
    )
    names = [u.rsplit("/", 1)[-1] for u in allowed[:20]]
    return download, thumb, names


class OpenGameArtIndexer:
    id = "opengameart"
    name = "OpenGameArt"

    capabilities = IndexerCapabilities(
        source="OpenGameArt.org",
        access_method="scrape",
        authentication="none",
        automated_access_policy="Respect site load; search uses public pages only (no official API).",
        license_default=LicenseClass.CREATIVE_COMMONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://opengameart.org",
        description="CC-licensed sprites, tilesets, and pixel UI packs — great for grid crafts.",
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
            await asyncio.sleep(0.35)
            return resp.text

    async def _fetch_asset(self, slug: str, *, craft: str) -> ExternalHit | None:
        html = await self._get_html(CONTENT_URL.format(slug=quote(slug, safe="")))
        urls = _parse_files(html)
        download, thumb, _names = _pick_files(urls, craft)
        if not download:
            return None
        fname = download.rsplit("/", 1)[-1]
        return ExternalHit(
            indexer_id=self.id,
            external_id=slug,
            title=_parse_title(html, slug),
            source_url=CONTENT_URL.format(slug=quote(slug, safe="")),
            pattern_url=CONTENT_URL.format(slug=quote(slug, safe="")),
            craft=craft,
            license_class=LicenseClass.CREATIVE_COMMONS,
            redistribution_allowed=False,
            thumbnail_url=thumb or download,
            metadata={"primary_file": fname},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        keys = _search_keys(query, craft)
        url = f"{SEARCH_URL}?keys={quote(keys)}&field_art_type_tid[]=9&sort=count"
        html = await self._get_html(url)
        slugs: list[str] = []
        for slug in _SLUG_RE.findall(html):
            if slug in _SKIP_SLUGS or slug in slugs:
                continue
            slugs.append(slug)
            if len(slugs) >= min(limit * 3, 60):
                break
        hits: list[ExternalHit] = []
        for slug in slugs:
            try:
                hit = await self._fetch_asset(slug, craft=craft)
                if hit:
                    hits.append(hit)
            except httpx.HTTPError as e:
                log.debug("OGA skip %s: %s", slug, e)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        slug = external_id.strip().strip("/")
        hit = await self._fetch_asset(slug, craft=craft)
        if not hit:
            raise KeyError(external_id)
        html = await self._get_html(CONTENT_URL.format(slug=quote(slug, safe="")))
        download, _, names = _pick_files(_parse_files(html), craft)
        fname = download.rsplit("/", 1)[-1] if download else None
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(download),
            suggested_filename=fname,
            all_files=names,
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        slug = external_id.strip().strip("/")
        html = await self._get_html(CONTENT_URL.format(slug=quote(slug, safe="")))
        return {"slug": slug, "files": _parse_files(html)}

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        slug = external_id.strip().strip("/")
        html = await self._get_html(CONTENT_URL.format(slug=quote(slug, safe="")))
        download, _, _ = _pick_files(_parse_files(html), craft)
        if not download:
            return None
        fname = download.rsplit("/", 1)[-1]
        return DownloadSpec(url=download, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

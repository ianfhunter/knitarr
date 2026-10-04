"""Cross Stitch Quest — free geeky charts via the WordPress.com public API."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

SITE = "crossstitchquest.wordpress.com"
API = f"https://public-api.wordpress.com/rest/v1.1/sites/{SITE}/posts"
SITE_URL = "https://crossstitchquest.net/"


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _filename_from_url(url: str, fallback: str) -> str:
    path = unquote(urlparse(url).path)
    name = path.rsplit("/", 1)[-1]
    return name or fallback


def _is_patreon_only(title: str) -> bool:
    return "patreon only" in (title or "").lower()


def _attachment_files(post: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    attachments = post.get("attachments") or {}
    if isinstance(attachments, dict):
        items = attachments.values()
    else:
        items = attachments
    for att in items:
        if not isinstance(att, dict):
            continue
        url = att.get("URL") or att.get("url") or ""
        if not url:
            continue
        files.append(
            {
                "url": url,
                "title": att.get("title") or "",
                "mime": (att.get("mime_type") or att.get("mime") or "").lower(),
            }
        )
    return files


def pick_pattern_files(post: dict[str, Any]) -> list[tuple[str, str]]:
    """Prefer the chart PDF, then non-preview pattern images."""
    files = _attachment_files(post)
    pdfs = [f for f in files if f["mime"] == "application/pdf" or f["url"].lower().endswith(".pdf")]
    charts = [
        f
        for f in files
        if "preview" not in f["title"].lower()
        and "preview" not in f["url"].lower()
        and (f["mime"].startswith("image/") or f["url"].lower().endswith((".png", ".jpg", ".jpeg")))
        and "pattern" in f["title"].lower()
    ]
    picked = pdfs or charts
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for f in picked:
        url = f["url"]
        if url in seen:
            continue
        seen.add(url)
        out.append((url, _filename_from_url(url, "pattern.bin")))
    return out


class CrossStitchQuestIndexer:
    id = "cross_stitch_quest"
    name = "Cross Stitch Quest"

    capabilities = IndexerCapabilities(
        source="Cross Stitch Quest",
        access_method="api",
        authentication="none",
        automated_access_policy="WordPress.com public REST API; free posts only, no Patreon-only charts.",
        license_default=LicenseClass.FREE_WITH_RESTRICTIONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url=SITE_URL,
        description="Free geeky cross-stitch patterns from crossstitchquest.net. Patreon-only posts are skipped.",
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

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client = await self._client_get()
        async with self._lock:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            await asyncio.sleep(0.2)
            return resp.json()

    def _hit(self, post: dict[str, Any], craft: str) -> ExternalHit | None:
        title = _strip_html(str(post.get("title") or ""))
        if not title or _is_patreon_only(title):
            return None
        files = pick_pattern_files(post)
        if not files:
            return None
        pid = str(post.get("ID") or post.get("id") or "")
        if not pid:
            return None
        url = (post.get("URL") or post.get("link") or SITE_URL).replace("http://", "https://")
        return ExternalHit(
            indexer_id=self.id,
            external_id=pid,
            title=title,
            designer="Sanorace",
            description=_strip_html(str(post.get("excerpt") or ""))[:400] or None,
            source_url=url,
            pattern_url=url,
            craft=craft,
            license_class=LicenseClass.FREE_WITH_RESTRICTIONS,
            redistribution_allowed=False,
            thumbnail_url=post.get("featured_image") or None,
            metadata={"slug": post.get("slug"), "files": [n for _, n in files]},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        params: dict[str, Any] = {
            "number": min(max(limit * 2, 10), 100),
            "fields": "ID,title,URL,excerpt,featured_image,attachments,slug",
        }
        q = query.strip()
        if q:
            params["search"] = q
        data = await self._get_json(API, params)
        hits: list[ExternalHit] = []
        for post in data.get("posts") or []:
            hit = self._hit(post, craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_post(self, external_id: str) -> dict[str, Any]:
        data = await self._get_json(f"{API}/{external_id.strip()}")
        if not data.get("ID") and not data.get("id"):
            raise KeyError(external_id)
        return data

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        post = await self._fetch_post(external_id)
        hit = self._hit(post, craft)
        if not hit:
            raise KeyError(external_id)
        files = pick_pattern_files(post)
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(files),
            suggested_filename=files[0][1] if files else None,
            all_files=[n for _, n in files],
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        return await self._fetch_post(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        post = await self._fetch_post(external_id)
        if _is_patreon_only(str(post.get("title") or "")):
            return None
        files = pick_pattern_files(post)
        if not files:
            return None
        return DownloadSpec(url=files[0][0], filename=files[0][1], all_urls=files)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

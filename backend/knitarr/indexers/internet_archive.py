from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import httpx

from knitarr.config import settings
from knitarr.services.craft_files import file_matches_craft
from knitarr.models import (
    DownloadSpec,
    ExternalDetail,
    ExternalHit,
    IndexerCapabilities,
    IndexerStatus,
    LicenseClass,
)

log = logging.getLogger(__name__)

SCRAPE_URL = "https://archive.org/services/search/v1/scrape"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_BASE = "https://archive.org/download/{identifier}/{filename}"
DETAILS_BASE = "https://archive.org/details/{identifier}"


_CRAFT_QUERY = {
    "cross_stitch": '(subject:"Cross-stitch" OR title:cross-stitch OR "cross stitch" OR cross-stitch)',
    "crochet": '(crochet OR "crochet pattern")',
    "knitting": '(knitting OR knit OR "knitting pattern")',
    "diamond_painting": '("diamond painting" OR "diamond art" OR "diamond dot")',
    "embroidery": '(embroidery OR "embroidery pattern" OR "hand embroidery")',
    "sewing": '(sewing OR "sewing pattern" OR "dressmaking")',
    "quilting": '(quilting OR quilt OR "quilt pattern")',
    "other": '(craft OR handicraft OR "craft pattern")',
}


def _build_query(user_query: str, craft: str = "cross_stitch") -> str:
    craft_q = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
    user_query = user_query.strip()
    if not user_query:
        return craft_q
    safe = user_query.replace('"', "")
    if " " not in safe and all(c.isalnum() or c in "-_" for c in safe):
        return f"{craft_q} AND (identifier:{safe} OR title:({safe}) OR description:({safe}))"
    return f"{craft_q} AND (title:({safe}) OR description:({safe}))"


def _creator_str(meta: dict[str, Any]) -> str | None:
    c = meta.get("creator")
    if isinstance(c, list):
        return c[0] if c else None
    return c


def _is_restricted(meta: dict[str, Any]) -> bool:
    if meta.get("access-restricted-item") in (True, "true", "True", "1"):
        return True
    return meta.get("loans__status__status") == "restricted"


def _score_file(name: str, size: int) -> tuple[int, int]:
    lower = name.lower()
    if "_thumb" in lower or lower.startswith("__"):
        return (99, 0)
    if lower.endswith(".oxs"):
        return (0, -size)
    if lower.endswith(".saga"):
        return (1, -size)
    if lower.endswith((".xps", ".oxps")):
        return (2, -size)
    if lower.endswith(".pdf"):
        return (3, -size)
    if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return (4, -size)
    return (10, -size)


def _pick_files(files: list[dict[str, Any]], craft: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for f in files:
        name = f.get("name") or ""
        if not name or name.endswith(".torrent"):
            continue
        if not file_matches_craft(name, craft):
            continue
        fmt = (f.get("format") or "").lower()
        if "metadata" in fmt:
            continue
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        candidates.append((name, size))
    candidates.sort(key=lambda x: _score_file(x[0], x[1]))
    return candidates


class InternetArchiveIndexer:
    id = "internet_archive"
    name = "Internet Archive"

    capabilities = IndexerCapabilities(
        source="Internet Archive",
        access_method="api",
        authentication="none",
        automated_access_policy="Use documented Search Scrape and Metadata APIs with descriptive User-Agent; honor 429/Retry-After.",
        license_default=LicenseClass.UNKNOWN,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://archive.org",
        description="Public-domain and community-uploaded books, PDFs, and pattern scans.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={"User-Agent": settings.ia_user_agent},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = await self._get_client()
        delay = settings.ia_request_delay_sec
        async with self._lock:
            for attempt in range(5):
                resp = await client.request(method, url, **kwargs)
                if resp.status_code != 429:
                    resp.raise_for_status()
                    if delay:
                        await asyncio.sleep(delay)
                    return resp
                retry = resp.headers.get("Retry-After")
                wait = float(retry) if retry and retry.isdigit() else 2**attempt
                log.warning("IA rate limited; waiting %ss", wait)
                await asyncio.sleep(wait)
        raise httpx.HTTPStatusError("Rate limited", request=resp.request, response=resp)

    async def _fetch_metadata(self, identifier: str) -> dict[str, Any]:
        url = METADATA_URL.format(identifier=quote(identifier, safe=""))
        resp = await self._request("GET", url)
        return resp.json()

    def _hit_from_item(
        self, item: dict[str, Any], meta: dict[str, Any] | None = None, *, craft: str = "cross_stitch"
    ) -> ExternalHit:
        identifier = item.get("identifier") or item.get("external_id") or ""
        title = item.get("title") or meta.get("title") if meta else None
        if isinstance(title, list):
            title = title[0]
        title = title or identifier
        license_url = None
        if meta:
            license_url = meta.get("licenseurl") or meta.get("license")
        elif item.get("licenseurl"):
            license_url = item.get("licenseurl")
        desc = item.get("description") or (meta.get("description") if meta else None)
        if isinstance(desc, list):
            desc = " ".join(str(x) for x in desc)
        thumb = f"https://archive.org/services/img/{identifier}"
        return ExternalHit(
            indexer_id=self.id,
            external_id=identifier,
            title=str(title),
            designer=_creator_str(meta) if meta else _creator_str(item),
            description=str(desc)[:2000] if desc else None,
            source_url=DETAILS_BASE.format(identifier=identifier),
            pattern_url=DETAILS_BASE.format(identifier=identifier),
            craft=craft,
            license_class=LicenseClass.UNKNOWN,
            redistribution_allowed=False,
            thumbnail_url=thumb,
            metadata={"licenseurl": license_url, "mediatype": item.get("mediatype")},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        q = _build_query(query, craft)
        params = {
            "q": q,
            "fields": "identifier,title,creator,description,licenseurl,mediatype",
            "count": max(100, min(limit * 2, 100)),
        }
        resp = await self._request("GET", SCRAPE_URL, params=params)
        data = resp.json()
        hits: list[ExternalHit] = []
        for item in data.get("items", []):
            ident = item.get("identifier")
            if not ident:
                continue
            try:
                payload = await self._fetch_metadata(ident)
                if _is_restricted(payload.get("metadata", {})):
                    continue
                if not _pick_files(payload.get("files") or [], craft):
                    continue
                hits.append(self._hit_from_item(item, payload.get("metadata", {}), craft=craft))
            except httpx.HTTPError as e:
                log.debug("skip %s: %s", ident, e)
                continue
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        payload = await self._fetch_metadata(external_id)
        meta = payload.get("metadata", {})
        files = payload.get("files") or []
        hit = self._hit_from_item({"identifier": external_id, **meta}, meta, craft=craft)
        picked = _pick_files(files, craft)
        download_available = bool(picked) and not _is_restricted(meta)
        suggested = picked[0][0] if picked else None
        detail = ExternalDetail(
            **hit.model_dump(),
            download_available=download_available,
            suggested_filename=suggested,
            all_files=[n for n, _ in picked[:30]],
        )
        return detail

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_metadata(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        payload = await self._fetch_metadata(external_id)
        meta = payload.get("metadata", {})
        if _is_restricted(meta):
            return None
        picked = _pick_files(payload.get("files") or [], craft)
        if not picked:
            return None
        image_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        image_pages = [
            (n, s)
            for n, s in picked
            if n.lower().endswith(image_exts) and "_thumb" not in n.lower()
        ]
        if len(image_pages) > 1 and not any(n.lower().endswith(".pdf") for n, _ in picked):
            urls = [
                (DOWNLOAD_BASE.format(identifier=external_id, filename=quote(n, safe="")), n)
                for n, _ in image_pages
            ]
            return DownloadSpec(url=urls[0][0], filename=urls[0][1], all_urls=urls)

        name = picked[0][0]
        url = DOWNLOAD_BASE.format(identifier=external_id, filename=quote(name, safe=""))
        return DownloadSpec(url=url, filename=name)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        payload = await self._fetch_metadata(external_id)
        updated = payload.get("item_last_updated") or payload.get("metadata", {}).get("updatedate")
        changed = known_etag is not None and str(updated) != known_etag
        return {"updated": updated, "changed": changed}

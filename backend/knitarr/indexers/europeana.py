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

SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"
RECORD_URL = "https://api.europeana.eu/record/v2/{record_id}.json"

_CRAFT_QUERY = {
    "cross_stitch": "cross stitch OR cross-stitch OR embroidery chart",
    "crochet": "crochet",
    "knitting": "knitting OR knit",
    "pixel_art": "pixel art OR embroidery chart OR cross-stitch pattern",
}


def _record_id_from_item(item: dict[str, Any]) -> str:
    raw = item.get("id") or ""
    return raw.lstrip("/")


def _first(values: list[str] | str | None) -> str | None:
    if isinstance(values, list):
        return values[0] if values else None
    return values


def _filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = Path(path).name.split("?")[0]
    return name if name else fallback


class EuropeanaIndexer:
    id = "europeana"
    name = "Europeana"

    capabilities = IndexerCapabilities(
        source="Europeana",
        access_method="api",
        authentication="api_key",
        automated_access_policy="Europeana Record API; use your own wskey for production (KNITARR_EUROPEANA_API_KEY).",
        license_default=LicenseClass.UNKNOWN,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url="https://www.europeana.eu",
        description="European museums and libraries — embroidery, textiles, and digitized pattern books.",
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

    def _wskey(self) -> str:
        key = (settings.europeana_api_key or "").strip()
        if not key:
            raise RuntimeError("KNITARR_EUROPEANA_API_KEY is not set")
        return key

    def _search_query(self, query: str, craft: str) -> str:
        craft_term = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
        q = query.strip()
        return f"({craft_term}) {q}".strip()

    def _hit_from_item(self, item: dict[str, Any], *, craft: str) -> ExternalHit | None:
        record_id = _record_id_from_item(item)
        if not record_id:
            return None
        download_url = _first(item.get("edmIsShownBy"))
        if not download_url:
            return None
        fname = _filename_from_url(download_url, f"{record_id.replace('/', '_')}.jpg")
        if not file_matches_craft(fname, craft):
            return None
        dc_title = item.get("dcTitleLangAware")
        title = None
        if isinstance(dc_title, dict):
            title = _first(dc_title.get("en"))
        title = title or _first(item.get("title")) or record_id
        if isinstance(title, list):
            title = title[0] if title else record_id
        shown_at = _first(item.get("edmIsShownAt")) or f"https://www.europeana.eu/item/{record_id}"
        thumb = _first(item.get("edmPreview"))
        desc = _first(item.get("dcDescriptionLangAware", {}).get("en")) or _first(item.get("dcDescription"))
        if isinstance(desc, list):
            desc = desc[0] if desc else None
        return ExternalHit(
            indexer_id=self.id,
            external_id=record_id,
            title=str(title),
            description=str(desc)[:2000] if desc else None,
            source_url=shown_at,
            pattern_url=shown_at,
            craft=craft,
            license_class=LicenseClass.UNKNOWN,
            redistribution_allowed=False,
            thumbnail_url=thumb,
            metadata={"rights": _first(item.get("rights")), "dataProvider": _first(item.get("dataProvider"))},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        client = await self._client_get()
        params = {
            "wskey": self._wskey(),
            "query": self._search_query(query, craft),
            "rows": min(max(limit, 1), 50),
            "profile": "standard",
            "reusability": "open",
        }
        resp = await client.get(SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        hits: list[ExternalHit] = []
        for item in data.get("items") or []:
            hit = self._hit_from_item(item, craft=craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_record(self, record_id: str) -> dict[str, Any]:
        client = await self._client_get()
        url = RECORD_URL.format(record_id=quote(record_id, safe="/"))
        resp = await client.get(url, params={"wskey": self._wskey(), "profile": "standard"})
        resp.raise_for_status()
        return resp.json()

    def _download_from_record(self, payload: dict[str, Any], craft: str) -> tuple[str, str] | None:
        ag = (payload.get("object") or {}).get("aggregations") or []
        if not ag:
            return None
        download_url = _first(ag[0].get("edmIsShownBy"))
        if not download_url:
            return None
        fname = _filename_from_url(download_url, "europeana-item.jpg")
        if not file_matches_craft(fname, craft):
            return None
        return download_url, fname

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        payload = await self._fetch_record(external_id)
        item = {"id": f"/{external_id}", **(payload.get("object") or {})}
        ag = item.get("aggregations") or []
        if ag:
            item["edmIsShownBy"] = ag[0].get("edmIsShownBy")
            item["edmIsShownAt"] = ag[0].get("edmIsShownAt")
            item["edmPreview"] = ag[0].get("edmPreview")
        hit = self._hit_from_item(item, craft=craft)
        if not hit:
            raise KeyError(external_id)
        dl = self._download_from_record(payload, craft)
        fname = dl[1] if dl else None
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(dl),
            suggested_filename=fname,
            all_files=[fname] if fname else [],
        )

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_record(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        payload = await self._fetch_record(external_id)
        dl = self._download_from_record(payload, craft)
        if not dl:
            return None
        url, fname = dl
        return DownloadSpec(url=url, filename=fname)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from urllib.parse import quote

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

ALGOLIA_URL = "https://{app_id}-dsn.algolia.net/1/indexes/{index}/query"
DEFAULT_APP_ID = "YCVRTN9Y8R"
DEFAULT_SEARCH_KEY = "17b225eadafc806fc2580708484de4d5"
DEFAULT_INDEX = "products_en_production"

_CRAFT_TAXON: dict[str, str] = {
    "cross_stitch": "patterns/free-patterns-by-craft/cross-stitch",
    "crochet": "patterns/free-patterns-by-craft/crochet",
    "knitting": "patterns/free-patterns-by-craft/knitting",
}

_CRAFT_LABEL: dict[str, str] = {
    "cross_stitch": "Cross Stitch",
    "crochet": "Crochet",
    "knitting": "Knitting",
}

_CRAFT_QUERY: dict[str, str] = {
    "cross_stitch": "cross stitch",
    "crochet": "crochet",
    "knitting": "knitting",
    "pixel_art": "pattern",
}


def _product_url(hit: dict[str, Any]) -> str:
    urls = hit.get("urls") or {}
    raw = urls.get("US") or urls.get("GB") or ""
    if not raw and hit.get("slug"):
        raw = f"https://www.dmc.com/US/en/products/{hit['slug']}"
    return raw.replace("http://www.dmc.com", "https://www.dmc.com").replace(
        "http://dmc.com", "https://www.dmc.com"
    )


def _price_usd(hit: dict[str, Any]) -> float | None:
    cents = (hit.get("priceCents") or {}).get("US")
    if cents is None:
        return None
    try:
        return float(cents) / 100.0
    except (TypeError, ValueError):
        return None


def _matches_craft(hit: dict[str, Any], craft: str) -> bool:
    label = _CRAFT_LABEL.get(craft)
    hit_craft = hit.get("craft")
    if label and hit_craft:
        return hit_craft == label
    if label:
        name = (hit.get("name") or "").lower()
        taxon = " ".join(hit.get("taxon") or []).lower()
        needle = label.lower()
        return needle in name or needle.replace(" ", "-") in taxon
    return hit.get("category") == "Patterns"


class _DMCAlgoliaIndexer:
    """DMC.com product search via public Algolia credentials embedded in their storefront."""

    _mode: Literal["free", "paid"]

    def __init__(self, *, mode: Literal["free", "paid"]) -> None:
        self._mode = mode
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    @property
    def _app_id(self) -> str:
        return (settings.dmc_algolia_app_id or DEFAULT_APP_ID).strip()

    @property
    def _search_key(self) -> str:
        return (settings.dmc_algolia_search_key or DEFAULT_SEARCH_KEY).strip()

    @property
    def _index(self) -> str:
        return (settings.dmc_algolia_index or DEFAULT_INDEX).strip()

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={
                    "User-Agent": settings.ia_user_agent,
                    "X-Algolia-Application-Id": self._app_id,
                    "X-Algolia-API-Key": self._search_key,
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_query(self, query: str, craft: str) -> dict[str, Any]:
        q = query.strip()
        craft_q = _CRAFT_QUERY.get(craft, _CRAFT_QUERY["cross_stitch"])
        if q:
            q = f"{q} {craft_q}".strip()
        else:
            q = craft_q
        body: dict[str, Any] = {
            "query": q,
            "hitsPerPage": 50,
            "facetFilters": [["category:Patterns"]],
        }
        if self._mode == "free":
            taxon = _CRAFT_TAXON.get(craft, _CRAFT_TAXON["cross_stitch"])
            body["facetFilters"] = [
                ["category:Patterns"],
                [f"taxon:{taxon}"],
            ]
            body["filters"] = "priceCents.US=0"
        else:
            body["filters"] = "priceCents.US > 0 AND category:Patterns"
        return body

    def _hit_from_record(self, hit: dict[str, Any], *, craft: str) -> ExternalHit | None:
        if hit.get("category") != "Patterns":
            return None
        if not _matches_craft(hit, craft):
            return None
        slug = hit.get("slug")
        if not slug:
            return None
        price = _price_usd(hit)
        if self._mode == "free" and price not in (None, 0.0):
            return None
        if self._mode == "paid" and (price is None or price <= 0):
            return None
        url = _product_url(hit)
        license_class = (
            LicenseClass.PURCHASE_REQUIRED if self._mode == "paid" else LicenseClass.FREE_WITH_RESTRICTIONS
        )
        return ExternalHit(
            indexer_id=self.id,
            external_id=str(slug),
            title=str(hit.get("name") or slug),
            description=(hit.get("description") or "")[:2000] or None,
            source_url=url,
            pattern_url=url,
            craft=craft,
            license_class=license_class,
            redistribution_allowed=False,
            thumbnail_url=hit.get("image"),
            metadata={
                "sku": hit.get("sku"),
                "level": hit.get("level"),
                "dmc_craft": hit.get("craft"),
                "price_usd": price,
                "mode": self._mode,
            },
        )

    async def _search_algolia(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        client = await self._client_get()
        url = ALGOLIA_URL.format(app_id=self._app_id, index=quote(self._index, safe=""))
        async with self._lock:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            await asyncio.sleep(0.2)
            return resp.json().get("hits") or []

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        body = self._build_query(query, craft)
        body["hitsPerPage"] = min(max(limit, 1), 50)
        records = await self._search_algolia(body)
        hits: list[ExternalHit] = []
        for record in records:
            hit = self._hit_from_record(record, craft=craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_slug(self, slug: str) -> dict[str, Any]:
        body = {"query": "", "filters": f'slug:"{slug}"', "hitsPerPage": 1}
        hits = await self._search_algolia(body)
        if not hits:
            raise KeyError(slug)
        return hits[0]

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        record = await self._fetch_slug(external_id)
        hit = self._hit_from_record(record, craft=craft)
        if not hit:
            raise KeyError(external_id)
        return ExternalDetail(
            **hit.model_dump(),
            download_available=False,
            suggested_filename=f"{external_id}.pdf",
            all_files=[],
        )

    async def get_metadata(self, external_id: str) -> dict:
        return await self._fetch_slug(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        return None

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}


class DMCFreeIndexer(_DMCAlgoliaIndexer):
    id = "dmc_free"
    name = "DMC Free Patterns"

    capabilities = IndexerCapabilities(
        source="DMC",
        access_method="api",
        authentication="none",
        automated_access_policy="DMC storefront Algolia search (public search-only key); download PDFs from product pages.",
        license_default=LicenseClass.FREE_WITH_RESTRICTIONS,
        can_download=False,
        status=IndexerStatus.ACTIVE,
        site_url="https://www.dmc.com/US/en/patterns/free-patterns-by-craft/cross-stitch",
        description="Official free DMC cross-stitch and craft PDF patterns from dmc.com.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        super().__init__(mode="free")


class DMCPaidIndexer(_DMCAlgoliaIndexer):
    id = "dmc_shop"
    name = "DMC Shop"

    capabilities = IndexerCapabilities(
        source="DMC",
        access_method="api",
        authentication="none",
        automated_access_policy="DMC storefront Algolia search for paid pattern products.",
        license_default=LicenseClass.PURCHASE_REQUIRED,
        can_download=False,
        status=IndexerStatus.ACTIVE,
        site_url="https://www.dmc.com/US/en/patterns",
        description="Paid DMC patterns, leaflets, and books — purchase on dmc.com; import after download.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        super().__init__(mode="paid")

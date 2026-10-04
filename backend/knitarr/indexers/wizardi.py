"""Wizardi free counted cross-stitch charts (Shopify collection; checkout required)."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
from typing import Any

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

COLLECTION = "free-counted-cross-stitch-charts"
COLLECTION_URL = f"https://wizardi.com/collections/{COLLECTION}"
PRODUCTS_JSON = f"{COLLECTION_URL}/products.json"
PRODUCT_JSON = "https://wizardi.com/products/{handle}.json"
_CACHE_TTL = 30 * 60


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _matches(product: dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    tags = product.get("tags") or []
    if isinstance(tags, str):
        tag_text = tags
    else:
        tag_text = " ".join(str(t) for t in tags)
    hay = " ".join(
        filter(
            None,
            (product.get("title"), product.get("vendor"), product.get("handle"), tag_text),
        )
    ).lower()
    return all(tok in hay for tok in q.split())


def product_to_fields(product: dict[str, Any]) -> dict[str, Any]:
    images = product.get("images") or []
    thumb = None
    if images and isinstance(images[0], dict):
        thumb = images[0].get("src")
    return {
        "handle": product.get("handle") or "",
        "title": product.get("title") or "",
        "vendor": product.get("vendor") or "",
        "description": _strip_html(str(product.get("body_html") or ""))[:400],
        "thumbnail": thumb,
    }


class WizardiIndexer:
    id = "wizardi"
    name = "Wizardi (free charts)"

    capabilities = IndexerCapabilities(
        source="Wizardi",
        access_method="api",
        authentication="none",
        automated_access_policy="Shopify storefront products.json; charts require a free checkout email, so Knitarr does not download them.",
        license_default=LicenseClass.FREE_DOWNLOAD_NONREDISTRIBUTABLE,
        can_download=False,
        status=IndexerStatus.ACTIVE,
        site_url=COLLECTION_URL,
        description="Free counted cross-stitch PDFs from wizardi.com — browse here, complete their free checkout to download, then import.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._products: list[dict[str, Any]] | None = None
        self._products_at = 0.0

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

    async def _load_collection(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._products is not None and now - self._products_at < _CACHE_TTL:
            return self._products
        products: list[dict[str, Any]] = []
        page = 1
        while page <= 20:
            data = await self._get_json(PRODUCTS_JSON, {"limit": 250, "page": page})
            batch = data.get("products") or []
            if not batch:
                break
            products.extend(batch)
            if len(batch) < 250:
                break
            page += 1
        self._products = products
        self._products_at = time.monotonic()
        log.info("Wizardi free collection: %s products", len(products))
        return products

    def _hit(self, product: dict[str, Any], craft: str) -> ExternalHit | None:
        fields = product_to_fields(product)
        handle = fields["handle"]
        if not handle or not fields["title"]:
            return None
        return ExternalHit(
            indexer_id=self.id,
            external_id=handle,
            title=fields["title"],
            designer=fields["vendor"] or None,
            description=fields["description"] or None,
            source_url=f"https://wizardi.com/products/{handle}",
            pattern_url=f"https://wizardi.com/products/{handle}",
            craft=craft,
            license_class=LicenseClass.FREE_DOWNLOAD_NONREDISTRIBUTABLE,
            redistribution_allowed=False,
            thumbnail_url=fields["thumbnail"],
            metadata={"handle": handle},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        hits: list[ExternalHit] = []
        for product in await self._load_collection():
            if not _matches(product, query):
                continue
            hit = self._hit(product, craft)
            if hit:
                hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _fetch_product(self, handle: str) -> dict[str, Any]:
        data = await self._get_json(PRODUCT_JSON.format(handle=handle.strip()))
        product = data.get("product") or data
        if not product.get("handle"):
            raise KeyError(handle)
        return product

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        product = await self._fetch_product(external_id)
        hit = self._hit(product, craft)
        if not hit:
            raise KeyError(external_id)
        return ExternalDetail(
            **hit.model_dump(),
            download_available=False,
            suggested_filename=None,
            all_files=[],
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        return await self._fetch_product(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        return None

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

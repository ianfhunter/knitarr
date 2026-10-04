"""Cyberstitchers free PDF/PAT charts — HTML catalog with a path-based search."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

BASE = "https://www.cyberstitchers.com"
LIST_URL = f"{BASE}/free_patterns/"
_PAGE_OF_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_PANEL_RE = re.compile(r'<div class="panel panel-default">(.*?)</table>', re.IGNORECASE | re.DOTALL)
_SLUG_LINK_RE = re.compile(r"href=['\"]/free_patterns/pattern/([a-z0-9_]+)['\"]>([^<]+)</a>", re.IGNORECASE)
_A2A_RE = re.compile(
    r"data-a2a-url=['\"][^'\"]*/free_patterns/pattern/([a-z0-9_]+)['\"][^>]*data-a2a-title=['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_A2A_SWAP_RE = re.compile(
    r"data-a2a-title=['\"]([^'\"]+)['\"][^>]*data-a2a-url=['\"][^'\"]*/free_patterns/pattern/([a-z0-9_]+)['\"]",
    re.IGNORECASE,
)
_ID_RE = re.compile(r"/free_patterns/download/(\d+)/(PDF|PAT)", re.IGNORECASE)
_THUMB_RE = re.compile(r"src=['\"](/Data/PatternLibrary/img/[^'\"]+)['\"]", re.IGNORECASE)
_FIELD_RE = re.compile(r"<th>([^<]+)</th>\s*<td>\s*(.*?)</td>", re.IGNORECASE | re.DOTALL)
_DIM_RE = re.compile(r"(\d+)\s*w\s*x\s*(\d+)\s*h", re.IGNORECASE)
_HEADING_RE = re.compile(r'<div class="panel-heading">(.*?)</div>', re.IGNORECASE | re.DOTALL)


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_page_counts(html: str) -> tuple[int, int]:
    m = _PAGE_OF_RE.search(html)
    if not m:
        return 1, 1
    return int(m.group(1)), int(m.group(2))


def _field_map(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, body in _FIELD_RE.findall(block):
        key = _clean(label).rstrip(":").lower()
        out[key] = _clean(body.split("<a", 1)[0] if "<a" in body.lower() else body)
    return out


def parse_cards(html: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _PANEL_RE.findall(html):
        slug = ""
        title = ""
        slug_m = _SLUG_LINK_RE.search(block)
        if slug_m:
            slug, title = slug_m.group(1), _clean(slug_m.group(2))
        if not slug:
            a2a = _A2A_RE.search(block) or None
            if a2a:
                slug, title = a2a.group(1), _clean(a2a.group(2))
            else:
                swapped = _A2A_SWAP_RE.search(block)
                if swapped:
                    title, slug = _clean(swapped.group(1)), swapped.group(2)
        if not title:
            head = _HEADING_RE.search(block)
            if head:
                title = _clean(head.group(1))
                title = re.sub(r"^‹?\s*Back\s*", "", title, flags=re.IGNORECASE).strip()
        ids = {m.group(1) for m in _ID_RE.finditer(block)}
        if not ids:
            thumb_ids = re.findall(r"/Data/PatternLibrary/img/(\d+)", block, re.IGNORECASE)
            ids = set(thumb_ids)
        pattern_id = next(iter(ids), "")
        if not slug or not pattern_id or slug in seen:
            continue
        seen.add(slug)
        fields = _field_map(block)
        thumbs = _THUMB_RE.findall(block)
        dim = _DIM_RE.search(fields.get("dimensions") or block)
        formats = {m.group(2).upper() for m in _ID_RE.finditer(block)}
        cards.append(
            {
                "slug": slug,
                "id": pattern_id,
                "title": title or slug.replace("_", " ").title(),
                "designer": fields.get("designer") or None,
                "category": fields.get("category") or None,
                "width": int(dim.group(1)) if dim else None,
                "height": int(dim.group(2)) if dim else None,
                "thumbnail": urljoin(BASE, thumbs[0]) if thumbs else None,
                "has_pdf": "PDF" in formats or True,
                "has_pat": "PAT" in formats,
            }
        )
    return cards


def search_path(query: str) -> str:
    q = re.sub(r"[^a-zA-Z0-9]+", " ", query).strip()
    if not q:
        return "/free_patterns/"
    return f"/free_patterns/search_{quote(q, safe='')}"


def page_path(base_path: str, page: int, total: int) -> str:
    base = base_path.rstrip("/")
    if page <= 1:
        return base + "/"
    return f"{base}/page{page}of{total}/"


class CyberstitchersIndexer:
    id = "cyberstitchers"
    name = "CyberStitchers"

    capabilities = IndexerCapabilities(
        source="Cyberstitchers",
        access_method="scrape",
        authentication="none",
        automated_access_policy="Public free-pattern HTML catalog and PDF/PAT downloads; polite fetch.",
        license_default=LicenseClass.FREE_WITH_RESTRICTIONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url=LIST_URL,
        description="Free cross-stitch PDFs and PCStitch files from cyberstitchers.com.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

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

    async def _get_html(self, path: str) -> str:
        client = await self._client_get()
        async with self._lock:
            resp = await client.get(urljoin(BASE + "/", path.lstrip("/")))
            resp.raise_for_status()
            await asyncio.sleep(0.25)
            return resp.text

    def _remember(self, card: dict[str, Any]) -> None:
        self._cache[card["slug"]] = card

    def _hit(self, card: dict[str, Any], craft: str) -> ExternalHit:
        slug = card["slug"]
        bits = [card.get("category") or ""]
        if card.get("width") and card.get("height"):
            bits.append(f"{card['width']}w x {card['height']}h")
        return ExternalHit(
            indexer_id=self.id,
            external_id=slug,
            title=card["title"],
            designer=card.get("designer") or None,
            description=" — ".join(b for b in bits if b) or None,
            source_url=f"{BASE}/free_patterns/pattern/{slug}",
            pattern_url=f"{BASE}/free_patterns/download/{card['id']}/PDF",
            craft=craft,
            license_class=LicenseClass.FREE_WITH_RESTRICTIONS,
            redistribution_allowed=False,
            thumbnail_url=card.get("thumbnail"),
            metadata={
                "id": card["id"],
                "slug": slug,
                "category": card.get("category"),
                "width": card.get("width"),
                "height": card.get("height"),
            },
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        base = search_path(query)
        html = await self._get_html(base)
        _page, total = parse_page_counts(html)
        hits: list[ExternalHit] = []
        pages_needed = min(max(total, 1), max(1, (limit + 11) // 12), 8)
        for page in range(1, pages_needed + 1):
            if page > 1:
                html = await self._get_html(page_path(base, page, total))
            for card in parse_cards(html):
                self._remember(card)
                hits.append(self._hit(card, craft))
                if len(hits) >= limit:
                    return hits
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _load_card(self, slug: str) -> dict[str, Any]:
        slug = slug.strip()
        cached = self._cache.get(slug)
        if cached:
            return cached
        html = await self._get_html(f"/free_patterns/pattern/{slug}")
        cards = parse_cards(html)
        if cards:
            self._remember(cards[0])
            return cards[0]
        # Detail heading has no pattern <a>; parse the page as a single card.
        fallback = parse_cards(html.replace("&nbsp;Back", "").replace("‹Back", ""))
        if fallback:
            fallback[0]["slug"] = slug
            self._remember(fallback[0])
            return fallback[0]
        # Last resort: extract id from the whole page.
        ids = _ID_RE.findall(html)
        if not ids:
            raise KeyError(slug)
        og = re.search(r'property="og:title"\s+content="([^"]+)"', html, re.IGNORECASE)
        card = {
            "slug": slug,
            "id": ids[0][0],
            "title": _clean(og.group(1)) if og else slug.replace("_", " ").title(),
            "designer": None,
            "category": None,
            "width": None,
            "height": None,
            "thumbnail": None,
            "has_pdf": True,
            "has_pat": any(fmt.upper() == "PAT" for _, fmt in ids),
        }
        self._remember(card)
        return card

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        card = await self._load_card(external_id)
        hit = self._hit(card, craft)
        names = [f"{card['slug']}.pdf"]
        if card.get("has_pat"):
            names.append(f"{card['slug']}.pat")
        return ExternalDetail(
            **hit.model_dump(),
            download_available=True,
            suggested_filename=names[0],
            all_files=names,
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        return await self._load_card(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        card = await self._load_card(external_id)
        pid = card["id"]
        slug = card["slug"]
        pairs = [(f"{BASE}/free_patterns/download/{pid}/PDF", f"{slug}.pdf")]
        if card.get("has_pat"):
            pairs.append((f"{BASE}/free_patterns/download/{pid}/PAT", f"{slug}.pat"))
        return DownloadSpec(url=pairs[0][0], filename=pairs[0][1], all_urls=pairs)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

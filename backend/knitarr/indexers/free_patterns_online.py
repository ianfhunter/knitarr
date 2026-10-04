"""FreePatternsOnline — Carrie's free charts. Live site is Cloudflare-gated; catalog via Wayback."""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse, unquote

import httpx

from knitarr.config import settings
from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities, IndexerStatus, LicenseClass

log = logging.getLogger(__name__)

LIVE = "https://freepatternsonline.com"
INDEX_PATH = "xspatterns2.htm"
WAYBACK = "https://web.archive.org/web/2024"
_CACHE_TTL = 6 * 3600
_DESIGNER = "Carrie Luhmann Pieniozek"

_WB_RE = re.compile(r"https?://web\.archive\.org/web/\d+[a-z_]*/", re.IGNORECASE)
_HREF_RE = re.compile(r"""<a\s+[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.IGNORECASE | re.DOTALL)
_IMG_RE = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
_SKIP_NAMES = frozenset(
    {
        "xspatterns.htm",
        "xspatterns2.htm",
        "messageboard.htm",
        "tools.htm",
        "xslinks.htm",
        "meet.htm",
        "newsletter.htm",
        "finishedxs1.htm",
        "quiltpatterns.htm",
        "quiltlinks.htm",
        "finishedquilt1.htm",
        "freepatterns_privacy.htm",
        "sitemap.htm",
    }
)
_CHART_IMG_HINTS = ("xspats/", "xskeys/", "xscharts/")
_CHART_IMG_SKIP = ("horzad", "dot.gif", "1by1", "facebook", "header", "line2")


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def strip_wayback(url: str) -> str:
    url = _WB_RE.sub("", url or "")
    url = re.sub(r"^https?://(?:www\.)?freepatternsonline\.com/", "", url, flags=re.IGNORECASE)
    return url.split("#", 1)[0].strip()


def _is_nav(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in _SKIP_NAMES or path.lower().startswith(("quilt", "images/", "styles"))


def _abs_path(base_path: str, href: str) -> str | None:
    original = href or ""
    raw = strip_wayback(original)
    if not raw or raw.startswith(("javascript:", "mailto:", "#")):
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        host = urlparse(raw).netloc.lower()
        if "freepatternsonline.com" not in host:
            return None
        return urlparse(raw).path.lstrip("/") or None
    if raw.startswith("/"):
        return raw.lstrip("/") or None
    # Wayback/live absolute hrefs become site paths without a leading slash.
    if original.startswith(("http://", "https://", "/web/")):
        return raw.lstrip("/") or None
    joined = urljoin(f"{LIVE}/{base_path}", raw)
    path = urlparse(joined).path.lstrip("/")
    return path or None


def parse_index(html: str, *, base_path: str = INDEX_PATH) -> tuple[list[dict[str, Any]], list[str]]:
    files: list[dict[str, Any]] = []
    categories: list[str] = []
    seen_files: set[str] = set()
    seen_cats: set[str] = set()
    for href, body in _HREF_RE.findall(html):
        path = _abs_path(base_path, href)
        if not path or _is_nav(path):
            continue
        title = _clean(body)
        lower = path.lower()
        if lower.startswith("xscharts/") and lower.endswith(".htm") and "/page/" not in lower:
            if path not in seen_cats:
                seen_cats.add(path)
                categories.append(path)
            continue
        if lower.endswith((".pdf", ".xsd", ".gif", ".jpg", ".jpeg", ".png")):
            if path in seen_files:
                continue
            seen_files.add(path)
            files.append(
                {
                    "path": path,
                    "title": title or path.rsplit("/", 1)[-1],
                    "category": path.split("/", 1)[0],
                    "files": [path],
                }
            )
    return files, categories


def parse_category(html: str, *, base_path: str, category: str = "") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    cat = category or base_path.rsplit("/", 1)[-1].removesuffix(".htm")
    for href, body in _HREF_RE.findall(html):
        path = _abs_path(base_path, href)
        if not path or _is_nav(path):
            continue
        lower = path.lower()
        if "/page/" not in lower and not lower.endswith((".pdf", ".xsd", ".gif", ".jpg", ".jpeg")):
            continue
        if path in seen:
            continue
        seen.add(path)
        title = _clean(body)
        entries.append(
            {
                "path": path,
                "title": title or path.rsplit("/", 1)[-1],
                "category": cat,
                "files": [path] if not lower.endswith(".htm") else [],
            }
        )
    return entries


def parse_chart_images(html: str, *, base_path: str) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    for src in _IMG_RE.findall(html):
        path = _abs_path(base_path, src)
        if not path:
            continue
        lower = path.lower()
        if any(skip in lower for skip in _CHART_IMG_SKIP):
            continue
        if not any(hint in lower for hint in _CHART_IMG_HINTS):
            continue
        if path in seen:
            continue
        seen.add(path)
        images.append(path)
    return images


def _matches(entry: dict[str, Any], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    hay = " ".join(filter(None, (entry.get("title"), entry.get("category"), entry.get("path")))).lower()
    return all(tok in hay for tok in q.split())


def wayback_original(path_or_url: str) -> str:
    url = path_or_url if path_or_url.startswith("http") else f"{LIVE}/{path_or_url.lstrip('/')}"
    return f"{WAYBACK}id_/{url}"


def live_url(path: str) -> str:
    return f"{LIVE}/{path.lstrip('/')}"


def _filename(path: str) -> str:
    return unquote(path.rsplit("/", 1)[-1]) or "pattern.bin"


class FreePatternsOnlineIndexer:
    id = "free_patterns_online"
    name = "FreePatternsOnline"

    capabilities = IndexerCapabilities(
        source="FreePatternsOnline",
        access_method="scrape",
        authentication="none",
        automated_access_policy=(
            "Live site is Cloudflare-protected; Knitarr reads the public Wayback snapshots "
            "and downloads original chart files into the personal library (no hotlinking)."
        ),
        license_default=LicenseClass.FREE_WITH_RESTRICTIONS,
        can_download=True,
        status=IndexerStatus.ACTIVE,
        site_url=f"{LIVE}/xspatterns.htm",
        description="Free personal-use charts by Carrie Luhmann Pieniozek. Sharing OK; do not sell or kit.",
        search_enabled=True,
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._catalog: list[dict[str, Any]] | None = None
        self._catalog_at = 0.0

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=45.0,
                headers={
                    "User-Agent": settings.ia_user_agent,
                    "Referer": f"{LIVE}/",
                    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _looks_blocked(self, resp: httpx.Response) -> bool:
        if resp.status_code != 200:
            return True
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/html" in ctype and "just a moment" in resp.text.lower():
            return True
        return len(resp.content) < 200

    async def _get_html(self, path: str) -> str:
        client = await self._client_get()
        live = live_url(path)
        async with self._lock:
            try:
                resp = await client.get(live)
                if not self._looks_blocked(resp):
                    await asyncio.sleep(0.2)
                    return resp.text
            except httpx.HTTPError as e:
                log.info("FPO live fetch %s: %s", path, e)
            resp = await client.get(f"{WAYBACK}/{live}")
            resp.raise_for_status()
            await asyncio.sleep(0.25)
            return resp.text

    async def _load_catalog(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._catalog is not None and now - self._catalog_at < _CACHE_TTL:
            return self._catalog
        async with self._lock:
            if self._catalog is not None and time.monotonic() - self._catalog_at < _CACHE_TTL:
                return self._catalog
        html = await self._get_html(INDEX_PATH)
        files, categories = parse_index(html)
        entries = list(files)
        seen = {e["path"] for e in entries}
        for cat_path in categories:
            try:
                cat_html = await self._get_html(cat_path)
            except httpx.HTTPError as e:
                log.info("FPO category %s: %s", cat_path, e)
                continue
            cat_name = cat_path.rsplit("/", 1)[-1].removesuffix(".htm")
            for entry in parse_category(cat_html, base_path=cat_path, category=cat_name):
                if entry["path"] in seen:
                    continue
                seen.add(entry["path"])
                entries.append(entry)
        self._catalog = entries
        self._catalog_at = time.monotonic()
        log.info("FPO catalog: %s entries", len(entries))
        return entries

    def _by_path(self, catalog: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
        path = path.strip().lstrip("/")
        for entry in catalog:
            if entry["path"] == path:
                return entry
        return None

    def _hit(self, entry: dict[str, Any], craft: str) -> ExternalHit:
        path = entry["path"]
        return ExternalHit(
            indexer_id=self.id,
            external_id=path,
            title=entry["title"],
            designer=_DESIGNER,
            description=f"{entry.get('category') or 'chart'} — personal use, do not sell or kit",
            source_url=live_url(path),
            pattern_url=live_url(path),
            craft=craft,
            license_class=LicenseClass.FREE_WITH_RESTRICTIONS,
            redistribution_allowed=False,
            thumbnail_url=None,
            metadata={"path": path, "category": entry.get("category")},
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        if craft != "cross_stitch":
            return []
        hits: list[ExternalHit] = []
        for entry in await self._load_catalog():
            if not _matches(entry, query):
                continue
            hits.append(self._hit(entry, craft))
            if len(hits) >= limit:
                break
        return hits

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return await self.search(tag, limit=limit, craft=craft)

    async def _files_for(self, entry: dict[str, Any]) -> list[str]:
        files = list(entry.get("files") or [])
        if files:
            return files
        path = entry["path"]
        if path.lower().endswith(".htm"):
            html = await self._get_html(path)
            images = parse_chart_images(html, base_path=path)
            entry["files"] = images
            return images
        return [path]

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        entry = self._by_path(await self._load_catalog(), external_id)
        if not entry:
            raise KeyError(external_id)
        files = await self._files_for(entry)
        names = [_filename(p) for p in files]
        hit = self._hit(entry, craft)
        return ExternalDetail(
            **hit.model_dump(),
            download_available=bool(files),
            suggested_filename=names[0] if names else None,
            all_files=names,
        )

    async def get_metadata(self, external_id: str) -> dict[str, Any]:
        entry = self._by_path(await self._load_catalog(), external_id)
        if not entry:
            raise KeyError(external_id)
        return entry

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        entry = self._by_path(await self._load_catalog(), external_id)
        if not entry:
            return None
        files = await self._files_for(entry)
        if not files:
            return None
        pairs = [(wayback_original(p), _filename(p)) for p in files]
        return DownloadSpec(url=pairs[0][0], filename=pairs[0][1], all_urls=pairs)

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

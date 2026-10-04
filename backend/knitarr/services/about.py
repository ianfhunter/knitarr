"""About / version metadata and optional GitHub release checks."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from knitarr import __version__
from knitarr.config import settings

log = logging.getLogger(__name__)

_ABOUT_BLURB = (
    "Knitarr is a self-hosted cross-stitch pattern library — search legitimate sources, "
    "import into a local library, and view or edit charts in the browser."
)


def _parse_semver(raw: str) -> tuple[int, ...]:
    cleaned = raw.strip().lstrip("vV")
    # Strip common prefixes like knitarr-v0.1.0 → 0.1.0
    prefix = (settings.github_release_prefix or "").strip()
    if prefix and cleaned.lower().startswith(prefix.lower()):
        cleaned = cleaned[len(prefix) :]
        cleaned = cleaned.lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:4])


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse_semver(latest) > _parse_semver(current)
    except Exception:
        return False


def _normalize_tag(tag: str) -> str:
    return (tag or "").strip()


async def _fetch_latest_release(repo: str) -> dict[str, Any] | None:
    """Return latest matching GitHub release, or None if unavailable."""
    repo = repo.strip().strip("/")
    if not repo or "/" not in repo:
        return None
    prefix = (settings.github_release_prefix or "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Knitarr/{__version__}",
    }
    url = f"https://api.github.com/repos/{repo}/releases?per_page=20"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            releases = r.json()
            if not isinstance(releases, list):
                return None
            for rel in releases:
                if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
                    continue
                tag = _normalize_tag(str(rel.get("tag_name") or ""))
                if not tag:
                    continue
                if prefix and not tag.lower().startswith(prefix.lower()):
                    continue
                return {
                    "version": tag,
                    "name": rel.get("name") or tag,
                    "url": rel.get("html_url") or f"https://github.com/{repo}/releases/tag/{tag}",
                    "published_at": rel.get("published_at"),
                }
            # Fallback: unprefixed latest release when prefix filtered everything out.
            if prefix:
                for rel in releases:
                    if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
                        continue
                    tag = _normalize_tag(str(rel.get("tag_name") or ""))
                    if tag:
                        return {
                            "version": tag,
                            "name": rel.get("name") or tag,
                            "url": rel.get("html_url")
                            or f"https://github.com/{repo}/releases/tag/{tag}",
                            "published_at": rel.get("published_at"),
                            "note": f"No release matched prefix “{prefix}”; showing latest repo release.",
                        }
    except Exception as e:
        log.info("GitHub release check failed for %s: %s", repo, e)
        return None
    return None


async def about_info() -> dict[str, Any]:
    current = __version__
    info: dict[str, Any] = {
        "name": "Knitarr",
        "version": current,
        "description": _ABOUT_BLURB,
        "github_repo": settings.github_repo or None,
        "update_available": False,
        "latest": None,
        "release_check": "ok",
    }
    repo = (settings.github_repo or "").strip()
    if not repo:
        info["release_check"] = "unconfigured"
        return info
    latest = await _fetch_latest_release(repo)
    if latest is None:
        info["release_check"] = "unavailable"
        return info
    info["latest"] = latest
    info["update_available"] = _is_newer(str(latest.get("version") or ""), current)
    return info

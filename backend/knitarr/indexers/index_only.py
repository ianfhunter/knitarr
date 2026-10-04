"""Catalog indexers with no automated search/download (links + metadata only)."""

from __future__ import annotations

from knitarr.models import (
    DownloadSpec,
    ExternalDetail,
    ExternalHit,
    IndexerCapabilities,
    IndexerStatus,
    LicenseClass,
)


class IndexOnlyIndexer:
    """Listed in Indexers UI; no API integration yet."""

    def __init__(
        self,
        *,
        id: str,
        name: str,
        source: str,
        site_url: str,
        description: str,
        status: IndexerStatus = IndexerStatus.INDEX_ONLY,
        access_method: str = "manual",
    ) -> None:
        self.id = id
        self.name = name
        self.site_url = site_url
        self.capabilities = IndexerCapabilities(
            source=source,
            access_method=access_method,
            authentication="none",
            automated_access_policy="No automated access; browse the site and import files you own.",
            license_default=LicenseClass.UNKNOWN,
            can_download=False,
            status=status,
            site_url=site_url,
            description=description,
            search_enabled=False,
        )

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return []

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]:
        return []

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail:
        raise KeyError(external_id)

    async def get_metadata(self, external_id: str) -> dict:
        raise KeyError(external_id)

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None:
        return None

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict:
        return {"changed": False}

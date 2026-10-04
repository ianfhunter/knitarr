from typing import Protocol, runtime_checkable

from knitarr.models import DownloadSpec, ExternalDetail, ExternalHit, IndexerCapabilities


@runtime_checkable
class Indexer(Protocol):
    id: str
    name: str
    capabilities: IndexerCapabilities

    async def search(self, query: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]: ...

    async def search_by_tag(self, tag: str, *, limit: int = 50, craft: str = "cross_stitch") -> list[ExternalHit]: ...

    async def get_pattern(self, external_id: str, *, craft: str = "cross_stitch") -> ExternalDetail: ...

    async def get_metadata(self, external_id: str) -> dict: ...

    async def get_download(self, external_id: str, *, craft: str = "cross_stitch") -> DownloadSpec | None: ...

    async def check_updates(self, external_id: str, known_etag: str | None) -> dict: ...

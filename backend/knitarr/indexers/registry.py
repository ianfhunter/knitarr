from knitarr.indexers.base import Indexer
from knitarr.indexers.internet_archive import InternetArchiveIndexer

_indexers: dict[str, Indexer] = {}


def register_indexer(indexer: Indexer) -> None:
    _indexers[indexer.id] = indexer


def get_indexer(indexer_id: str) -> Indexer:
    if indexer_id not in _indexers:
        raise KeyError(f"Unknown indexer: {indexer_id}")
    return _indexers[indexer_id]


def list_indexers() -> list[Indexer]:
    return list(_indexers.values())


def bootstrap_indexers() -> None:
    register_indexer(InternetArchiveIndexer())


async def shutdown_indexers() -> None:
    for idx in _indexers.values():
        if hasattr(idx, "close"):
            await idx.close()

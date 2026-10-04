"""Merge multi-indexer search hits without one source dominating the limit."""

from __future__ import annotations

from knitarr.models import ExternalHit


def fair_merge_hits(lists: list[list[ExternalHit]], limit: int) -> list[ExternalHit]:
    """Round-robin across indexers so each source can appear in combined results."""
    merged: list[ExternalHit] = []
    round_idx = 0
    while len(merged) < limit:
        added = False
        for hits in lists:
            if round_idx < len(hits):
                merged.append(hits[round_idx])
                added = True
                if len(merged) >= limit:
                    break
        if not added:
            break
        round_idx += 1
    return merged

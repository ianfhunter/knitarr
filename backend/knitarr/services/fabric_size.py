"""Fabric cut size from the Thread-Bare calculator approach.

stitched_inches = stitches / fabric_count
fabric_inches = stitched_inches + 2 * border_inches
"""

from __future__ import annotations


def stitched_inches(stitches: int, fabric_count: int) -> float:
    count = max(1, int(fabric_count))
    return max(0, int(stitches)) / count


def fabric_inches(stitches: int, *, fabric_count: int, border_inches: float = 3.0) -> float:
    return stitched_inches(stitches, fabric_count) + 2.0 * max(0.0, float(border_inches))

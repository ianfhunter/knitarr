"""Skein estimates from the mismatch.co.uk / Kathleen Dyer floss-amount formula.

stitches_per_skein = 17 * (15 / (6/count)) * (6/strands)
                  = 255 * count / strands

Assumes ~8.5 yd (~8 m) skeins, 18" working lengths, 3" waste, and ~6/count inches of
thread per full cross (including back travel). Guide only.
"""

from __future__ import annotations

import math


def stitches_per_skein(*, fabric_count: int, strands: int) -> float:
    count = max(1, int(fabric_count))
    used = max(1, min(6, int(strands)))
    return 255.0 * count / used


def skeins_needed(stitch_count: int | float, *, fabric_count: int, strands: int) -> float:
    stitches = max(0.0, float(stitch_count))
    if stitches <= 0:
        return 0.0
    per = stitches_per_skein(fabric_count=fabric_count, strands=strands)
    if per <= 0:
        return 0.0
    return stitches / per


def skeins_to_buy(stitch_count: int | float, *, fabric_count: int, strands: int) -> int:
    needed = skeins_needed(stitch_count, fabric_count=fabric_count, strands=strands)
    if needed <= 0:
        return 0
    return max(1, int(math.ceil(needed - 1e-9)))

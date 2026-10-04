"""Symbol marks for chart export — mirrors frontend symbol modes."""

from __future__ import annotations

from typing import Any

SYMBOL_SET = (
    "■□▲△▼▽◆◇●○★☆♠♥♦♣$€£¥¢§†‡¶※#@&%+×÷=¤⊕⊗•◦▬▪▫◐◑✚✕▣▤▥▦▧▨▩◊⊞⊟⊠"
)
ALT_SYMBOL_SET = (
    "ΑΒΓΔΘΛΞΠΣΦΨΩαβγδεθλσφω←↑→↓↔↕±∞√∑∏∂∇∫≈≠≤≥☀☁☂☎☑☒♪♫☺☼♀♂☾⚡⚓⚙❖❋✳✴"
)
VALID_SYMBOL_MODES = frozenset({"none", "alphabet", "numbers", "symbols", "alt"})


def normalize_symbol_mode(raw: str | None) -> str:
    mode = (raw or "").strip().lower()
    return mode if mode in VALID_SYMBOL_MODES else "symbols"


def _pe_index(pe: Any) -> int:
    if isinstance(pe, dict):
        return int(pe.get("index") or 0)
    return int(getattr(pe, "index", 0) or 0)


def palette_order_index(palette: list[Any], palindex: int) -> int:
    used = sorted((pe for pe in palette if _pe_index(pe) > 0), key=_pe_index)
    for i, pe in enumerate(used):
        if _pe_index(pe) == palindex:
            return i
    return -1


def symbol_for_palette(palette: list[Any], palindex: int, mode: str | None) -> str:
    mode = normalize_symbol_mode(mode)
    if mode == "none" or palindex <= 0:
        return ""
    order = palette_order_index(palette, palindex)
    if order < 0:
        return ""
    if mode == "alphabet":
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        if order < len(letters):
            return letters[order]
        return f"{letters[order % 26]}{order // 26}"
    if mode == "numbers":
        return str(order + 1)
    charset = SYMBOL_SET if mode == "symbols" else ALT_SYMBOL_SET
    return charset[order % len(charset)] or str(order + 1)


def build_symbol_map(palette: list[Any], mode: str | None) -> dict[int, str]:
    out: dict[int, str] = {}
    for pe in palette:
        idx = _pe_index(pe)
        if idx <= 0:
            continue
        out[idx] = symbol_for_palette(palette, idx, mode)
    return out

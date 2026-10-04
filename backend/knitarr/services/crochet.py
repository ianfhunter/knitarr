"""Crochet wrappers around the shared yarn instruction/supplies service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knitarr.services import yarn_pattern as yp

CROCHET_FILENAME = yp.pattern_filename("crochet")


def crochet_path(pattern_id: int) -> Path:
    return yp.yarn_path(pattern_id, "crochet")


def empty_supplies(*, terminology: str = "US") -> dict[str, str]:
    return yp.empty_supplies(terminology=terminology)


def normalize_supplies(raw: Any) -> dict[str, str]:
    return yp.normalize_supplies(raw)


def empty_document(*, title: str = "Untitled", dialect: str = "US") -> dict[str, Any]:
    return yp.empty_document("crochet", title=title, dialect=dialect)


def load_crochet(pattern_id: int) -> dict[str, Any] | None:
    return yp.load_document(pattern_id, "crochet")


def save_crochet(pattern_id: int, doc: dict[str, Any]) -> dict[str, Any]:
    return yp.save_document(pattern_id, "crochet", doc)


def pdf_raw_text(pdf_path: Path) -> str:
    return yp.pdf_raw_text(pdf_path)


def extract_supplies_from_text(text: str) -> dict[str, str]:
    return yp.extract_supplies_from_text(text, craft="crochet")


def extract_pdf_lines(pdf_path: Path) -> tuple[list[str], list[str]]:
    return yp.extract_pdf_lines(pdf_path)


def extract_from_pdf(pattern_id: int) -> dict[str, Any]:
    return yp.extract_from_pdf(pattern_id)


def get_or_extract(pattern_id: int) -> dict[str, Any]:
    return yp.get_or_extract(pattern_id)

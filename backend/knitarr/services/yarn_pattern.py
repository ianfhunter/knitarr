"""Shared instruction-line + supplies helpers for crochet and knitting patterns."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import fitz

from knitarr.config import settings
from knitarr.db import get_conn

YARN_CRAFTS = frozenset({"crochet", "knitting"})

_CRAFT_META = {
    "crochet": {
        "filename": "crochet.json",
        "format": "knitarr_crochet_v1",
    },
    "knitting": {
        "filename": "knitting.json",
        "format": "knitarr_knitting_v1",
    },
}

_LINE_START = re.compile(
    r"^(?:"
    r"rounds?\s*\d+"
    r"|rnds?\s*\d+"
    r"|rows?\s*\d+"
    r"|r\s*\d+"
    r"|step\s*\d+"
    r"|\d+\s*[.:)]"
    r"|\*"
    r")",
    re.IGNORECASE,
)

_ROUND_HEAD = re.compile(
    r"^(?:round|rnd|row|r)\s*(\d+)\s*[:.\-)]?\s*(.*)$",
    re.IGNORECASE,
)


def assert_yarn_craft(craft: str) -> str:
    craft = (craft or "").strip()
    if craft not in YARN_CRAFTS:
        raise ValueError("Instruction editor is only available for crochet and knitting")
    return craft


def pattern_filename(craft: str) -> str:
    return _CRAFT_META[assert_yarn_craft(craft)]["filename"]


def pattern_format(craft: str) -> str:
    return _CRAFT_META[assert_yarn_craft(craft)]["format"]


def yarn_path(pattern_id: int, craft: str) -> Path:
    return settings.library_dir / str(pattern_id) / pattern_filename(craft)


def empty_supplies(*, terminology: str = "US") -> dict[str, str]:
    term = terminology if terminology in {"US", "UK", "unknown"} else "US"
    return {
        "terminology": term,
        "hook_size": "",
        "needle_size": "",
        "yarn": "",
        "yarn_amount": "",
        "gauge": "",
        "notions": "",
        "notes": "",
    }


def normalize_supplies(raw: Any) -> dict[str, str]:
    base = empty_supplies()
    if not isinstance(raw, dict):
        return base
    for key in base:
        val = raw.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if key == "terminology":
            upper = text.upper()
            if upper in {"US", "UK"}:
                base[key] = upper
            elif text.lower() == "unknown":
                base[key] = "unknown"
            else:
                base[key] = "US"
        else:
            base[key] = text[:500]
    return base


def empty_document(
    craft: str,
    *,
    title: str = "Untitled",
    dialect: str = "US",
) -> dict[str, Any]:
    craft = assert_yarn_craft(craft)
    supplies = empty_supplies(terminology=dialect if dialect in {"US", "UK"} else "US")
    return {
        "format": pattern_format(craft),
        "craft": craft,
        "title": title,
        "dialect": supplies["terminology"],
        "lines": [],
        "supplies": supplies,
        "warnings": [],
    }


def load_document(pattern_id: int, craft: str) -> dict[str, Any] | None:
    craft = assert_yarn_craft(craft)
    path = yarn_path(pattern_id, craft)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("format", pattern_format(craft))
    data.setdefault("craft", craft)
    data.setdefault("lines", [])
    data.setdefault("warnings", [])
    supplies = normalize_supplies(data.get("supplies"))
    if not data.get("supplies") and data.get("dialect") in {"US", "UK"}:
        supplies["terminology"] = str(data["dialect"])
    data["supplies"] = supplies
    data["dialect"] = supplies["terminology"]
    return data


def save_document(pattern_id: int, craft: str, doc: dict[str, Any]) -> dict[str, Any]:
    craft = assert_yarn_craft(craft)
    path = yarn_path(pattern_id, craft)
    path.parent.mkdir(parents=True, exist_ok=True)
    supplies = normalize_supplies(doc.get("supplies"))
    if doc.get("dialect") in {"US", "UK"} and not (doc.get("supplies") or {}).get("terminology"):
        supplies["terminology"] = str(doc["dialect"])
    lines = [str(ln).strip() for ln in (doc.get("lines") or []) if str(ln).strip()]
    out = {
        "format": pattern_format(craft),
        "craft": craft,
        "title": str(doc.get("title") or "Untitled"),
        "dialect": supplies["terminology"],
        "lines": lines,
        "supplies": supplies,
        "warnings": [str(w) for w in (doc.get("warnings") or []) if str(w).strip()],
    }
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def _primary_pdf(pattern_id: int) -> Path | None:
    lib = settings.library_dir / str(pattern_id)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT path, filename, mime_type FROM pattern_files
            WHERE pattern_id = ? ORDER BY id
            """,
            (pattern_id,),
        ).fetchall()
    for row in rows:
        name = (row["filename"] or "").lower()
        mime = (row["mime_type"] or "").lower()
        if name.endswith(".pdf") or mime == "application/pdf":
            p = Path(row["path"]) if row["path"] else lib / row["filename"]
            if p.is_file():
                return p
    for p in sorted(lib.glob("*.pdf")):
        if p.is_file():
            return p
    return None


def pdf_raw_text(pdf_path: Path) -> str:
    chunks: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text") or ""
            if text.strip():
                chunks.append(text)
    return "\n".join(chunks)


def extract_supplies_from_text(text: str, *, craft: str = "crochet") -> dict[str, str]:
    """Best-effort supplies fields from pattern prose."""
    craft = assert_yarn_craft(craft)
    supplies = empty_supplies(terminology="unknown")
    if not (text or "").strip():
        return supplies
    blob = text.replace("\u00ad", "")

    if re.search(r"\bUK\s+terms?\b|\bBritish\s+terms?\b", blob, re.IGNORECASE):
        supplies["terminology"] = "UK"
    elif re.search(r"\bUS\s+terms?\b|\bAmerican\s+terms?\b", blob, re.IGNORECASE):
        supplies["terminology"] = "US"

    hook = re.search(
        r"(?:crochet\s+)?hook(?:\s*size)?\s*[:\-]?\s*"
        r"((?:\d+(?:\.\d+)?\s*mm)|(?:[A-K]/?\d{0,2})|(?:\d+\s*/\s*\d+\s*mm))",
        blob,
        re.IGNORECASE,
    )
    if not hook:
        hook = re.search(r"\b(\d+(?:\.\d+)?\s*mm)\s*(?:crochet\s+)?hook\b", blob, re.IGNORECASE)
    if hook:
        supplies["hook_size"] = re.sub(r"\s+", " ", hook.group(1)).strip()

    needle = re.search(
        r"(?:knitting\s+)?needles?(?:\s*size)?\s*[:\-]?\s*"
        r"((?:\d+(?:\.\d+)?\s*mm)|(?:US\s*\d+(?:\s*/\s*\d+(?:\.\d+)?\s*mm)?)|"
        r"(?:size\s+[A-Z0-9/.\s-]{1,20}))",
        blob,
        re.IGNORECASE,
    )
    if not needle:
        needle = re.search(
            r"\b((?:\d+(?:\.\d+)?\s*mm)|(?:US\s*\d+))\s*(?:circular\s+|dpn\s+|straight\s+)?needles?\b",
            blob,
            re.IGNORECASE,
        )
    if needle:
        supplies["needle_size"] = re.sub(r"\s+", " ", needle.group(1)).strip(" .;")

    yarn = re.search(
        r"(?:yarn|wool)\s*[:\-]\s*([^\n.]{3,80})",
        blob,
        re.IGNORECASE,
    )
    if yarn:
        supplies["yarn"] = yarn.group(1).strip(" .;,-")
    else:
        weight = re.search(
            r"\b((?:lace|fingering|sock|sport|dk|light\s*worsted|worsted|aran|chunky|bulky|super\s*bulky)"
            r"(?:\s*weight)?(?:\s*yarn)?)\b",
            blob,
            re.IGNORECASE,
        )
        if weight:
            supplies["yarn"] = weight.group(1).strip()

    amount = re.search(
        r"\b(\d+(?:\.\d+)?\s*(?:g|grams?|oz|skeins?|balls?|yards?|yds?|meters?|metres?|m)\b"
        r"(?:[^.\n]{0,40})?)",
        blob,
        re.IGNORECASE,
    )
    if amount:
        supplies["yarn_amount"] = re.sub(r"\s+", " ", amount.group(1)).strip(" .;")

    gauge = re.search(
        r"(?:gauge|tension)\s*[:\-]?\s*([^\n]{3,100})",
        blob,
        re.IGNORECASE,
    )
    if gauge:
        supplies["gauge"] = gauge.group(1).strip(" .;")

    notions = re.search(
        r"(?:notions?|you(?:'ll| will)\s+also\s+need)\s*[:\-]?\s*([^\n]{3,140})",
        blob,
        re.IGNORECASE,
    )
    if notions:
        supplies["notions"] = notions.group(1).strip(" .;")

    # Prefer craft-appropriate tool; leave the other blank unless both were explicit.
    if craft == "knitting" and supplies["needle_size"] and not re.search(r"\bhook\b", blob, re.I):
        supplies["hook_size"] = ""
    if craft == "crochet" and supplies["hook_size"] and not re.search(r"\bneedles?\b", blob, re.I):
        supplies["needle_size"] = ""

    return supplies


def extract_pdf_lines(pdf_path: Path) -> tuple[list[str], list[str]]:
    """Return (instruction_lines, warnings) from a digital PDF text layer."""
    warnings: list[str] = []
    combined = pdf_raw_text(pdf_path)
    if not combined.strip():
        return [], [
            "No extractable text layer found. This PDF may be scanned — paste instructions manually."
        ]

    combined = combined.replace("\u00ad", "").replace("\r\n", "\n").replace("\r", "\n")
    rough = [ln.strip() for ln in combined.split("\n") if ln.strip()]

    junk = re.compile(
        r"^(page\s*\d+|©|copyright|all rights reserved|www\.|http)\b",
        re.IGNORECASE,
    )
    materials_head = re.compile(
        r"^(materials?|yarn|wool|hook|needles?|gauge|tension|abbreviations?|notions?)\b",
        re.IGNORECASE,
    )
    filtered = [ln for ln in rough if not junk.match(ln) and len(ln) > 1]

    lines: list[str] = []
    for ln in filtered:
        if materials_head.match(ln) and not _LINE_START.match(ln) and not _ROUND_HEAD.match(ln):
            continue
        if not lines:
            lines.append(ln)
            continue
        if _LINE_START.match(ln) or _ROUND_HEAD.match(ln):
            lines.append(ln)
        elif lines[-1].endswith((",", ";", ":", "-", "–", "*")):
            if len(ln) < 120:
                lines[-1] = f"{lines[-1]} {ln}".strip()
            else:
                lines.append(ln)
        else:
            lines.append(ln)

    preferred = [
        ln for ln in lines if _ROUND_HEAD.match(ln) or _LINE_START.match(ln) or "*" in ln
    ]
    if len(preferred) >= 3:
        lines = preferred
    elif not lines:
        warnings.append("Could not find instruction-like lines; showing raw extracted text.")
        lines = [ln for ln in rough if not junk.match(ln)][:200]
    else:
        warnings.append(
            "Few round/row markers found — showing extracted lines. Edit as needed."
        )

    if len(lines) > 400:
        warnings.append(f"Truncated to 400 lines (had {len(lines)}).")
        lines = lines[:400]
    return lines, warnings


def _pattern_craft(pattern_id: int) -> tuple[Any, str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, craft FROM patterns WHERE id = ?", (pattern_id,)
        ).fetchone()
    if not row:
        raise KeyError(pattern_id)
    craft = assert_yarn_craft(row["craft"])
    return row, craft


def extract_from_pdf(pattern_id: int) -> dict[str, Any]:
    row, craft = _pattern_craft(pattern_id)
    existing = load_document(pattern_id, craft) or empty_document(
        craft, title=row["title"] or "Untitled"
    )
    pdf = _primary_pdf(pattern_id)
    if not pdf:
        doc = empty_document(craft, title=row["title"] or "Untitled")
        doc["supplies"] = existing.get("supplies") or empty_supplies()
        doc["warnings"] = ["No PDF found — add instruction lines and supplies manually."]
        return save_document(pattern_id, craft, doc)

    lines, warnings = extract_pdf_lines(pdf)
    raw = pdf_raw_text(pdf)
    supplies = extract_supplies_from_text(raw, craft=craft)
    prev = normalize_supplies(existing.get("supplies"))
    for key, val in supplies.items():
        if not val and prev.get(key):
            supplies[key] = prev[key]

    doc = {
        "title": row["title"] or "Untitled",
        "dialect": supplies["terminology"],
        "lines": lines,
        "supplies": supplies,
        "warnings": warnings,
    }
    return save_document(pattern_id, craft, doc)


def get_or_extract(pattern_id: int) -> dict[str, Any]:
    row, craft = _pattern_craft(pattern_id)
    existing = load_document(pattern_id, craft)
    if existing is not None:
        return existing
    _ = row
    return extract_from_pdf(pattern_id)

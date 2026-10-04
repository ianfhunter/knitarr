from pathlib import Path

import fitz

from knitarr.services.crochet import (
    extract_pdf_lines,
    extract_supplies_from_text,
    normalize_supplies,
    save_crochet,
)
from knitarr.services import yarn_pattern as yarn_svc


def test_extract_supplies_from_text():
    text = """
    Cute Bear
    Materials
    Yarn: DK weight cotton
    Hook size: 3.5 mm
    You will also need: stitch markers, tapestry needle
    Gauge: 20 sc = 10 cm
    Pattern uses US terms.
    100g / 2 skeins needed
    Rnd 1: 6 sc in mr (6)
    """
    supplies = extract_supplies_from_text(text)
    assert supplies["terminology"] == "US"
    assert "3.5" in supplies["hook_size"]
    assert "DK" in supplies["yarn"] or "dk" in supplies["yarn"].lower()
    assert supplies["yarn_amount"]
    assert supplies["gauge"]
    assert "stitch markers" in supplies["notions"].lower()


def test_extract_supplies_uk_terms():
    supplies = extract_supplies_from_text("This pattern is written in UK terms. Use a 4mm hook.")
    assert supplies["terminology"] == "UK"
    assert "4" in supplies["hook_size"]


def test_normalize_supplies_defaults():
    assert normalize_supplies(None)["terminology"] == "US"
    assert normalize_supplies({"terminology": "uk", "hook_size": " G "})["terminology"] == "UK"
    assert normalize_supplies({"terminology": "uk", "hook_size": " G "})["hook_size"] == "G"


def test_extract_pdf_lines(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Rnd 1: 6 sc in mr (6)\nRnd 2: 6 inc (12)\nMaterials: worsted yarn\n",
        fontsize=11,
    )
    doc.save(pdf)
    doc.close()
    lines, warnings = extract_pdf_lines(pdf)
    assert any("Rnd 1" in ln or "rnd 1" in ln.lower() for ln in lines)
    assert any("Rnd 2" in ln or "rnd 2" in ln.lower() for ln in lines)


def test_save_crochet_keeps_supplies(tmp_path: Path, monkeypatch):
    from knitarr.config import settings

    monkeypatch.setattr(settings, "library_dir", tmp_path)
    out = save_crochet(
        1,
        {
            "title": "Hat",
            "lines": ["Rnd 1: 6 sc (6)", "Rnd 2: 6 inc (12)"],
            "supplies": {
                "terminology": "UK",
                "hook_size": "4 mm",
                "needle_size": "",
                "yarn": "DK",
                "yarn_amount": "50g",
                "gauge": "",
                "notions": "",
                "notes": "soft",
            },
        },
    )
    assert out["lines"] == ["Rnd 1: 6 sc (6)", "Rnd 2: 6 inc (12)"]
    assert out["supplies"]["terminology"] == "UK"
    assert out["supplies"]["hook_size"] == "4 mm"
    assert out["dialect"] == "UK"
    assert "mesh" not in out


def test_knitting_supplies_extract_needles():
    text = """
    Cosy Scarf
    Needles: 4.5 mm
    Yarn: Aran wool
    UK terms
    Cast on 40 sts
    Row 1: k1, p1 across
    """
    supplies = yarn_svc.extract_supplies_from_text(text, craft="knitting")
    assert supplies["terminology"] == "UK"
    assert "4.5" in supplies["needle_size"]
    assert supplies["hook_size"] == ""
    assert "Aran" in supplies["yarn"] or "aran" in supplies["yarn"].lower()


def test_save_knitting_document(tmp_path: Path, monkeypatch):
    from knitarr.config import settings

    monkeypatch.setattr(settings, "library_dir", tmp_path)
    out = yarn_svc.save_document(
        2,
        "knitting",
        {
            "title": "Scarf",
            "lines": ["Cast on 40", "Row 1: knit"],
            "supplies": {
                "terminology": "US",
                "hook_size": "",
                "needle_size": "5 mm",
                "yarn": "worsted",
                "yarn_amount": "200g",
                "gauge": "",
                "notions": "",
                "notes": "",
            },
        },
    )
    assert out["format"] == "knitarr_knitting_v1"
    assert out["craft"] == "knitting"
    assert out["supplies"]["needle_size"] == "5 mm"
    assert (tmp_path / "2" / "knitting.json").is_file()

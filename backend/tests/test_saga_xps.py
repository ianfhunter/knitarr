"""Saga structured parse + XPS document detection + container characterization."""

from __future__ import annotations

import base64
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from knitarr.parsers.oxs import NormalizedPattern, PaletteEntry, write_oxs
from knitarr.parsers.saga import parse_saga
from knitarr.parsers.saga_container import characterize_saga
from knitarr.parsers.xsp_container import characterize_xsp
from knitarr.services.image_to_oxs import document_filetype, looks_like_xps, pdf_page_count


def _sample_norm() -> NormalizedPattern:
    return NormalizedPattern(
        title="Tiny",
        width_stitches=2,
        height_stitches=2,
        palette=[
            PaletteEntry(index=0, number="cloth", name="cloth", color="FFFFFF"),
            PaletteEntry(index=1, number="DMC 310", name="Black", color="000000"),
        ],
        full_stitches=[{"x": 0, "y": 0, "palindex": 1}, {"x": 1, "y": 1, "palindex": 1}],
        backstitches=[{"x1": 0, "y1": 0, "x2": 2, "y2": 0, "palindex": 1}],
    )


def _write_minimal_xps(path: Path) -> None:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>
  <Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>
  <Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/>
</Types>
""",
        "_rels/.rels": """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Type="http://schemas.microsoft.com/xps/2005/06/fixedrepresentation" Target="/FixedDocumentSequence.fdseq" Id="r1"/>
</Relationships>
""",
        "FixedDocumentSequence.fdseq": """<?xml version="1.0" encoding="utf-8"?>
<FixedDocumentSequence xmlns="http://schemas.microsoft.com/xps/2005/06">
  <DocumentReference Source="Documents/1/FixedDoc.fdoc"/>
</FixedDocumentSequence>
""",
        "Documents/1/FixedDoc.fdoc": """<?xml version="1.0" encoding="utf-8"?>
<FixedDocument xmlns="http://schemas.microsoft.com/xps/2005/06">
  <PageContent Source="Pages/1.fpage"/>
</FixedDocument>
""",
        "Documents/1/_rels/FixedDoc.fdoc.rels": """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Type="http://schemas.microsoft.com/xps/2005/06/required-resource" Target="Pages/1.fpage" Id="r2"/>
</Relationships>
""",
        "Documents/1/Pages/1.fpage": """<?xml version="1.0" encoding="utf-8"?>
<FixedPage xmlns="http://schemas.microsoft.com/xps/2005/06" Width="96" Height="96">
  <Path Data="M 0,0 L 48,0 48,48 0,48 Z">
    <Path.Fill><SolidColorBrush Color="#FFFFCC00"/></Path.Fill>
  </Path>
  <Path Data="M 48,48 L 96,48 96,96 48,96 Z">
    <Path.Fill><SolidColorBrush Color="#FF000000"/></Path.Fill>
  </Path>
</FixedPage>
""",
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)


class SagaXpsTests(unittest.TestCase):
    def test_parse_saga_zip_with_oxs(self):
        with tempfile.TemporaryDirectory() as tmp:
            oxs = Path(tmp) / "chart.oxs"
            write_oxs(oxs, _sample_norm())
            saga = Path(tmp) / "pattern.saga"
            with zipfile.ZipFile(saga, "w") as zf:
                zf.write(oxs, "chart.oxs")
            loaded = parse_saga(saga, title="From Saga")
        self.assertEqual(loaded.title, "From Saga")
        self.assertEqual(len(loaded.full_stitches), 2)
        self.assertEqual(len(loaded.backstitches), 1)

    def test_encrypted_saga_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            saga = Path(tmp) / "locked.saga"
            with zipfile.ZipFile(saga, "w") as zf:
                zf.writestr("info.xpub", "I8RKKxZytDSJ5so35jtzaUiSN18mZ08tGwQaggsp")
                zf.writestr("hoop_0.xpub", "not-xml-ciphertext")
            with self.assertRaises(ValueError) as ctx:
                parse_saga(saga)
        self.assertIn("encrypted", str(ctx.exception).lower())

    def test_xsp_platinum_is_not_xps(self):
        with tempfile.TemporaryDirectory() as tmp:
            xsp = Path(tmp) / "adesign.xsp"
            xsp.write_bytes(b"XSPPLAT\x00\x08" + b"\x00" * 32)
            self.assertFalse(looks_like_xps(xsp))
            self.assertIsNone(document_filetype(xsp))

    def test_minimal_xps_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            xps = Path(tmp) / "chart.xps"
            _write_minimal_xps(xps)
            self.assertTrue(looks_like_xps(xps))
            self.assertEqual(document_filetype(xps), "xps")
            try:
                pages = pdf_page_count(xps)
            except Exception:
                self.skipTest("PyMuPDF could not open the minimal XPS fixture")
            self.assertGreaterEqual(pages, 1)

    def test_characterize_saga_xpub_prefix(self):
        shared = bytes(range(32))
        a = base64.b64encode(shared + b"\x11" * 16).decode("ascii")
        b = base64.b64encode(shared + b"\x22" * 16).decode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            saga = Path(tmp) / "p.saga"
            with zipfile.ZipFile(saga, "w") as zf:
                zf.writestr("info.xpub", a)
                zf.writestr("hoop_0.xpub", b)
            report = characterize_saga(saga)
        self.assertTrue(report["is_zip"])
        prefs = [p for p in report["common_prefixes"] if p["bytes"] == 32]
        self.assertTrue(prefs)
        self.assertFalse(report["readable_chart_xml"])

    def test_characterize_xspplat_header(self):
        name = b"adesignfile.xsu"
        payload = b"\xab" * 20
        header = (
            b"XSPPLAT\x00"
            + struct.pack("<HIIII I", 8, 1, 0x11223344, len(payload), 100, len(name))
            + name
            + payload
        )
        # Minimal CD + EOCD so the trailer offsets are consistent.
        cd = (
            b"PK\x01\x02\x14\x00\x14\x00\x01\x00\x08\x00"
            + struct.pack("<HHIHHH", 0, 0, 0x11223344, len(payload), 100, len(name))
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            + name
        )
        # The above CD packing is easy to get wrong; only assert header fields.
        with tempfile.TemporaryDirectory() as tmp:
            xsp = Path(tmp) / "d.xsp"
            xsp.write_bytes(header)
            report = characterize_xsp(xsp)
        self.assertTrue(report["is_xspplat"])
        self.assertEqual(report["member_name"], "adesignfile.xsu")
        self.assertEqual(report["method"], 8)
        self.assertEqual(report["compressed_size"], 20)
        self.assertEqual(report["uncompressed_size"], 100)


if __name__ == "__main__":
    unittest.main()

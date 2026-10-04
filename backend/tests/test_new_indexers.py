"""Parser tests for Antique Pattern Library, Cross Stitch Quest, Wizardi, and new sources."""

from __future__ import annotations

import unittest

from knitarr.indexers.antique_pattern_library import parse_catalog
from knitarr.indexers.cross_stitch_com import design_to_fields
from knitarr.indexers.cross_stitch_quest import _is_patreon_only, pick_pattern_files
from knitarr.indexers.cyberstitchers import parse_cards, parse_page_counts, search_path
from knitarr.indexers.free_patterns_online import (
    parse_category,
    parse_chart_images,
    parse_index,
    strip_wayback,
    wayback_original,
)
from knitarr.indexers.wizardi import _matches, product_to_fields


_APL_SNIPPET = """
<table>
<tr class="odd">
<td> <a name="6-AK015" />
 <img width="100" src="../../pub/Thumbnails/6-AK015Nichols.t.png" alt="x"></td>
<td> <a class="inline" href="../../pub/PDF/6-AK015Nichols.pdf" target="_blank">&nbsp;PDF&nbsp;</a></td>
<td>
<P class="author">  Nichols, Mrs. P.W., et al.</P>
<P class="title">   Homemade Gifts in Variety,</P>
</td>
<td>
<P class="descr">   Needlecraft magazine, directions for small gifts.</P>
</td>
<td>
<P class="code_">   6-AK015</P>
</td>
</tr>
</table>
"""


class NewIndexerParseTests(unittest.TestCase):
    def test_apl_parses_catalog_row(self):
        entries = parse_catalog(_APL_SNIPPET)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["code"], "6-AK015")
        self.assertEqual(e["title"], "Homemade Gifts in Variety")
        self.assertIn("Nichols", e["author"])
        self.assertTrue(e["pdfs"][0].endswith("/pub/PDF/6-AK015Nichols.pdf"))
        self.assertIn("Thumbnails/6-AK015Nichols.t.png", e["thumbnail"])

    def test_csq_skips_patreon_and_picks_pdf(self):
        self.assertTrue(_is_patreon_only("Patreon Only Connie Cross Stitch Pattern"))
        self.assertFalse(_is_patreon_only("Free Tiny Zubat Cross Stitch Pattern"))
        post = {
            "attachments": {
                "1": {
                    "URL": "https://example.com/zubat-tiny-preview.png",
                    "title": "Zubat Tiny Preview",
                    "mime_type": "image/png",
                },
                "2": {
                    "URL": "https://example.com/zubat-tiny-pattern.pdf",
                    "title": "Zubat Tiny Pattern",
                    "mime_type": "application/pdf",
                },
            }
        }
        files = pick_pattern_files(post)
        self.assertEqual(files[0][1], "zubat-tiny-pattern.pdf")

    def test_wizardi_matches_vendor_and_title(self):
        product = {
            "handle": "owl-free-pdf-cross-stitch-pattern",
            "title": "Owl - Free PDF Cross Stitch Pattern",
            "vendor": "Midnatt",
            "body_html": "<p>Stitches: 40 x 40<br>Floss used: DMC</p>",
            "tags": ["free", "cross stitch"],
            "images": [{"src": "https://cdn.example/owl.jpg"}],
        }
        self.assertTrue(_matches(product, "owl"))
        self.assertTrue(_matches(product, "midnatt"))
        self.assertFalse(_matches(product, "dracula"))
        fields = product_to_fields(product)
        self.assertEqual(fields["handle"], "owl-free-pdf-cross-stitch-pattern")
        self.assertIn("40 x 40", fields["description"])
        self.assertEqual(fields["thumbnail"], "https://cdn.example/owl.jpg")

    def test_cyberstitchers_parses_listing_card(self):
        html = """
        <title>Free Patterns | by Date Posted | Page 1 of 10 | Cyberstitchers</title>
        <div class="panel panel-default">
            <div class="panel-heading">
                <a href='/free_patterns/pattern/skull_bookmark'>Skull Bookmark</a>
            </div>
            <input onclick="document.location.href='/free_patterns/download/1790844611901/PDF'"/>
            <input onclick="document.location.href='/free_patterns/download/1790844611901/PAT'"/>
            <img src='/Data/PatternLibrary/img/1790844611901_150x150.jpg' alt="Skull Bookmark"/>
            <table>
                <tr><th>Designer:</th><td>Cyberstitchers<br /></td></tr>
                <tr><th>Category:</th><td>Holidays - Halloween</td></tr>
                <tr><th>Dimensions:</th><td>32w x 109h <a href="/x">x</a></td></tr>
            </table>
        </div>
        """
        self.assertEqual(parse_page_counts(html), (1, 10))
        self.assertTrue(search_path("skull bookmark").endswith("search_skull%20bookmark"))
        self.assertEqual(search_path(""), "/free_patterns/")
        cards = parse_cards(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["slug"], "skull_bookmark")
        self.assertEqual(cards[0]["id"], "1790844611901")
        self.assertEqual(cards[0]["title"], "Skull Bookmark")
        self.assertEqual(cards[0]["designer"], "Cyberstitchers")
        self.assertEqual(cards[0]["width"], 32)
        self.assertEqual(cards[0]["height"], 109)
        self.assertTrue(cards[0]["has_pat"])

    def test_cross_stitch_com_design_fields(self):
        fields = design_to_fields(
            {
                "DesignID": 5482,
                "Caption": "Cute Sleepy Cat",
                "Description": "103 x 87 stitches 10 colors",
                "ImageUrl": "https://cdn.example/cat.jpg",
                "PdfUrl": "https://cdn.example/pdfs/15/Stitch5482_Kit.pdf",
                "Width": 103,
                "Height": 87,
                "NColors": 10,
                "subject": "animals",
            }
        )
        self.assertEqual(fields["id"], "5482")
        self.assertEqual(fields["title"], "Cute Sleepy Cat")
        self.assertTrue(fields["pdf"].endswith("Stitch5482_Kit.pdf"))
        self.assertEqual(fields["colors"], 10)

    def test_fpo_parses_index_category_and_chart(self):
        index_html = """
        <a href="adobe/cancerribbon.pdf">Breast Cancer Ribbon</a>
        <a href="xscharts/floral.htm">Floral</a>
        <a href="xspatterns.htm">Rules</a>
        """
        files, cats = parse_index(index_html)
        self.assertEqual(files[0]["path"], "adobe/cancerribbon.pdf")
        self.assertEqual(files[0]["title"], "Breast Cancer Ribbon")
        self.assertEqual(cats, ["xscharts/floral.htm"])
        cat_html = """
        <a href="page/floral1.htm">Rose</a>
        <a href="page/floral2.htm">Sunflower</a>
        <a href="../xspatterns2.htm">Back to free patterns</a>
        """
        entries = parse_category(cat_html, base_path="xscharts/floral.htm", category="floral")
        self.assertEqual([e["title"] for e in entries], ["Rose", "Sunflower"])
        self.assertEqual(entries[0]["path"], "xscharts/page/floral1.htm")
        chart_html = """
        <img src="https://web.archive.org/web/20230529112858im_/https://freepatternsonline.com/xspats/other/rosech.gif" width="490">
        <img src="https://web.archive.org/web/20230529112858im_/https://freepatternsonline.com/xskeys/rosekey.jpg">
        <img src="horzad.png">
        """
        images = parse_chart_images(chart_html, base_path="xscharts/page/floral1.htm")
        self.assertEqual(images, ["xspats/other/rosech.gif", "xskeys/rosekey.jpg"])
        self.assertEqual(
            strip_wayback("https://web.archive.org/web/20240719135842/https://freepatternsonline.com/xscharts/floral.htm"),
            "xscharts/floral.htm",
        )
        self.assertIn("id_/", wayback_original("adobe/cancerribbon.pdf"))


if __name__ == "__main__":
    unittest.main()


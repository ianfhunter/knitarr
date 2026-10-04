"""Floss brand matching and Supplies preferences."""

from __future__ import annotations

import unittest

from knitarr.services.floss_catalog import (
    FLOSS_BRANDS,
    looks_like_floss_label,
    nearest_floss,
    normalize_floss_brand,
    parse_hex_rgb,
)
from knitarr.services.supplies import get_preferred_floss_brand, get_supplies, init_supplies, update_supplies


class FlossSuppliesTests(unittest.TestCase):
    def test_normalize_brand(self):
        self.assertEqual(normalize_floss_brand("DMC"), "dmc")
        self.assertEqual(normalize_floss_brand("anchor"), "anchor")
        self.assertEqual(normalize_floss_brand("Madeira"), "madeira")
        self.assertEqual(normalize_floss_brand("Cosmo"), "cosmo")
        self.assertEqual(normalize_floss_brand("Sullivans"), "sullivans")
        self.assertEqual(normalize_floss_brand("J&P Coats"), "jp_coats")
        self.assertEqual(normalize_floss_brand("CXC"), "cxc")
        self.assertEqual(normalize_floss_brand("nope"), "dmc")

    def test_all_brand_palettes_load(self):
        for brand_id in FLOSS_BRANDS:
            number, name, color = nearest_floss(parse_hex_rgb("000000"), brand=brand_id)
            self.assertTrue(number.startswith(FLOSS_BRANDS[brand_id]["label"] + " "), brand_id)
            self.assertTrue(name)
            self.assertEqual(len(color), 6)
            self.assertTrue(looks_like_floss_label(number, brand=brand_id), brand_id)

    def test_nearest_dmc_gold(self):
        number, name, color = nearest_floss(parse_hex_rgb("F0C840"), brand="dmc")
        self.assertTrue(number.startswith("DMC "))
        self.assertIn(
            name.lower(),
            {
                "topaz",
                "topaz light",
                "topaz medium",
                "old gold medium",
                "tangerine light",
                "yellow dark",
                "golden yellow",
            },
        )
        self.assertEqual(len(color), 6)

    def test_nearest_anchor(self):
        number, name, color = nearest_floss(parse_hex_rgb("000000"), brand="anchor")
        self.assertTrue(number.startswith("Anchor "))
        self.assertEqual(len(color), 6)
        self.assertTrue(looks_like_floss_label(number, brand="anchor"))

    def test_supplies_preference(self):
        init_supplies()
        before = get_preferred_floss_brand()
        self.assertIn(before, set(FLOSS_BRANDS))
        updated = update_supplies(floss_brand="madeira")
        self.assertEqual(updated["floss_brand"], "madeira")
        self.assertEqual(get_preferred_floss_brand(), "madeira")
        update_supplies(floss_brand=before)
        supplies = get_supplies()
        ids = {b["id"] for b in supplies["floss_brands"] if b["available"]}
        self.assertTrue({"dmc", "anchor", "madeira", "cosmo", "sullivans", "jp_coats", "cxc"} <= ids)
        self.assertTrue(all(b["color_count"] > 50 for b in supplies["floss_brands"] if b["available"]))


if __name__ == "__main__":
    unittest.main()

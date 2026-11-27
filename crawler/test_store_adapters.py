import unittest
from store_adapters import profile
class AdapterTests(unittest.TestCase):
    def test_shopify(self):
        raw=b'<script src="https://cdn.shopify.com/test.js"></script><button>Add to cart</button>'
        p=profile(raw,"https://shop.no/")
        self.assertEqual(p["adapter"],"shopify")
        self.assertEqual(p["search_path"],"/search?q={q}&type=product")
        self.assertTrue(p["shop"])
    def test_vat_separate_from_currency(self):
        p=profile(b'<p>NOK 100 inkl. mva</p>',"https://shop.no/")
        self.assertEqual(p["currency_hint"],"NOK")
        self.assertEqual(p["vat_status"],"vat_mentioned")
        self.assertFalse(p["shop"])
    def test_norwegian_vat_evidence(self):
        self.assertEqual(profile(b'<p>NO 123456789 MVA</p>',"https://shop.no/")["vat_status"],"norwegian_evidence")
    def test_search_form_not_shop(self):
        self.assertFalse(profile(b'<form action="/search"><input name="q"></form>',"https://example.no/")["shop"])
if __name__=="__main__":unittest.main()

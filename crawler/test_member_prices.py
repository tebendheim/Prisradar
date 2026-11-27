import json
import unittest

from crawl import extract

URL = "https://example.no/p/ep"


def page(offers, name="Test Produkt"):
    data = {"@context": "https://schema.org", "@type": "Product", "name": name, "url": URL, "offers": offers}
    return ("<html><script type='application/ld+json'>" + json.dumps(data) + "</script></html>").encode()


PUBLIC = {"@type": "Offer", "price": "1000", "priceCurrency": "NOK", "availability": "https://schema.org/InStock"}
MEMBER = {"@type": "Offer", "price": "900", "priceCurrency": "NOK", "validForMemberTier": {"name": "Klubb"}}


class MemberPricesTest(unittest.TestCase):
    def test_member_price_stored_separately_main_price_public(self):
        [o] = list(extract(page([MEMBER, PUBLIC]), URL, "example.no"))
        self.assertEqual(o["price"], 1000)
        self.assertEqual(o["price_kind"], "exact")
        self.assertEqual(o["member_prices"], [{"price": 900, "condition": "Klubb", "source": URL}])

    def test_member_only_offer_gives_no_offer(self):
        self.assertEqual(list(extract(page([MEMBER]), URL, "example.no")), [])

    def test_no_member_price_gives_empty_list(self):
        [o] = list(extract(page([PUBLIC]), URL, "example.no"))
        self.assertEqual(o["member_prices"], [])

    def test_non_nok_member_price_ignored(self):
        eur = dict(MEMBER, priceCurrency="EUR")
        [o] = list(extract(page([PUBLIC, eur]), URL, "example.no"))
        self.assertEqual(o["member_prices"], [])
        self.assertEqual(o["price"], 1000)


if __name__ == "__main__":
    unittest.main()

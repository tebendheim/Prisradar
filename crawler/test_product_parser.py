import unittest,json
from product_parser import parse,price,gtin,product_hint
from unittest.mock import patch
from crawl import fetch
import urllib.error
U="https://example.no/product/12345"
def page(obj):return ('<script type="application/ld+json">'+json.dumps(obj)+'</script>').encode()
def product(**kw):return dict({"@type":"Product","name":"Headphones","offers":{"@type":"Offer","price":"2499","priceCurrency":"NOK"}},**kw)
def parse_page(raw):return parse(raw,U,"example.no","2026-11-26T00:00:00Z")
class ParserTests(unittest.TestCase):
    def test_price(self):
        for s in ("2 499,00","2\u00a0499,00","2.499,00","2499.00"):
            self.assertEqual(price(s),2499)
        for s in ("NaN","0","2.499","2499 kr","-1",True):self.assertIsNone(price(s))
    def test_gtin(self):
        self.assertEqual(gtin("4006381333931"),"4006381333931")
        self.assertIsNone(gtin("4006381333932"))
    def test_graph(self):
        p=product(offers={"@id":"#offer"})
        self.assertEqual(parse_page(page({"@graph":[p,{"@id":"#offer","@type":"Offer","price":99,"priceCurrency":"NOK"}]}))[0]["price"],99)
    def test_spec(self):
        self.assertEqual(parse_page(page(product(offers={"priceSpecification":{"price":99,"priceCurrency":"NOK"}})))[0]["price"],99)
    def test_wrong_currency(self):
        self.assertFalse(parse_page(page(product(offers={"price":99,"priceCurrency":"USD"}))))
    def test_variants(self):
        self.assertFalse(parse_page(page(product(offers=[{"price":99,"priceCurrency":"NOK"},{"price":199,"priceCurrency":"NOK"}]))))
    def test_used(self):
        self.assertFalse(parse_page(page(product(offers={"price":99,"priceCurrency":"NOK","itemCondition":"https://schema.org/UsedCondition"}))))
    def test_aggregate(self):
        self.assertFalse(parse_page(page(product(offers={"@type":"AggregateOffer","lowPrice":99,"priceCurrency":"NOK"}))))
    def test_members(self):
        self.assertFalse(parse_page(page(product(offers={"price":99,"priceCurrency":"NOK","validForMemberTier":"Gold"}))))
    def test_related(self):
        self.assertFalse(parse_page(page(product(url="https://example.no/other"))))
    def test_metadata(self):
        html=b'<meta property="og:type" content="product"><meta property="og:title" content="Headphones"><meta property="product:price:amount" content="99"><meta property="product:price:currency" content="NOK">'
        self.assertEqual(parse_page(html)[0]["price"],99)
    def test_product_hint(self):
        self.assertTrue(product_hint(U));self.assertFalse(product_hint("https://example.no/category/audio"))

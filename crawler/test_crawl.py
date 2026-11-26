import unittest
from crawl import extract,coupon_extract
class TestCrawler(unittest.TestCase):
    def test_nok(self):
        html=b'<script type="application/ld+json">{"@type":"Product","name":"Test","offers":{"price":"99","priceCurrency":"NOK"}}</script>'
        self.assertEqual(list(extract(html,"https://example.no/a","example.no"))[0]["price"],99)
    def test_currency(self):
        html=b'<script type="application/ld+json">{"@type":"Product","name":"Test","offers":{"price":"99","priceCurrency":"USD"}}</script>'
        self.assertEqual(list(extract(html,"https://example.no/a","example.no")),[])
    def test_coupon(self):
        self.assertEqual(list(coupon_extract(b"rabattkode: TEST20","example.no","https://example.no"))[0]["code"],"TEST20")
if __name__=="__main__":unittest.main()

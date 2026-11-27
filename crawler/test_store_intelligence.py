import unittest
from merchant_feed import parse_feed
from store_rank import rank,relevant
from catalog_discovery import list_names
class StoreIntelligenceTests(unittest.TestCase):
    def test_feed_xml(self):
        raw=b'<rss xmlns:g="http://base.google.com/ns/1.0"><channel><item><g:title>Headphones</g:title><g:link>https://shop.no/products/1</g:link><g:gtin>4006381333931</g:gtin></item></channel></rss>'
        self.assertEqual(list(parse_feed(raw,"https://shop.no/feed.xml"))[0]["g"],"4006381333931")
    def test_feed_csv(self):
        self.assertEqual(len(list(parse_feed(b"title,link\nTest,https://shop.no/products/1\nOther,https://other.no/products/2","https://shop.no/feed.csv"))),1)
    def test_rank(self):
        self.assertGreater(rank("www.power.no","AirPods"),rank("www.jernia.no","AirPods"))
        self.assertTrue(relevant("www.jernia.no","AirPods",1))
    def test_list(self):
        raw=b'<script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"@type":"Product","name":"Test","url":"/products/1"},{"@type":"Product","name":"Other","url":"https://other.no/products/2"}]}</script>'
        self.assertEqual(len(list(list_names(raw,"https://shop.no/category"))),1)
if __name__=="__main__":unittest.main()

import unittest
from discover_settings import discover_paths
class DiscoveryTests(unittest.TestCase):
    def test_public_get_search(self):
        raw=b'<form action="/search" role="search"><input type="search" name="query"></form><a href="/products.xml">Product feed</a>'
        self.assertEqual(discover_paths(raw,"https://shop.no/"),("/search?query={q}",["/products.xml"]))
    def test_external_and_post(self):
        raw=b'<form action="https://other.no/search"><input name="q"></form><form action="/search" method="post"><input name="q"></form><a href="https://other.no/products.xml">feed</a>'
        self.assertEqual(discover_paths(raw,"https://shop.no/"),(None,[]))
if __name__=="__main__":unittest.main()

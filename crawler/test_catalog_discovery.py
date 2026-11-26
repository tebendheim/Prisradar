import unittest
from catalog_discovery import names
class CatalogueTests(unittest.TestCase):
    def test_name_without_price(self):
        raw=b'<script type="application/ld+json">{"@type":"Product","name":"Test product","gtin13":"4006381333931"}</script>'
        self.assertEqual(list(names(raw,"https://shop.no/products/test"))[0]["n"],"Test product")
    def test_category_not_product(self):
        self.assertEqual(list(names(b'<meta property="og:title" content="Category">',"https://shop.no/category")),[])
    def test_ambiguous_products(self):
        raw=b'<script type="application/ld+json">[{"@type":"Product","name":"One"},{"@type":"Product","name":"Two"}]</script>'
        self.assertEqual(list(names(raw,"https://shop.no/category")),[])
if __name__=="__main__":unittest.main()

"""Offline integration tests: actual discovery, parsing and orchestration, fake I/O."""
import unittest,time,json,urllib.error
from unittest.mock import patch
import demand,store_adapters
from store_search import search_url,links

HOST="shop.example"
BASE="https://"+HOST
URL=BASE+"/products/acme-headphones-3"
QUERY="acme headphones 3"
ROBOTS=b"User-agent: *\nDisallow:\n"
HOME=b'<script src="https://cdn.shopify.com/shop.js"></script><button>Add to cart</button>'
RESULT=b'<a href="/products/acme-headphones-3">Acme Headphones 3</a><a href="https://other.example/products/acme-headphones-3">Other</a>'
def product(currency="NOK"):
    return ('<script type="application/ld+json">'+json.dumps({"@context":"https://schema.org","@type":"Product","name":"Acme Headphones 3","url":URL,"offers":{"@type":"Offer","price":"1499","priceCurrency":currency,"availability":"https://schema.org/InStock"}})+'</script>').encode()
DNS=[(2,1,6,"",("8.8.8.8",443))]

class Integration(unittest.TestCase):
    def execute(self,blocked=False,currency="NOK",robots=ROBOTS):
        calls=[];writes=[];prices=[]
        def fetch(url,host,rp=None):
            calls.append(url)
            if url.endswith("/robots.txt"):return robots
            if blocked:raise urllib.error.HTTPError(url,429,"limited",{},None)
            if url==BASE+"/":return HOME
            if "/search/suggest.json?" in url:return json.dumps({"resources":{"results":{"products":[{"url":URL}]}}}).encode()
            if "/search?" in url:return RESULT
            if url==URL:return product(currency)
            self.fail("Unexpected fetch "+url)
        def db(table,params=None,method="GET",body=None,prefer=None):
            if method!="GET":writes.append((table,method,body));return None
            if table=="offers":return [{"id":7}]
            if table=="crawl_pages":return []
            self.fail("Unexpected DB read "+table)
        with patch.object(demand,"fetch",side_effect=fetch),patch.object(demand,"db",side_effect=db),patch.object(demand,"send",side_effect=lambda table,rows,key:prices.extend(rows)),patch.object(demand,"learn_assortment"),patch.object(demand.socket,"getaddrinfo",return_value=DNS),patch.object(demand,"discover",return_value=[]):
            result=demand.process_store(HOST,QUERY,{"search_path":None},[],time.monotonic()+100,12)
        return result,calls,writes,prices
    def test_discovery_to_price_and_permanent_index(self):
        count,calls,writes,prices=self.execute()
        self.assertEqual(count,1)
        self.assertEqual(float(prices[0]["price"]),1499)
        self.assertIn(URL,calls)
        self.assertTrue(any(t=="rpc/index_store_products_v1" and b["items"][0]["src"]==URL for t,m,b in writes))
        self.assertTrue(any(t=="search_offer_links" and b[0]["offer_id"]==7 for t,m,b in writes))
        self.assertTrue(any(t=="search_store_checks" and b["status"]=="found" for t,m,b in writes))
    def test_rate_limit_is_not_no_product(self):
        count,calls,writes,prices=self.execute(blocked=True)
        self.assertEqual(count,0)
        self.assertFalse(prices)
        self.assertTrue(any(t=="managed_stores" and "paused_until" in b for t,m,b in writes))
        self.assertTrue(any(t=="search_store_checks" and b["status"]=="incomplete" for t,m,b in writes))
    def test_foreign_currency_not_saved_as_nok(self):
        count,calls,writes,prices=self.execute(currency="USD")
        self.assertEqual(count,0)
        self.assertFalse(prices)
    def test_robots_disallow(self):
        count,calls,writes,prices=self.execute(robots=b"User-agent: *\nDisallow: /\n")
        self.assertEqual(count,0)
        self.assertEqual(calls,[BASE+"/robots.txt"])
        self.assertFalse(prices)

class AdapterIntegration(unittest.TestCase):
    def test_platform_search_urls(self):
        for raw,expected in [(HOME,"/search?q=Acme%20Headphones&type=product"),(b'<div class="woocommerce">Add to cart</div>',"/?s=Acme%20Headphones&post_type=product"),(b'<form action="/find"><input type="search" name="query"></form>',"/find?query=Acme%20Headphones")]:
            with self.subTest(expected=expected):
                p=store_adapters.profile(raw,BASE+"/")
                self.assertEqual(search_url(HOST,p["search_path"],"Acme Headphones"),BASE+expected)
    def test_result_links_stay_on_store(self):
        self.assertEqual(links(RESULT,BASE+"/search",HOST,QUERY),[URL])
    def test_unsafe_search_paths(self):
        for path in ["//other.example/?q={q}","https://other.example/?q={q}","/search"]:
            with self.assertRaises(ValueError):search_url(HOST,path,QUERY)
if __name__=="__main__":unittest.main()

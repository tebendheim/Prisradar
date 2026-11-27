import unittest,time,json,urllib.robotparser
from adapter_quality import repair,verify_reference

HOST="shop.example"
ROOT="https://"+HOST+"/"
URL=ROOT+"products/mixer"
REF={"name":"Acme Mixer","gtin":"4006381333931"}

class QualityTests(unittest.TestCase):
    def exercise(self,code="4006381333931",blocked=False):
        calls=[]
        def robots(*args):
            r=urllib.robotparser.RobotFileParser()
            r.parse(["User-agent: *","Disallow: /" if blocked else "Disallow:"])
            return r
        def fetch(url,*args):
            calls.append(url)
            if url==ROOT:return b'<form action="/find"><input type="search" name="q"></form><button>Add to cart</button>'
            if "/find?" in url:return b'<a href="/products/mixer">Acme Mixer</a>'
            if url==URL:
                return ('<script type="application/ld+json">'+json.dumps({"@type":"Product","name":"Acme Mixer","gtin13":code,"offers":{"price":"199","priceCurrency":"NOK"}})+'</script>').encode()
            raise AssertionError("Unexpected URL")
        return repair(HOST,{},[REF],time.monotonic()+100,fetch,robots),calls
    def test_repair_verified(self):
        (patch,detail),calls=self.exercise()
        self.assertEqual(patch["search_path"],"/find?q={q}")
        self.assertEqual(detail,"reference verified")
        self.assertIn(URL,calls)
    def test_wrong_gtin_rejected(self):
        (patch,detail),_=self.exercise("4006381333948")
        self.assertIsNone(patch)
    def test_robots_disallow(self):
        (patch,detail),calls=self.exercise(blocked=True)
        self.assertIsNone(patch)
        self.assertEqual(calls,[])
    def test_from_price_not_reference(self):
        self.assertFalse(verify_reference({"gtin":REF["gtin"],"price_kind":"from"},REF))

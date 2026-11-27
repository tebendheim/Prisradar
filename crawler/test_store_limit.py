import unittest,time
from unittest.mock import patch
import store_adapters as sa

PROFILE={"shop":True,"search_path":"/s?q={q}","adapter":"x","vat_status":"unknown","currency_hint":"NOK"}

class StoreLimit(unittest.TestCase):
    def run_probe(self,limit_row):
        writes=[];reads=[]
        def db(table,params=None,method="GET",body=None,prefer=None):
            if method!="GET":writes.append((table,method,body));return None
            reads.append((table,dict(params)))
            if table=="store_candidates":return [{"host":"shop.example.no","source":"t"}]
            if params.get("offset"):return [{"host":"x"}] if limit_row else []
            return []
        class RP:
            def can_fetch(self,*a):return True
        with patch.object(sa,"db",side_effect=db),patch.object(sa,"load_robots",return_value=RP()),patch.object(sa,"fetch",return_value=b""),patch.object(sa,"profile",return_value=PROFILE),patch.object(sa.socket,"getaddrinfo",return_value=[(0,0,0,"",("93.184.216.34",443))]):
            sa.probe_candidates(time.monotonic()+100)
        return writes,reads
    def test_limit_value(self):self.assertEqual(sa.MAX_STORES,2000)
    def test_blocked_when_row_exists(self):
        writes,reads=self.run_probe(True)
        self.assertIn(("managed_stores","offset","1999"),[(t,"offset",p["offset"]) for t,p in reads if "offset" in p])
        self.assertFalse([w for w in writes if w[0]=="managed_stores"])
        self.assertEqual([w for w in writes if w[0]=="store_candidates"][0][2]["probe_result"],"store limit reached")
    def test_allowed_otherwise(self):
        writes,_=self.run_probe(False)
        self.assertTrue([w for w in writes if w[0]=="managed_stores" and w[2][0]["host"]=="shop.example.no"])
if __name__=="__main__":unittest.main()

import unittest,time,threading,datetime,urllib.error
from unittest.mock import patch
import store_adapters as sa
import brreg_seed

SHOP={"shop":True,"search_path":"/s?q={q}","adapter":"x","vat_status":"unknown","currency_hint":"NOK"}
class RP:
    def can_fetch(self,*a):return True

def run_probe(hosts,deadline_in=100,fetch=None,profile=SHOP,registered=(),workers=12,source="t",fail=(),store_rows=None):
    writes=[];lock=threading.Lock()
    def db(table,params=None,method="GET",body=None,prefer=None):
        with lock:
            if method!="GET":writes.append((table,method,params,body));return None
        if "store_candidates" in fail and table=="store_candidates":raise OSError("db down")
        if "registered" in fail and table=="managed_stores" and "host" in params:raise OSError("db down")
        if table=="store_candidates":return [{"host":h,"source":source} for h in hosts]
        if table=="managed_stores" and params and "host" in params:return [{"host":h} for h in registered]
        if table=="managed_stores" and params and "offset" in params and store_rows is not None:
            return [{"host":"x"}] if sum(1 for x in writes if x[0]=="managed_stores")>=store_rows else []
        return []
    with patch.object(sa,"db",side_effect=db),patch.object(sa,"load_robots",return_value=RP()),patch.object(sa,"fetch",fetch or (lambda *a:b"")),patch.object(sa,"profile",return_value=profile),patch.object(sa.socket,"getaddrinfo",return_value=[(0,0,0,"",("93.184.216.34",443))]):
        n=sa.probe_candidates(time.monotonic()+deadline_in,workers=workers)
    return n,writes

class Probe(unittest.TestCase):
    def test_not_limited_to_four(self):
        hosts=["s%d.example.no"%i for i in range(120)]
        n,writes=run_probe(hosts)
        self.assertEqual(n,120)
        self.assertEqual(len([w for w in writes if w[0]=="store_candidates"]),120)
        self.assertEqual(len([w for w in writes if w[0]=="managed_stores"]),120)
    def test_deadline_stops_new_probes(self):
        n,writes=run_probe(["a.example.no","b.example.no"],deadline_in=10)  # inside margin
        self.assertEqual(n,0);self.assertEqual(writes,[])
    def test_deadline_mid_run(self):
        calls=[]
        def slow(*a):
            calls.append(a);time.sleep(0.05);return b""
        hosts=["h%d.example.no"%i for i in range(40)]
        # real clock: deadline just after margin allows only a few tasks
        n,_=run_probe(hosts,deadline_in=35+14+0.3,fetch=slow,workers=1)
        self.assertLess(n,40)
    def test_deadline_mid_run_deterministic(self):
        # No real clock: can_start allows exactly 5 starts, then refuses. Margin must be 35 s, deadline given.
        seen=[];fetched=[]
        def gate(deadline,rp=None,margin=0):
            seen.append((deadline is not None,rp,margin))
            return len(seen)<=5
        with patch.object(sa,"can_start",side_effect=gate):
            n,writes=run_probe(["m%d.example.no"%i for i in range(40)],fetch=lambda *a:fetched.append(a) or b"",workers=1)
        self.assertEqual(n,5)
        self.assertEqual(len([w for w in writes if w[0]=="store_candidates"]),5)
        self.assertEqual(len(fetched),5)   # one page fetch per started probe (robots is patched)
        self.assertEqual(len(seen),40)     # every candidate asked once; none probed twice
        self.assertTrue(all(d and rp is None and m==35 for d,rp,m in seen))
    def test_store_limit_checked_once_per_run(self):
        calls=[]
        def db(table,params=None,method="GET",body=None,prefer=None):
            if method!="GET":return None
            if table=="store_candidates":return [{"host":"l%d.example.no"%i,"source":"t"} for i in range(20)]
            if table=="managed_stores" and "offset" in (params or {}):calls.append(params);return [{"host":"x"}]
            return []
        with patch.object(sa,"db",side_effect=db),patch.object(sa,"load_robots",return_value=RP()),patch.object(sa,"fetch",return_value=b""),patch.object(sa,"profile",return_value=SHOP),patch.object(sa.socket,"getaddrinfo",return_value=[(0,0,0,"",("93.184.216.34",443))]):
            n=sa.probe_candidates(time.monotonic()+100)
        self.assertEqual(n,20);self.assertEqual(len(calls),1);self.assertEqual(calls[0]["offset"],str(sa.MAX_STORES-1))
    def test_registered_batch_query_format(self):
        seen=[]
        def db(table,params=None,*a,**k):
            seen.append(params["host"]);return [{"host":"WWW.A-b.example.no"}]
        with patch.object(sa,"db",side_effect=db):
            found=sa.registered_hosts(["a-b.example.no"]+["h%d.example.no"%i for i in range(59)])
        self.assertEqual(len(seen),2)    # 60 hosts -> 2 batches of <=50
        self.assertTrue(seen[0].startswith("in.(") and seen[0].endswith(")") and " " not in seen[0] and '"' not in seen[0])
        self.assertIn("www.a-b.example.no",seen[0].split(","))
        self.assertIn("a-b.example.no",found)
    def test_no_parallel_same_host(self):
        active={};peak=[0];lock=threading.Lock()
        def f(url,host,rp=None):
            with lock:
                active[host]=active.get(host,0)+1;peak[0]=max(peak[0],active[host])
            time.sleep(0.01)
            with lock:active[host]-=1
            return b""
        n,_=run_probe(["a.example.no","www.a.example.no","a.example.no"]+["x%d.example.no"%i for i in range(10)],fetch=f)
        self.assertEqual(peak[0],1)
        self.assertEqual(n,11)  # a.example.no and www.a.example.no are one host
    def test_workers_capped(self):
        cur=[0];peak=[0];lock=threading.Lock()
        def f(*a):
            with lock:cur[0]+=1;peak[0]=max(peak[0],cur[0])
            time.sleep(0.02)
            with lock:cur[0]-=1
            return b""
        run_probe(["w%d.example.no"%i for i in range(60)],fetch=f,workers=99)
        self.assertLessEqual(peak[0],12);self.assertGreater(peak[0],1)
    def patch_for(self,writes,h):
        return [w[3] for w in writes if w[0]=="store_candidates" and w[2]["host"]=="eq."+h][0]
    def days(self,p):
        return (datetime.datetime.fromisoformat(p["probe_next"])-datetime.datetime.now(datetime.timezone.utc)).total_seconds()/86400
    def test_failures_pushed_forward(self):
        def f(url,host,rp=None):
            if host=="blocked.example.no":raise urllib.error.HTTPError(url,403,"x",{},None)
            if host=="limited.example.no":raise urllib.error.HTTPError(url,429,"x",{},None)
            if host=="down.example.no":raise urllib.error.URLError("x")
            return b""
        n,w=run_probe(["blocked.example.no","limited.example.no","down.example.no"],fetch=f)
        self.assertEqual(self.patch_for(w,"blocked.example.no")["probe_result"],"HTTP 403")
        self.assertGreater(self.days(self.patch_for(w,"blocked.example.no")),25)
        self.assertGreater(self.days(self.patch_for(w,"limited.example.no")),6)
        self.assertGreater(self.days(self.patch_for(w,"down.example.no")),13)
        self.assertFalse([x for x in w if x[0]=="managed_stores"])
    def test_non_shop_and_registered(self):
        n,w=run_probe(["plain.example.no"],profile=dict(SHOP,shop=False))
        p=self.patch_for(w,"plain.example.no");self.assertEqual(p["probe_result"],"no storefront evidence");self.assertGreater(self.days(p),25)
        n,w=run_probe(["www.known.example.no"],registered=["known.example.no"])
        p=self.patch_for(w,"www.known.example.no");self.assertEqual(p["probe_result"],"already registered");self.assertGreater(self.days(p),80)
    def test_legacy_limit_ignored(self):
        with patch.object(sa,"db",return_value=[]) as d:
            sa.probe_candidates(time.monotonic()+100,limit=16)
        self.assertEqual(d.call_args_list[0][0][1]["limit"],str(sa.PROBE_BATCH));self.assertGreater(sa.PROBE_BATCH,100)

class Hardening(unittest.TestCase):
    def test_link_candidates_capped(self):
        n,w=run_probe(["l%d.example.no"%i for i in range(25)],source="https://shop.no/")
        self.assertEqual(len([x for x in w if x[0]=="managed_stores"]),sa.LINK_ACTIVATIONS)
        capped=[x[3] for x in w if x[0]=="store_candidates" and x[3]["probe_result"]=="link candidate cap reached"]
        self.assertEqual(len(capped),15)
        self.assertTrue(all(0.9<(datetime.datetime.fromisoformat(c["probe_next"])-datetime.datetime.now(datetime.timezone.utc)).total_seconds()/86400<1.1 for c in capped))
    def test_curated_and_brreg_not_capped(self):
        for src in ("crawler/stores.txt","https://data.brreg.no/enhetsregisteret/api/enheter"):
            n,w=run_probe(["c%d.example.no"%i for i in range(25)],source=src)
            self.assertEqual(len([x for x in w if x[0]=="managed_stores"]),25,src)
    def test_hard_store_cap_exact(self):
        n,w=run_probe(["k%d.example.no"%i for i in range(40)],source="crawler/stores.txt",store_rows=7)
        self.assertEqual(len([x for x in w if x[0]=="managed_stores"]),7)
    def test_db_read_failure_does_not_raise(self):
        self.assertEqual(run_probe(["a.example.no"],fail=("store_candidates",))[0],0)
    def test_registered_lookup_failure_skips_batch(self):
        n,w=run_probe(["a.example.no"],fail=("registered",))
        self.assertEqual(n,1)

class Job(unittest.TestCase):
    def test_probe_runs_when_earlier_steps_fail(self):
        import discovery_job
        called=[]
        with patch.object(brreg_seed,"run",side_effect=RuntimeError("x")),patch.object(brreg_seed,"seed_curated",side_effect=OSError("y")),patch.object(brreg_seed,"seed_from_active",side_effect=ValueError("z")),patch.object(sa,"probe_candidates",side_effect=lambda d:called.append(d)):
            discovery_job.main(start=1000.0,budget=270)
        self.assertEqual(called,[1270.0])
    def test_shared_deadline_passed_to_steps(self):
        import discovery_job
        seen={}
        with patch.object(brreg_seed,"run",side_effect=lambda deadline=None:seen.update(b=deadline)),patch.object(brreg_seed,"seed_curated"),patch.object(brreg_seed,"seed_from_active",side_effect=lambda deadline=None:seen.update(l=deadline)),patch.object(sa,"probe_candidates",side_effect=lambda d:seen.update(p=d)):
            discovery_job.main(start=500.0)
        self.assertLess(seen["b"],seen["l"]);self.assertLess(seen["l"],seen["p"]);self.assertEqual(seen["p"],770.0)
    def test_brreg_stops_at_deadline(self):
        import json
        calls=[]
        def fetch(url,host,rp=None):
            calls.append(url);return json.dumps({"page":{"totalPages":5},"_embedded":{"enheter":[]}}).encode()
        with patch.object(brreg_seed,"fetch",fetch),patch("crawl.load_robots",return_value=RP()),patch.object(brreg_seed,"db"):
            brreg_seed.run(deadline=time.monotonic()+1)
        self.assertEqual(len(calls),1)  # first page only, then deadline
    def test_links_stop_at_deadline(self):
        with patch.object(brreg_seed,"db",return_value=[{"host":"a.no"},{"host":"b.no"}]),patch("crawl.load_robots",return_value=RP()),patch.object(brreg_seed,"fetch") as f:
            self.assertEqual(brreg_seed.seed_from_active(deadline=time.monotonic()+5),0)
        f.assert_not_called()
    def test_workflow_uses_single_entrypoint(self):
        import os
        with open(os.path.join(os.path.dirname(__file__),"..",".github","workflows","store-discovery.yml"),encoding="utf8") as f:y=f.read()
        self.assertIn("discovery_job.py",y);self.assertNotIn("probe_candidates",y)

class Sources(unittest.TestCase):
    def test_curated_hosts(self):
        self.assertEqual(brreg_seed.curated_hosts("# c\nwww.Elkjop.no\nelkjop.no  # dup\n\nbad host\nposten.no\nxxl.no\n"),["elkjop.no","xxl.no"])
    def test_stores_txt_parses(self):
        import os
        with open(os.path.join(os.path.dirname(brreg_seed.__file__),"stores.txt"),encoding="utf8") as f:hosts=brreg_seed.curated_hosts(f.read())
        self.assertGreater(len(hosts),60);self.assertIn("elkjop.no",hosts);self.assertIn("xxl.no",hosts)
    def test_seed_curated_ignore_duplicates(self):
        writes=[]
        with patch.object(brreg_seed,"db",side_effect=lambda *a:writes.append(a)):
            n=brreg_seed.seed_curated()
        self.assertEqual(n,sum(len(w[3]) for w in writes))
        self.assertTrue(all(w[0]=="store_candidates" and "ignore-duplicates" in w[4] for w in writes))
        self.assertTrue(all(r["host"] and not r["host"].startswith("www.") for w in writes for r in w[3]))
    def test_linked_hosts(self):
        raw=b'<a href="https://www.butikk.no/x">a</a><a href="https://own.no/">o</a><a href="https://posten.no/">p</a><a href="http://insecure.no/">i</a><a href="https://foo.com/">c</a><a href="/rel">r</a><a href="https://butikk.no/y">dup</a>'
        self.assertEqual(brreg_seed.linked_hosts(raw,"https://www.own.no/"),["butikk.no"])
    def test_seed_from_active(self):
        writes=[]
        def db(table,params=None,method="GET",body=None,prefer=None):
            if method=="GET":return [{"host":"www.a.no"}]
            writes.append((table,body));return None
        with patch.object(brreg_seed,"db",side_effect=db),patch("crawl.load_robots",return_value=RP()),patch.object(brreg_seed,"fetch",return_value=b'<a href="https://ny.no/">x</a>'):
            n=brreg_seed.seed_from_active()
        self.assertEqual(n,1);self.assertEqual(writes[0][1][0]["host"],"ny.no")
if __name__=="__main__":unittest.main()

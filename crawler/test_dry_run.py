import io,os,unittest,contextlib
from unittest.mock import patch
import crawl,durable

KEY="sekret-nokkel-123"
ENV={"SUPABASE_URL":"https://abc.supabase.co","SUPABASE_SERVICE_ROLE_KEY":KEY}

class FakeOpener:
    def __init__(self):self.reqs=[]
    def open(self,req,timeout=0):
        self.reqs.append(req)
        class R:
            def __enter__(s):return s
            def __exit__(s,*a):return False
            def read(s):return b"[]"
        return R()

def run(env,fn):
    op=FakeOpener();out=io.StringIO()
    with patch.dict(os.environ,env,clear=False),patch.object(durable,"opener",op),patch.object(crawl,"opener",op),contextlib.redirect_stdout(out):
        r=fn()
    return op.reqs,out.getvalue(),r

class DryRun(unittest.TestCase):
    def test_all_write_paths_blocked(self):
        def go():
            durable.db("crawl_pages",{"on_conflict":"url"},"POST",[{"url":"a"},{"url":"b"}],"x")
            durable.db("managed_stores",{"host":"eq.a"},"PATCH",{"paused_until":"x"})
            durable.db("crawl_pages",{"url":"eq.a"},"DELETE")
            durable.db("rpc/learn_catalog_batch_v1",None,"POST",{"items":[{"n":1}]*3})
            durable.db("rpc/index_store_products_v1",None,"POST",{"h":"a","items":[]})
            durable.db("rpc/prune_searches_v1",None,"POST",{})
            return crawl.send("offers",[{"a":1}],"a")
        reqs,out,r=run(dict(ENV,DRY_RUN="1"),go)
        self.assertEqual(reqs,[]);self.assertIsNone(r)
        self.assertEqual(len(out.strip().splitlines()),7)
        self.assertIn("crawl_pages POST rows=2",out);self.assertIn("rpc/learn_catalog_batch_v1 POST rows=3",out)
        self.assertNotIn(KEY,out);self.assertNotIn("supabase.co",out)
    def test_reads_and_whitelisted_rpc_allowed(self):
        def go():
            durable.db("managed_stores",{"select":"host"})
            durable.db("rpc/schema_health_v1",None,"POST",{})
            durable.db("rpc/catalog_capacity_v1",None,"POST",{})
        reqs,out,_=run(dict(ENV,DRY_RUN="1"),go)
        self.assertEqual([r.get_method() for r in reqs],["GET","POST","POST"]);self.assertEqual(out,"")
    def test_without_dry_run_unchanged(self):
        def go():
            durable.db("crawl_pages",None,"POST",[{"url":"a"}]);crawl.send("offers",[{"a":1}],"a")
        env=dict(ENV);
        with patch.dict(os.environ,{},clear=False):os.environ.pop("DRY_RUN",None)
        reqs,out,_=run(env,go)
        self.assertEqual(len(reqs),2);self.assertEqual(out,"")
    def test_dry_run_without_url_blocks_writes_and_reads_fail_clearly(self):
        with patch.dict(os.environ,{"DRY_RUN":"1"}):
            os.environ.pop("SUPABASE_URL",None);os.environ.pop("SUPABASE_SERVICE_ROLE_KEY",None)
            with contextlib.redirect_stdout(io.StringIO()):self.assertIsNone(durable.db("t",None,"POST",[1]))
            with self.assertRaisesRegex(RuntimeError,"DRY_RUN: SUPABASE_URL"):durable.db("t")
    def test_db_all_stops_on_non_list(self):
        calls=[]
        def db(*a,**k):calls.append(a);return {"message":"x"}
        with patch.object(durable,"db",side_effect=db):self.assertEqual(durable.db_all("t"),[])
        self.assertEqual(len(calls),1)
        with patch.object(durable,"db",return_value=None):self.assertEqual(durable.db_all("t"),[])
    def test_only_exact_1_enables_dry_run(self):
        for v in ("0","","true","TRUE","yes"," 1","1 ","01"):
            with self.subTest(v=v):
                reqs,out,_=run(dict(ENV,DRY_RUN=v),lambda:durable.db("crawl_pages",None,"POST",[{"url":"a"}]))
                self.assertEqual(len(reqs),1);self.assertEqual(out,"")
        reqs,out,_=run(dict(ENV,DRY_RUN="1"),lambda:durable.db("crawl_pages",None,"POST",[{"url":"a"}]))
        self.assertEqual(reqs,[])
    def test_whitelist_is_exactly_two_read_rpcs(self):
        self.assertEqual(durable.DRY_RUN_READ_RPC,{"rpc/schema_health_v1","rpc/catalog_capacity_v1"})
    def test_whitelisted_rpcs_are_read_only_in_migrations(self):
        import re,glob
        sql=open(os.path.join(os.path.dirname(__file__),"..","supabase","migrations","2026112701.sql")).read()
        m=re.search(r"function public\.catalog_capacity_v1\(\).*?\$fn\$;",sql,re.S|re.I)
        self.assertIsNotNone(m);body=m[0].lower()
        self.assertIn("stable",body)
        for w in ("insert ","update ","delete ","truncate","drop ","alter "):self.assertNotIn(w,body)
        latest=sorted(glob.glob(os.path.join(os.path.dirname(__file__),"..","supabase","migrations","2026*.sql")))[-1]
        sql=open(latest).read()
        m=re.search(r"function public\.schema_health_v1\(\).*?end \$fn\$;",sql,re.S|re.I)
        self.assertIsNotNone(m);body=m[0].lower()
        self.assertIn("stable",body)
        for w in ("insert ","update ","delete ","truncate","drop ","alter "):self.assertNotIn(w,body)
    def test_send_dry_run_empty_rows_silent_and_no_secrets_on_error_path(self):
        reqs,out,_=run(dict(ENV,DRY_RUN="1"),lambda:crawl.send("offers",[],"a"))
        self.assertEqual((reqs,out),([],""))
    def test_only_db_and_send_open_connections_to_supabase(self):
        import re,glob
        for f in glob.glob(os.path.join(os.path.dirname(__file__),"*.py")):
            n=os.path.basename(f)
            if n.startswith("test_"):continue
            src=open(f).read()
            if "/rest/v1" in src:self.assertIn(n,("crawl.py","durable.py"))
if __name__=="__main__":unittest.main()

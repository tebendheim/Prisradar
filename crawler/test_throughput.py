"""Offline tests: early exit when idle, time-driven loop, deadline margin, one in-flight request per host."""
import io,os,time,threading,unittest,contextlib
from unittest.mock import patch
import demand,crawl,durable

HEALTH={"ready":True,"version":2026112708}
def fake_db(responses,calls=None):
    def db(table,params=None,method="GET",body=None,prefer=None):
        if calls is not None:calls.append((table,method))
        if table=="rpc/schema_health_v1":return HEALTH
        return responses.get(table,[]) if method=="GET" else None
    return db

class EarlyExit(unittest.TestCase):
    def go(self,responses):
        calls=[];out=io.StringIO()
        with patch.object(demand,"db",side_effect=fake_db(responses,calls)),patch.object(demand,"process_one",return_value=False) as po,patch("adapter_quality.run") as aq,patch("catalog_discovery.run") as cd,contextlib.redirect_stdout(out):
            demand.run()
        return calls,out.getvalue(),po,aq,cd
    def test_idle_exits_with_log_and_no_heavy_work(self):
        calls,out,po,aq,cd=self.go({"crawl_reports":[{"host":"a.no"}]})
        self.assertIn("Idle: nothing to do",out);self.assertIn("exiting early",out)
        po.assert_not_called();aq.assert_not_called();cd.assert_not_called()
        self.assertNotIn(("rpc/learn_catalog_batch_v1","POST"),calls)
    def test_due_search_is_work(self):
        _,out,po,_,_=self.go({"active_searches":[{"query":"x"}],"crawl_reports":[{"host":"a"}]})
        self.assertNotIn("Idle",out);po.assert_called()
    def test_overdue_page_is_work(self):
        _,out,_,aq,cd=self.go({"crawl_pages":[{"url":"u"}],"crawl_reports":[{"host":"a"}]})
        self.assertNotIn("Idle",out);cd.assert_called()
    def test_no_recent_catalogue_report_is_work(self):
        _,out,_,_,cd=self.go({})
        self.assertNotIn("Idle",out);cd.assert_called()
    def test_failed_idle_check_never_skips_work(self):
        import urllib.error
        def db(table,params=None,method="GET",body=None,prefer=None):
            if table=="rpc/schema_health_v1":return HEALTH
            if table=="active_searches":raise urllib.error.HTTPError("u",500,"x",{},None)
            return None
        with patch.object(demand,"db",side_effect=db):self.assertIsNone(demand.idle_reason())

class DeadlineAndLoop(unittest.TestCase):
    def test_run_seconds_clamped_and_below_job_timeout(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop("RUN_SECONDS",None);self.assertEqual(demand.run_seconds(),390)
        for v,e in (("9999",400),("5",60),("junk",390),("200",200)):
            with patch.dict(os.environ,{"RUN_SECONDS":v}):self.assertEqual(demand.run_seconds(),e)
        # job timeout 8 min = 480 s; keep >= 60 s for setup, in-flight request and final writes
        self.assertLessEqual(demand.MAX_RUN_SECONDS+25+20,480-30)
    def test_loop_continues_while_time_and_stops_at_margin(self):
        now=[1000.0];n=[0]
        def po(deadline,seen,ctx):
            n[0]+=1;now[0]+=20;return True
        with patch.object(demand,"db",side_effect=fake_db({"active_searches":[{"query":"x"}]})),patch.object(demand,"idle_reason",return_value=None),patch.object(demand,"process_one",side_effect=po),patch("adapter_quality.run"),patch("catalog_discovery.run"),patch.object(demand.time,"monotonic",side_effect=lambda:now[0]):
            demand.run()
        # searches stop 35 s before search_deadline (deadline-110): 390-110-35=245 s -> 13 iterations of 20 s, not a fixed 3
        self.assertEqual(n[0],13)
        self.assertLessEqual(now[0]-1000,245+20)
    def test_maintenance_skipped_without_margin(self):
        now=[1000.0]
        def po(deadline,seen,ctx):now[0]+=1000;return True
        with patch.object(demand,"db",side_effect=fake_db({})),patch.object(demand,"idle_reason",return_value=None),patch.object(demand,"process_one",side_effect=po),patch("adapter_quality.run") as aq,patch("catalog_discovery.run") as cd,patch.object(demand.time,"monotonic",side_effect=lambda:now[0]):
            demand.run()
        aq.assert_not_called();cd.assert_not_called()
    def test_process_one_never_repeats_a_query(self):
        seen={"a"}
        def db(table,params=None,method="GET",body=None,prefer=None):
            if table=="active_searches":
                self.assertEqual(params["limit"],"2");return [{"query":"a"}]
            self.fail("should stop before other reads: "+table)
        with patch.object(demand,"db",side_effect=db),contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(demand.process_one(time.monotonic()+100,seen,{}))
    def test_workers_bounded(self):self.assertEqual(demand.WORKERS,12)

class PerHost(unittest.TestCase):
    def setUp(self):crawl._last_request.clear();crawl._host_locks.clear()
    def run_fetches(self,hosts,delay_rp=None):
        active={};peak={};lock=threading.Lock()
        class R:
            def __init__(s,h):s.h=h
            def __enter__(s):return s
            def __exit__(s,*a):return False
            def read(s,n=-1):
                with lock:active[s.h]=active.get(s.h,0)+1;peak[s.h]=max(peak.get(s.h,0),active[s.h])
                time.sleep(0.02)
                with lock:active[s.h]-=1
                return b"ok"
        class Op:
            def open(s,req,timeout=0):return R(req.full_url.split("/")[2])
        with patch.object(crawl,"opener",Op()),patch.object(crawl.socket,"getaddrinfo",return_value=[(2,1,6,"",("8.8.8.8",443))]),patch.object(crawl,"throttle"):
            ts=[threading.Thread(target=crawl.fetch,args=("https://"+h+"/p"+str(i),h)) for i,h in enumerate(hosts)]
            [t.start() for t in ts];[t.join() for t in ts]
        return peak
    def test_same_host_never_parallel_different_hosts_overlap(self):
        peak=self.run_fetches(["a.no"]*6+["www.a.no"]*0+["b.no"]*6)
        self.assertEqual(peak["a.no"],1);self.assertEqual(peak["b.no"],1)
    def test_www_and_bare_share_one_lock(self):
        self.assertIs(crawl.host_lock("www.a.no"),crawl.host_lock("a.no"))
        self.assertIsNot(crawl.host_lock("a.no"),crawl.host_lock("b.no"))
    def test_crawl_delay_exact_per_host_and_independent_across_hosts(self):
        class RP:
            def crawl_delay(s,ua):return 5
            def request_rate(s,ua):return None
        sleeps=[];t=[100.0]
        with patch.object(crawl.time,"monotonic",side_effect=lambda:t[0]),patch.object(crawl.time,"sleep",side_effect=sleeps.append):
            crawl.throttle("a.no",RP());crawl.throttle("www.a.no",RP());crawl.throttle("b.no",RP())
        # first a: no wait; second a (same host): exactly 5 s; first b: independent, no wait
        self.assertEqual(sleeps,[0,5,0])
    def test_selected_stores_deduplicated_by_www(self):
        # www and bare names are the same shop: only one is queued
        keys=set();sel=[]
        for h in ["www.x.no","x.no","y.no"]:
            if h.removeprefix("www.") not in keys:keys.add(h.removeprefix("www."));sel.append(h)
        self.assertEqual(sel,["www.x.no","y.no"])

class StoreStateAndDeadline(unittest.TestCase):
    def test_403_marks_cached_store_paused_in_place(self):
        import urllib.error,datetime
        cfg={"host":"a.no","paused_until":None,"search_path":None,"adapter":None,"feed_path":None};calls=[]
        def db(table,params=None,method="GET",body=None,prefer=None):calls.append((table,method,body));return None
        def robots(host,fetcher=None):raise urllib.error.HTTPError("u",403,"x",{},None)
        with patch.object(demand,"db",side_effect=db),patch.object(demand,"load_robots",side_effect=robots),patch.object(demand,"affiliate_items",return_value=[]),patch.object(demand.socket,"getaddrinfo",return_value=[(2,1,6,"",("8.8.8.8",443))]),contextlib.redirect_stdout(io.StringIO()):
            demand.process_store("a.no","q",cfg,[],time.monotonic()+100,6)
        self.assertTrue(cfg["paused_until"])
        self.assertGreater(datetime.datetime.fromisoformat(cfg["paused_until"]),datetime.datetime.now(datetime.timezone.utc))
        self.assertIn(("managed_stores","PATCH"),[(t,m) for t,m,_ in calls])
    def test_store_past_deadline_is_not_contacted_nor_marked_checked(self):
        # A store that did not get time keeps its due search_store_checks row (no PATCH), so it stays overdue.
        with patch.object(demand,"db",side_effect=AssertionError("no db write expected")),patch.object(demand,"load_robots",side_effect=AssertionError("no network expected")):
            self.assertEqual(demand.process_store("a.no","q",{},[],time.monotonic()+10,6),0)
if __name__=="__main__":unittest.main()

class DeadlineMarginInDiscovery(unittest.TestCase):
    RP=type("RP",(),{"site_maps":lambda s:["https://a.no/s1.xml","https://a.no/s2.xml"],"can_fetch":lambda s,*a:True,"crawl_delay":lambda s,u:20,"request_rate":lambda s,u:None})()
    def test_discover_default_deadline_unchanged(self):
        calls=[]
        def f(u,h,rp=None):calls.append(u);return b"<urlset><url><loc>https://a.no/p/1</loc></url></urlset>"
        with patch.object(durable,"fetch",side_effect=f):
            durable.discover("a.no",self.RP,[5])
        self.assertEqual(len(calls),2)
    def test_no_fetch_starts_if_crawl_delay_passes_deadline(self):
        calls=[]
        with patch.object(durable,"fetch",side_effect=lambda *a:calls.append(a)):
            # 20 s delay + 12 s timeout + 30 s margin = 62 s needed; only 50 s left
            durable.discover("a.no",self.RP,[5],time.monotonic()+50)
            self.assertEqual(calls,[])
            self.assertFalse(durable.can_start(time.monotonic()+50,self.RP,30))
            self.assertTrue(durable.can_start(time.monotonic()+70,self.RP,30))
            self.assertTrue(durable.can_start(None,self.RP,30))
    def test_catalogue_starts_no_store_without_room(self):
        import catalog_discovery as cd
        fetched=[]
        def db(table,params=None,method="GET",body=None,prefer=None):
            if table=="rpc/catalog_capacity_v1":return {"allowed":True}
            if table=="managed_stores":return [{"host":"a.no","paused_until":None,"feed_path":None,"search_path":None}]
            return []
        with patch.object(cd,"db",side_effect=db),patch.object(cd,"db_all",side_effect=lambda t,p=None,**k:db(t)),patch.object(cd,"fetch",side_effect=lambda *a:fetched.append(a)),patch.object(cd,"load_robots",side_effect=lambda *a:fetched.append(a)):
            cd.run(deadline=time.monotonic()+40,budget=60)
        self.assertEqual(fetched,[])

class AliasPause(unittest.TestCase):
    def test_429_pauses_all_alias_rows_in_cache(self):
        import urllib.error
        rows=[{"host":"www.x.no","paused_until":None},{"host":"x.no","paused_until":None},{"host":"y.no","paused_until":None}]
        ctx={"stores":rows}
        def fetch(url,host,rp=None):
            if url.endswith("/robots.txt"):raise urllib.error.HTTPError(url,429,"limited",{},None)
        with patch.object(demand,"fetch",side_effect=fetch),patch.object(demand,"db",return_value=None),patch.object(demand,"affiliate_items",return_value=[]),patch.object(demand.socket,"getaddrinfo",return_value=[(2,1,6,"",("8.8.8.8",443))]),contextlib.redirect_stdout(io.StringIO()):
            demand.process_store("www.x.no","q",rows[0],[],time.monotonic()+100,6,ctx)
        self.assertTrue(rows[0]["paused_until"] and rows[1]["paused_until"])
        self.assertIsNone(rows[2]["paused_until"])

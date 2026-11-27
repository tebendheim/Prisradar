"""Durable crawling, using the existing bounded network and product parser."""
import os,re,json,urllib.request,urllib.parse,time,datetime
from crawl import delay_for,dry_run,dry_write,fetch,opener,UA,error_detail,extract,coupon_extract,send,load_robots,same_host
from product_parser import product_hint,Page,walk,types
from sources import microdata,candidate_hosts
import urllib.robotparser,urllib.error,xml.etree.ElementTree as ET
from collections import deque
def stamp(days=0):
    return (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
# Read-only (STABLE, no inserts) RPCs the crawler needs to start; the only non-GET calls allowed in DRY_RUN.
# schema_health_v1: readiness check. catalog_capacity_v1: size check that gates catalogue learning.
DRY_RUN_READ_RPC=frozenset({"rpc/schema_health_v1","rpc/catalog_capacity_v1"})
def db(table,params=None,method="GET",body=None,prefer=None):
    if dry_run():
        if method!="GET" and table not in DRY_RUN_READ_RPC:dry_write(table,method,body);return None
        if "SUPABASE_URL" not in os.environ or "SUPABASE_SERVICE_ROLE_KEY" not in os.environ:raise RuntimeError("DRY_RUN: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for reads ("+table+")")
    base=os.environ["SUPABASE_URL"].rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co",base):raise ValueError("bad DB URL")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    h={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json"}
    if prefer:h["Prefer"]=prefer
    u=base+"/rest/v1/"+table+("?"+urllib.parse.urlencode(params) if params else "")
    with opener.open(urllib.request.Request(u,headers=h,data=json.dumps(body).encode() if body is not None else None,method=method),timeout=20) as r:
        raw=r.read();return json.loads(raw) if raw else None
def db_all(table,params=None,page=1000,cap=20000,order="host.asc"):
    """GET all rows via limit/offset (PostgREST max-rows is 1000). Always sends a stable order. Stops at a short page or at cap."""
    page=max(1,min(int(page),1000));base={k:v for k,v in dict(params or {}).items() if k not in("limit","offset")}
    base.setdefault("order",order);rows=[]
    while len(rows)<cap:
        want=min(page,cap-len(rows))
        got=db(table,dict(base,limit=str(want),offset=str(len(rows))))
        if not isinstance(got,list):break
        rows+=got
        if len(got)<want:break
    return rows
def can_start(deadline,rp=None,margin=0):
    """False if a fetch started now could finish after deadline-margin (Crawl-delay wait + 12 s timeout)."""
    return deadline is None or time.monotonic()+min(30,delay_for(rp))+12<=deadline-margin
def discover(host,rp,budget,deadline=None):
    maps=deque(rp.site_maps() or ["https://"+host+"/sitemap.xml"]);seen=set();pages=set()
    while maps and budget[0]>0 and len(seen)<6 and len(pages)<15000:
        u=maps.popleft()
        if not can_start(deadline,rp,30):break
        if u in seen or not same_host(urllib.parse.urlsplit(u).hostname,host) or not rp.can_fetch(UA,u):continue
        seen.add(u);budget[0]-=1
        try:
            tree=ET.fromstring(fetch(u,host,rp))
            locs=[n.text for n in tree.findall("./{*}*/{*}loc") if n.text]
            if tree.tag.endswith("sitemapindex"):
                maps.extend(sorted(locs,key=lambda u:not bool(re.search("product|produkt|vare",u,re.I)))[:100])
            else:
                pages.update(u for u in locs if len(u)<=1500 and same_host(urllib.parse.urlsplit(u).hostname,host) and urllib.parse.urlsplit(u).scheme=="https" and rp.can_fetch(UA,u))
        except urllib.error.HTTPError as e:
            if e.code in (401,403,429):raise
        except (ValueError,ET.ParseError):continue
    return sorted(pages,key=lambda u:(not product_hint(u),u))[:15000]
def words(q):return re.findall(r"[a-z0-9æøå]+",q.lower())
def relevance(u,q):
    text=urllib.parse.unquote(u).lower()
    return sum(w in text for w in words(q))
def run():
    hosts=[x.strip() for x in open("crawler/stores.txt") if x.strip() and not x.startswith("#")]
    reqs=db("crawl_requests",{"state":"eq.queued","select":"id,query","order":"created.asc","limit":"5"})
    # Process only after a bounded attempt across the selected stores.
    offset=int(os.environ.get("STORE_OFFSET","0"))%len(hosts)
    selected=(hosts[offset:]+hosts[:offset])[:4]
    budget=[min(60,max(8,int(os.environ.get("PAGE_BUDGET","40"))))]
    total=0; attempted=0
    for host in selected:
        if budget[0]<3:break
        allocation=max(3,budget[0]//(len(selected)-attempted));attempted+=1
        local=[allocation];count=0;found_count=0;detail="ok"
        try:
            local[0]-=1
            rp=load_robots(host,fetch)
            # Keep previously discovered pages and their next-check timestamps.
            due=db("crawl_pages",{"host":"eq."+host,"next_check":"lte."+stamp(),"select":"url","order":"next_check.asc","limit":"1000"})
            urls={x["url"] for x in due}
            if len(urls)<10 or reqs:
                discovery_budget=[min(5,max(0,local[0]-2))]
                before=discovery_budget[0]
                discovered=discover(host,rp,discovery_budget);local[0]-=before-discovery_budget[0]
                for i in range(0,len(discovered),500):
                    db("crawl_pages",{"on_conflict":"url"},"POST",[{"url":u,"host":host} for u in discovered[i:i+500]],"resolution=ignore-duplicates,return=minimal")
                # Reload due pages, prioritizing matching fresh candidates without resetting history.
                for req in reqs:
                    for u in sorted(discovered,key=lambda u:relevance(u,req["query"]),reverse=True)[:5]:
                        if relevance(u,req["query"])==len(words(req["query"])):urls.add(u)
                if not urls:
                    urls={x["url"] for x in db("crawl_pages",{"host":"eq."+host,"next_check":"lte."+stamp(),"select":"url","order":"next_check.asc","limit":"1000"})}
            ordered=sorted(urls,key=lambda u:(-max([relevance(u,r["query"]) for r in reqs] or [0]),not product_hint(u),u))
            for u in ordered:
                if local[0]<=0:break
                if not same_host(urllib.parse.urlsplit(u).hostname,host) or not rp.can_fetch(UA,u):continue
                local[0]-=1;count+=1;outcome="no structured offer"
                try:
                    raw=fetch(u,host,rp);offers=list(extract(raw,u,host))
                    if not offers:
                        p=Page();p.feed(raw.decode("utf8","replace"))
                        if not any("Product" in types(x) for x in walk(p.scripts)):
                            offers=microdata(raw,u,host,stamp())
                    candidates=candidate_hosts(raw,u)
                    if candidates:db("store_candidates",{"on_conflict":"host"},"POST",[{"host":h,"source":u} for h in candidates],"resolution=ignore-duplicates,return=minimal")
                    if offers:
                        send("offers",offers,"url,name");found_count+=len(offers);total+=len(offers);outcome="offer"
                    coupons=list(coupon_extract(raw,host,u))
                    # Never overwrite a manually reviewed coupon status.
                    if coupons:
                        db("coupons",{"on_conflict":"host,code,source"},"POST",list({(x["host"],x["code"],x["source"]):x for x in coupons}.values()),"resolution=ignore-duplicates,return=minimal")
                except urllib.error.HTTPError as e:
                    outcome=error_detail(e)
                    if e.code in (401,403,429):
                        detail=outcome;break
                except Exception as e:outcome=error_detail(e)
                db("crawl_pages",{"url":"eq."+u},"PATCH",{"checked":stamp(),"outcome":outcome,"next_check":stamp(1 if outcome=="offer" else 14)},"return=minimal")
        except Exception as e:detail=error_detail(e)
        finally:
            budget[0]-=allocation-local[0]
            db("crawl_reports",None,"POST",{"host":host,"pages":count,"offers":found_count,"detail":detail},"return=minimal")
            print(host,count,found_count,detail,flush=True)
    if attempted:
        for r in reqs:db("crawl_requests",{"id":"eq."+str(r["id"])},"PATCH",{"state":"processed","processed":stamp()},"return=minimal")
    print("Offers:",total,flush=True)
    if not total:raise SystemExit("No offers indexed; see crawl reports")
if __name__=="__main__":run()

"""Demand-driven crawler. Catalogue discovery is separate from price collection."""
import os,re,datetime,urllib.parse,urllib.robotparser,urllib.error
from durable import db,discover,stamp,words
from crawl import fetch,UA,extract,send,error_detail
from product_parser import Page,walk,types
from sources import microdata
from store_search import search_url,links
import socket,ipaddress

def matches(text,q):
    terms=words(q)
    tokens=set(words(urllib.parse.unquote(text)))
    return bool(terms) and all(t in tokens for t in terms)

def run():
    db("rpc/prune_searches_v1",None,"POST",{})
    jobs=db("active_searches",{"next_check":"lte."+stamp(),"last_searched":"gte."+(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=123)).isoformat(),"order":"last_searched.desc,next_check.asc","limit":"1"})
    if not jobs:
        print("No active searches due");return
    job=jobs[0];q=job["query"];stores=db("managed_stores",{"enabled":"eq.true","select":"host,search_path,paused_until","limit":"500"});config={x["host"]:x for x in stores if not x["paused_until"] or datetime.datetime.fromisoformat(x["paused_until"])<=datetime.datetime.now(datetime.timezone.utc)};hosts=list(config)
    if not hosts: print("No enabled stores available");return
    offset=int(os.environ.get("GITHUB_RUN_ID","0"))%len(hosts)
    hosts=hosts[offset:]+hosts[:offset]
    budget=min(65,int(os.environ.get("PAGE_BUDGET","60")))
    total=0
    for host in hosts:
        if budget<3:break
        count=0;found=0;detail="ok"
        try:
            if not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)):raise ValueError("nonpublic store address")
            budget-=1
            raw=fetch("https://"+host+"/robots.txt",host)
            rp=urllib.robotparser.RobotFileParser();rp.parse(raw.decode("utf8","replace").splitlines())
            if (rp.crawl_delay(UA) or rp.crawl_delay("*") or 0)>2 or rp.request_rate(UA) or rp.request_rate("*"):
                detail="robots rate restriction";continue
            # Previously known matching URLs are looked up server-side, not just the first 1000 rows.
            terms=words(q)
            params=[("host","eq."+host),("select","url"),("limit","40")]
            # PostgREST AND filters; terms are alphanumeric.
            params.extend(("url","ilike.*"+t+"*") for t in terms[:8])
            candidates={x["url"] for x in db("crawl_pages",params)}
            if config[host]["search_path"] and budget>2:
                u=search_url(host,config[host]["search_path"],q)
                if rp.can_fetch(UA,u):
                    budget-=1
                    try:candidates.update(links(fetch(u,host,rp),u,host,q))
                    except urllib.error.HTTPError as e:
                        if e.code in (403,429):raise
            if not candidates:
                allowance=[min(5,max(0,budget-2))]
                before=allowance[0];pages=discover(host,rp,allowance);budget-=before-allowance[0]
                # Preserve URL discovery only; no prices collected for unrelated products.
                for i in range(0,len(pages),500):
                    db("crawl_pages",{"on_conflict":"url"},"POST",[{"url":u,"host":host} for u in pages[i:i+500]],"resolution=ignore-duplicates,return=minimal")
                candidates.update(u for u in pages if matches(u,q))
            for u in sorted(candidates)[:5]:
                if budget<=0:break
                if urllib.parse.urlsplit(u).hostname!=host or not rp.can_fetch(UA,u):continue
                budget-=1;count+=1
                try:
                    raw=fetch(u,host,rp);offers=list(extract(raw,u,host))
                    if not offers:
                        p=Page();p.feed(raw.decode("utf8","replace"))
                        if not any("Product" in types(x) for x in walk(p.scripts)):offers=microdata(raw,u,host,stamp())
                    offers=[o for o in offers if matches(o["name"],q) or o.get("gtin")==q or (o.get("model") or "").lower()==q]
                    if not offers:continue
                    send("offers",offers,"url,name")
                    for o in offers:
                        rows=db("offers",{"url":"eq."+u,"name":"eq."+o["name"],"select":"id"})
                        if rows:db("search_offer_links",{"on_conflict":"query,offer_id"},"POST",[{"query":q,"offer_id":r["id"]} for r in rows],"resolution=ignore-duplicates,return=minimal")
                        db("rpc/learn_catalog_v1",None,"POST",{"n":o["name"],"src":u,"g":o.get("gtin")})
                    found+=len(offers);total+=len(offers)
                except urllib.error.HTTPError as e:
                    if e.code in (403,429):detail=error_detail(e);break
                    detail=error_detail(e)
        except Exception as e:detail=error_detail(e)
        finally:
            if detail in ("HTTP 403","HTTP 429"):db("managed_stores",{"host":"eq."+host},"PATCH",{"paused_until":stamp(1)},"return=minimal")
            db("crawl_reports",None,"POST",{"host":host,"pages":count,"offers":found,"detail":detail},"return=minimal")
            print(host,count,found,detail,flush=True)
    db("active_searches",{"query":"eq."+q},"PATCH",{"last_attempt":stamp(),"next_check":stamp(1 if total else 0.25)},"return=minimal")
    print("Search:",q,"offers:",total,flush=True)
if __name__=="__main__":run()

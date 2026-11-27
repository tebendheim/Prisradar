"""Demand-driven crawler. Catalogue discovery is separate from price collection."""
import os,re,datetime,urllib.parse,urllib.robotparser,urllib.error
from durable import db,discover,stamp,words
from crawl import fetch,UA,extract,send,error_detail,load_robots,same_host
from product_parser import Page,walk,types,normalized_gtin
from sources import microdata
from store_search import search_url,links
import socket,ipaddress,time
from catalog_seed import MODELS, URLS
from store_rank import rank,relevant,categories
from merchant_feed import learn_assortment,cached_feed,feed_offers
from affiliate_feed import affiliate_items
from store_adapters import profile,probe_candidates,public_search
from concurrent.futures import ThreadPoolExecutor

def matches(text,q):
    terms=words(q)
    tokens=set(words(urllib.parse.unquote(text)))
    if not terms or not all(t in tokens for t in terms):return False
    if "airpods" in terms and any(t.isdigit() for t in terms):
        model=re.search(r"airpods\s+(?:(?:pro|max)\s+)?(\d+)",text.lower())
        if model and model.group(1) not in terms:return False
    return True

def offer_matches(name,g,model,q):
    code=normalized_gtin(q.strip())
    if code:return normalized_gtin(g)==code
    return matches(name,q) or bool(model and model.lower()==q.lower())

def run():
    try:health=db("rpc/schema_health_v1",None,"POST",{})
    except urllib.error.HTTPError as e:
        raise SystemExit("Database readiness check failed (HTTP "+str(e.code)+"). Apply supabase/migrations/2026112706.sql") from None
    if not health.get("ready") or health.get("version",0)<2026112706:
        raise SystemExit("Database migration required: "+str(health.get("missing",[])))
    db("rpc/prune_searches_v1",None,"POST",{})
    db("rpc/learn_catalog_batch_v1",None,"POST",{"items":[{"n":name,"src":source,"g":None} for name,source in MODELS]})
    deadline=time.monotonic()+350
    search_deadline=deadline-150
    for _ in range(3):
        if time.monotonic()>search_deadline-35:break
        if not process_one(search_deadline):break
    if time.monotonic()<deadline-100:
        probe_candidates(min(deadline-65,time.monotonic()+65),limit=4)
    if time.monotonic()<deadline-45:
        from catalog_discovery import run as discover_catalog
        try:discover_catalog(deadline=deadline,budget=60)
        except urllib.error.HTTPError as e:
            if e.code not in (400,404):raise
            print("WARNING: catalogue maintenance unavailable; check supabase/store_catalog_upgrade.sql (HTTP "+str(e.code)+")",flush=True)

def optional_assortment():
    try:
        return db("store_assortment",{"select":"host,category,samples","limit":"5000"})
    except urllib.error.HTTPError as e:
        if e.code != 404:raise
        print("WARNING: store_assortment unavailable; using static ranking. Apply supabase/store_catalog_upgrade.sql",flush=True)
        return []

def process_one(deadline):
    jobs=db("active_searches",{"next_check":"lte."+stamp(),"last_searched":"gte."+(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=123)).isoformat(),"order":"last_searched.desc,next_check.asc","limit":"1"})
    if not jobs:
        print("No active searches due");return False
    job=jobs[0];q=job["query"];stores=db("managed_stores",{"enabled":"eq.true","select":"host,search_path,paused_until,adapter,feed_path","limit":"500"});config={x["host"]:x for x in stores if not x["paused_until"] or datetime.datetime.fromisoformat(x["paused_until"])<=datetime.datetime.now(datetime.timezone.utc)};hosts=list(config)
    if not hosts: print("No enabled stores available");return False
    terms=[t for t in words(q) if t!="apple"] or words(q)
    # One global indexed lookup, not a network request to every shop.
    params=[("select","host,url"),("limit","1000")]
    params.extend(("url","ilike.*"+t+"*") for t in terms[:8])
    evidence={}
    for row in db("crawl_pages",params):
        evidence.setdefault(row["host"],[]).append(row["url"])
    for row in db("offers",[( "select","host,url"),("limit","300")]+[("name","ilike.*"+t+"*") for t in terms[:8]]):
        evidence.setdefault(row["host"],[]).append(row["url"])
    for row in db("catalog_store_products",[("select","host,url"),("limit","1000")]+[("search_key","ilike.*"+t+"*") for t in terms[:8]]):
        evidence.setdefault(row["host"],[]).append(row["url"])
    code=normalized_gtin(q.strip())
    if code:
        for table in ("catalog_store_products","offers"):
            for row in db(table,{"select":"host,url","gtin":"in.("+",".join(code[-n:] for n in (8,12,13,14) if code[:-n].strip("0")=="")+")","limit":"1000"}):
                evidence.setdefault(row["host"],[]).append(row["url"])
    for name,u in URLS:
        if matches(name,q):evidence.setdefault(urllib.parse.urlsplit(u).hostname,[]).append(u)
    reports=db("crawl_reports",{"select":"host,offers","order":"created.desc","limit":"200"})
    history={}
    for row in reports:history[row["host"]]=history.get(row["host"],0)+row["offers"]
    offset=int(os.environ.get("GITHUB_RUN_NUMBER","0"))%len(hosts)
    hosts=hosts[offset:]+hosts[:offset]
    learned={}
    for row in optional_assortment():
        if row["category"] in categories(q):learned[row["host"]]=learned.get(row["host"],0)+row["samples"]
    hosts.sort(key=lambda h:rank(h,q,len(evidence.get(h,[])),history.get(h,0))+min(45,learned.get(h,0)),reverse=True)
    preferred=[h for h in hosts if learned.get(h,0) or relevant(h,q,len(evidence.get(h,[])))]
    hosts=preferred+[h for h in hosts if h not in preferred]
    # Parallel across different shops, never parallel requests to the same shop.
    db("search_store_checks",{"on_conflict":"query,host"},"POST",[{"query":q,"host":h} for h in hosts],"resolution=ignore-duplicates,return=minimal")
    checks=db("search_store_checks",{"query":"eq."+q,"select":"host,next_check,checked","limit":"500"})
    due={x["host"] for x in checks if datetime.datetime.fromisoformat(x["next_check"])<=datetime.datetime.now(datetime.timezone.utc)}
    checked_hosts={x["host"] for x in checks if x.get("checked")}
    selected=sorted((h for h in hosts if h in due),key=lambda h:h in checked_hosts)[:min(24,max(1,int(os.environ.get("PAGE_BUDGET","60"))//3))]
    if not selected:
        db("active_searches",{"query":"eq."+q},"PATCH",{"next_check":stamp(0.08)},"return=minimal");return True
    budget=min(144,int(os.environ.get("PAGE_BUDGET","60"))*2)
    print("Ranked stores:",selected,flush=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(lambda h:process_store(h,q,config[h],evidence.get(h,[]),min(deadline,time.monotonic()+65),max(6,budget//len(selected))),selected))
    total=sum(results)
    print("Search metrics: selected stores",len(selected),"offers",total,"seconds remaining",round(deadline-time.monotonic()),flush=True)
    db("active_searches",{"query":"eq."+q},"PATCH",{"last_attempt":stamp(),"next_check":stamp(0.02 if len(due)>len(selected) else 0.25 if total else 0.08)},"return=minimal")
    print("Search:",q,"offers:",total,flush=True)
    return True

def persist_offers(host,q,offers):
    if not offers:return 0
    for o in offers:
        o.setdefault("price_kind","exact");o.setdefault("brand",None);o.setdefault("mpn",None)
    send("offers",offers,"url,name")
    for o in offers:
        rows=db("offers",{"url":"eq."+o["url"],"name":"eq."+o["name"],"select":"id"})
        if rows:db("search_offer_links",{"on_conflict":"query,offer_id"},"POST",[{"query":q,"offer_id":r["id"]} for r in rows],"resolution=ignore-duplicates,return=minimal")
        db("rpc/learn_catalog_v1",None,"POST",{"n":o["name"],"src":o["url"],"g":o.get("gtin")})
    db("rpc/index_store_products_v1",None,"POST",{"h":host,"items":[{"n":o["name"],"src":o["url"],"g":o.get("gtin")} for o in offers][:100]})
    learn_assortment(host,[{"n":o["name"]} for o in offers])
    return len(offers)

def process_store(host,q,config,prior,deadline,budget):
    if time.monotonic()>deadline-25:return 0
    total=0
    count=0;found=0;detail="ok"
    try:
        if not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)):raise ValueError("nonpublic store address")
        # An independently authorised affiliate feed is not a request to the merchant.
        try:
            rows=list(feed_offers(affiliate_items(host),host,lambda x:offer_matches(x["n"],x.get("g"),None,q)))[:100]
            n=persist_offers(host,q,rows);found+=n;total+=n
        except (ValueError,OSError) as e:print(host,"affiliate feed unavailable",type(e).__name__,flush=True)
        budget-=1
        rp=load_robots(host,fetch)
        feed=config.get("feed_path")
        if feed and budget>2 and feed.startswith("/") and not feed.startswith("//") and "\\" not in feed:
            u="https://"+host+feed
            if rp.can_fetch(UA,u):
                budget-=1
                try:
                    rows=list(feed_offers(cached_feed(u,host,rp,fetch),host,lambda x:offer_matches(x["n"],x.get("g"),None,q)))[:100]
                    n=persist_offers(host,q,rows);found+=n;total+=n
                except urllib.error.HTTPError as e:
                    if e.code in (401,403,429):raise
                except (ValueError,OSError):pass
        # Previously known matching URLs are looked up server-side, not just the first 1000 rows.
        terms=[t for t in words(q) if t not in ("apple",) ] or words(q)
        params=[("host","eq."+host),("select","url"),("limit","40")]
        # PostgREST AND filters; terms are alphanumeric.
        params.extend(("url","ilike.*"+t+"*") for t in terms[:8])
        candidates=set(prior)
        if not candidates:candidates={x["url"] for x in db("crawl_pages",params)}
        known=[u for name,u in URLS if matches(name,q) and same_host(urllib.parse.urlsplit(u).hostname,host)]
        candidates.update(known)
        if not candidates and not config["search_path"] and budget>3 and rp.can_fetch(UA,"https://"+host+"/"):
            budget-=1
            detected=profile(fetch("https://"+host+"/",host,rp),"https://"+host+"/")
            path=detected["search_path"]
            patch={k:detected[k] for k in ("adapter","vat_status","currency_hint")}
            if path and rp.can_fetch(UA,search_url(host,path,q)):
                patch["search_path"]=path;config["search_path"]=path
            db("managed_stores",{"host":"eq."+host},"PATCH",patch,"return=minimal")
            config["adapter"]=detected["adapter"]
        if config.get("adapter") in ("shopify","woocommerce") and budget>3 and time.monotonic()<deadline-35:
            budget-=1
            api_offers=[]
            candidates.update(public_search(host,config["adapter"],q,rp,fetch,api_offers))
            api_offers=[o for o in api_offers if offer_matches(o["name"],o.get("gtin"),o.get("model"),q)]
            if api_offers:
                n=persist_offers(host,q,api_offers);found+=n;total+=n
            api_urls={o["url"] for o in api_offers}
        else:api_urls=set()
        if config["search_path"] and budget>2:
            u=search_url(host,config["search_path"],q)
            if rp.can_fetch(UA,u):
                budget-=1
                try:candidates.update(links(fetch(u,host,rp),u,host,q))
                except urllib.error.HTTPError as e:
                    if e.code in (401,403,429):raise
        # Public product-family pages supplement sitemap and search discovery.
        family_pages={"www.elkjop.no":"https://www.elkjop.no/brand/apple/airpods/airpods-produkter","www.power.no":"https://www.power.no/apple/","eplehuset.no":"https://eplehuset.no/collections/airpods"}
        family=family_pages.get(host) or family_pages.get(host.removeprefix("www."))
        if "airpods" in terms and family and budget>3 and time.monotonic()<deadline-35 and rp.can_fetch(UA,family):
            budget-=1
            try:candidates.update(links(fetch(family,host,rp),family,host,q))
            except urllib.error.HTTPError as e:
                if e.code in (401,403,429):raise
        if not candidates:
            allowance=[min(5,max(0,budget-2))]
            before=allowance[0];pages=discover(host,rp,allowance);budget-=before-allowance[0]
            # Preserve URL discovery only; no prices collected for unrelated products.
            for i in range(0,len(pages),500):
                db("crawl_pages",{"on_conflict":"url"},"POST",[{"url":u,"host":host} for u in pages[i:i+500]],"resolution=ignore-duplicates,return=minimal")
            candidates.update(u for u in pages if matches(u,q))
        candidates.difference_update(api_urls)
        if not candidates and not found:detail="no matching product URLs"
        rejected=0
        for u in sorted(candidates,key=lambda u:(u not in known,-sum(t in u.lower() for t in terms),u))[:8]:
            if budget<=0 or time.monotonic()>deadline-20:break
            if not same_host(urllib.parse.urlsplit(u).hostname,host) or not rp.can_fetch(UA,u):continue
            budget-=1;count+=1
            try:
                raw=fetch(u,host,rp);offers=list(extract(raw,u,host))
                if not offers:
                    p=Page();p.feed(raw.decode("utf8","replace"))
                    if not any("Product" in types(x) for x in walk(p.scripts)):offers=microdata(raw,u,host,stamp())
                offers=[o for o in offers if offer_matches(o["name"],o.get("gtin"),o.get("model"),q)]
                if not offers:rejected+=1;continue
                persist_offers(host,q,offers)
                found+=len(offers);total+=len(offers)
            except urllib.error.HTTPError as e:
                if e.code in (401,403,429):detail=error_detail(e);break
                detail=error_detail(e)
        if rejected and not found and detail=="ok":detail="no matching structured NOK offers on "+str(rejected)+" pages"
    except Exception as e:detail=error_detail(e)
    finally:
        if detail in ("HTTP 401","HTTP 403","HTTP 429"):db("managed_stores",{"host":"eq."+host},"PATCH",{"paused_until":stamp(1)},"return=minimal")
        db("crawl_reports",None,"POST",{"host":host,"pages":count,"offers":found,"detail":detail},"return=minimal")
        db("search_store_checks",{"query":"eq."+q,"host":"eq."+host},"PATCH",{"checked":stamp(),"next_check":stamp(0.25 if found else 0.08),"status":"found" if found else "no_offer" if count and detail=="ok" else "incomplete","offers":found,"detail":detail},"return=minimal")
        print(host,count,found,detail,flush=True)
    return total
if __name__=="__main__":run()

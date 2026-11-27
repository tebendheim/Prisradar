"""Declarative adapters inferred from public storefront metadata; no generated code."""
import re,urllib.parse,urllib.error,urllib.robotparser,socket,ipaddress,time
from crawl import fetch,UA,error_detail,load_robots,same_host
from durable import db,stamp,can_start
from concurrent.futures import ThreadPoolExecutor
import threading
from discover_settings import discover_paths
from product_parser import Page,walk,types,gtin,price
from decimal import Decimal,InvalidOperation
from store_search import links,search_url
from search_adapters import API_ADAPTERS,detect_platform,DEFAULT_SEARCH,searchaction_path,opensearch_href,opensearch_path,api_search,woo_offer

def profile(raw,base):
    path,feeds=discover_paths(raw,base)
    html=raw.decode("utf8","replace")
    p=Page();p.feed(html)
    objects=list(walk(p.scripts))
    product=any("Product" in types(x) for x in objects)
    shop=product or bool(re.search(r"(?i)(add.to.cart|legg i handlekurv|shopping.cart|handlekurv)",html))
    platform=detect_platform(html)
    shop=shop or (platform!="generic" and bool(path))
    # Order: advertised search form, schema.org SearchAction, platform default. OpenSearch is resolved by the caller (needs a fetch).
    path=path or searchaction_path(objects,base) or DEFAULT_SEARCH.get(platform)
    text=re.sub(r'<[^>]+>',' ',html)
    vat="unknown"
    if re.search(r'(?i)(norsk merverdiavgift|norwegian vat|norsk mva|NO\s?\d{9}\s?MVA)',text):vat="norwegian_evidence"
    elif re.search(r'(?i)(inkl\.?\s*mva|inkludert merverdiavgift|inklusive moms|incl\.?\s*vat)',text):vat="vat_mentioned"
    currency="NOK" if any(x.get("priceCurrency")=="NOK" for x in objects) or re.search(r'(?i)\bNOK\b',text) else "unknown"
    return {"search_path":path,"feed_candidates":feeds,"adapter":platform,"vat_status":vat,"currency_hint":currency,"shop":shop,"opensearch":opensearch_href(html,base)}

MAX_STORES=2000
PROBE_WORKERS=12      # hard cap; each worker handles a different host (host_lock in crawl.fetch also serialises per host)
PROBE_BATCH=400       # candidates read per run; the deadline, not this number, normally ends the run
PROBE_MARGIN=35       # seconds kept free before the deadline (can_start adds the worst-case fetch time on top)
# Days until a candidate is probed again, by outcome. Non-stores and failures must not be re-probed daily.
RECHECK_DAYS={"active":90,"registered":90,"no storefront":30,"robots":30,"blocked":30,"rate limited":7,"error":14,"store limit":3}
HOST_RE=re.compile(r"(?=.{4,150}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}")

def host_variants(h):
    base=h.lower().removeprefix("www.")
    return [h,base,"www."+base]

def registered_hosts(hosts):
    """One batched lookup (50 hosts per call) instead of one query per candidate; matches www/bare variants."""
    found=set()
    for i in range(0,len(hosts),50):
        names=sorted({v for h in hosts[i:i+50] for v in host_variants(h)})
        try:
            for r in db("managed_stores",{"select":"host","host":"in.("+",".join(names)+")","limit":"1000"}) or []:
                found.add(r["host"].lower().removeprefix("www."))
        except Exception as e:print("Registered lookup skipped for a batch:",error_detail(e),flush=True)
    return found

LINK_ACTIVATIONS=10   # per run, for candidates that only come from links on other shops' pages
def is_link_source(src):
    """Curated (stores.txt) and BRREG candidates are trusted; anything else came from an outbound link."""
    src=str(src or "")
    return src.startswith(("http://","https://","link:")) and not src.startswith("https://data.brreg.no/")

def probe_one(h,registered,limit_state,source=""):
    """Return (result,days). Never raises. Every network call goes through crawl.fetch (robots, delay, host lock)."""
    try:
        if not HOST_RE.fullmatch(h) or not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)):raise ValueError("invalid host")
        if h.removeprefix("www.") in registered:return "already registered",RECHECK_DAYS["registered"]
        rp=load_robots(h,fetch)
        if not rp.can_fetch(UA,"https://"+h+"/"):return "robots restriction",RECHECK_DAYS["robots"]
        raw=fetch("https://"+h+"/",h,rp);p=profile(raw,"https://"+h+"/")
        # A search form alone is not proof of a shop.
        if not p["shop"]:return "no storefront evidence",RECHECK_DAYS["no storefront"]
        payload={k:p[k] for k in ("search_path","adapter","vat_status","currency_hint")}
        payload.update(host=h,enabled=True)
        # Check, cap and insert under one lock so MAX_STORES and the link cap are exact (the check re-reads the table).
        with limit_state["lock"]:
            if is_link_source(source) and limit_state["link"]>=LINK_ACTIVATIONS:return "link candidate cap reached",1
            # Once full, stays full for this run (no further queries); until then re-read so the cap is exact.
            if limit_state["full"] or db("managed_stores",{"select":"host","limit":"1","offset":str(MAX_STORES-1)}):
                limit_state["full"]=True;return "store limit reached",RECHECK_DAYS["store limit"]
            db("managed_stores",{"on_conflict":"host"},"POST",[payload],"resolution=ignore-duplicates,return=minimal")
            limit_state["activated"]+=1
            if is_link_source(source):limit_state["link"]+=1
        return "storefront detected; activated",RECHECK_DAYS["active"]
    except urllib.error.HTTPError as e:
        return error_detail(e),RECHECK_DAYS["blocked"] if e.code in (401,403) else RECHECK_DAYS["rate limited"] if e.code==429 else RECHECK_DAYS["error"]
    except Exception as e:return error_detail(e),RECHECK_DAYS["error"]

def probe_candidates(deadline,limit=None,workers=PROBE_WORKERS):
    """Time-boxed, parallel across DIFFERENT hosts. `limit` is kept for old callers and ignored: the deadline decides.
    Returns the number of candidates probed."""
    try:rows=db("store_candidates",{"select":"host,source","order":"probe_checked.asc.nullsfirst,host.asc","limit":str(PROBE_BATCH),"probe_next":"lte."+stamp()}) or []
    except Exception as e:
        print("Candidate read failed; nothing probed:",error_detail(e),flush=True);return 0
    seen=set();hosts=[];sources={}
    for r in rows:
        h=str(r.get("host","")).strip().lower()
        key=h.removeprefix("www.")
        if h and key not in seen:seen.add(key);hosts.append(h);sources[h]=r.get("source")   # one task per host (and per www/bare pair)
    if not hosts:return 0
    reg=registered_hosts([h for h in hosts if HOST_RE.fullmatch(h)])
    limit_state={"lock":threading.Lock(),"activated":0,"link":0,"full":False}
    def work(h):
        if not can_start(deadline,None,PROBE_MARGIN):return False   # not started; stays due for the next run
        result,days=probe_one(h,reg,limit_state,sources.get(h))
        patch={"probe_checked":stamp(),"probe_next":stamp(days),"probe_result":result}
        try:db("store_candidates",{"host":"eq."+h},"PATCH",patch,"return=minimal")
        except Exception as e:print("Candidate write failed",h,error_detail(e),flush=True)
        print("Candidate",h,result,flush=True)
        return True
    with ThreadPoolExecutor(max_workers=max(1,min(PROBE_WORKERS,workers))) as pool:
        done=sum(pool.map(work,hosts))
    print("Probed",done,"of",len(hosts),"candidates",flush=True)
    return done

def public_search(host,adapter,q,rp,fetcher=fetch,offers=None):
    """Only documented public storefront search endpoints; return product URLs, not guessed prices."""
    return api_search(host,adapter,q,rp,fetcher,offers)


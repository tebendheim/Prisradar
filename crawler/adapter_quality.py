"""Bounded adapter repair using known product identities, never generated code."""
import time,urllib.error
from crawl import fetch,load_robots,UA,extract,error_detail
from durable import db,stamp,words
from store_adapters import profile,public_search
from store_search import links,search_url
from product_parser import normalized_gtin

def verify_reference(offer,reference):
    code=normalized_gtin(reference.get("gtin"))
    if code:return normalized_gtin(offer.get("gtin"))==code and offer.get("price_kind","exact")=="exact"
    return bool(reference.get("name") and words(reference["name"])==words(offer["name"]))

def repair(host,config,references,deadline,fetcher=fetch,robots_loader=load_robots):
    """Only promote a discovered path after a real reference product is found and parsed."""
    if not references or time.monotonic()>deadline-35:return None,"no reference or time"
    rp=robots_loader(host,fetcher)
    root="https://"+host+"/"
    if not rp.can_fetch(UA,root):return None,"robots restriction"
    detected=profile(fetcher(root,host,rp),root)
    path=detected.get("search_path")
    if not path:return None,"no search path"
    reference=references[0]
    q=reference["name"]
    u=search_url(host,path,q)
    if not rp.can_fetch(UA,u):return None,"robots restriction"
    candidates=links(fetcher(u,host,rp),u,host,q)
    if detected["adapter"] in ("shopify","woocommerce") and not candidates and time.monotonic()<deadline-25:
        candidates=public_search(host,detected["adapter"],q,rp,fetcher)
    for candidate in candidates[:3]:
        if time.monotonic()>deadline-20:break
        if not rp.can_fetch(UA,candidate):continue
        offers=list(extract(fetcher(candidate,host,rp),candidate,host))
        if any(verify_reference(o,reference) for o in offers):
            return {k:detected[k] for k in ("search_path","adapter","vat_status","currency_hint")},"reference verified"
    return None,"reference not verified"

def run(deadline,limit=3):
    stores=db("managed_stores",{"enabled":"eq.true","select":"host,search_path,paused_until","limit":"500"})
    reports=db("crawl_reports",{"select":"host,detail,offers","order":"created.desc","limit":"500"})
    latest={}
    for row in reports:
        if not row["detail"].startswith(("catalogue","adapter audit")):latest.setdefault(row["host"],row)
    candidates=[s for s in stores if not s.get("paused_until") or s["paused_until"]<=stamp()]
    candidates=[s for s in candidates if s["host"] in latest and latest[s["host"]]["offers"]==0 and latest[s["host"]]["detail"] not in ("HTTP 401","HTTP 403","HTTP 429")]
    for store in candidates[:limit]:
        if time.monotonic()>deadline-35:break
        host=store["host"];detail="unverified"
        try:
            refs=db("offers",{"host":"eq."+host,"price_kind":"eq.exact","select":"name,gtin","order":"checked.desc","limit":"3"})
            patch,detail=repair(host,store,refs,deadline)
            if patch:db("managed_stores",{"host":"eq."+host,"enabled":"eq.true"},"PATCH",patch,"return=minimal")
        except Exception as e:
            detail=error_detail(e)
            if detail in ("HTTP 401","HTTP 403","HTTP 429"):db("managed_stores",{"host":"eq."+host},"PATCH",{"paused_until":stamp(1)},"return=minimal")
        db("crawl_reports",None,"POST",{"host":host,"pages":0,"offers":0,"detail":"adapter audit: "+detail},"return=minimal")
        print(host,"adapter audit:",detail,flush=True)

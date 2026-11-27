"""Declarative adapters inferred from public storefront metadata; no generated code."""
import re,urllib.parse,urllib.error,urllib.robotparser,socket,ipaddress,time
from crawl import fetch,UA,error_detail,load_robots,same_host
from durable import db,stamp
from discover_settings import discover_paths
from product_parser import Page,walk,types
from store_search import links,search_url

def profile(raw,base):
    path,feeds=discover_paths(raw,base)
    html=raw.decode("utf8","replace")
    p=Page();p.feed(html)
    objects=list(walk(p.scripts))
    product=any("Product" in types(x) for x in objects)
    shop=product or bool(re.search(r"(?i)(add.to.cart|legg i handlekurv|shopping.cart|handlekurv)",html))
    platform="generic"
    if re.search(r'cdn\.shopify\.com|Shopify\.shop',html,re.I):platform="shopify"
    elif re.search(r'woocommerce|wp-content/plugins/woocommerce',html,re.I):platform="woocommerce"
    shop=shop or (platform!="generic" and bool(path))
    if not path:
        if platform=="shopify":path="/search?q={q}&type=product"
        elif platform=="woocommerce":path="/?s={q}&post_type=product"
    text=re.sub(r'<[^>]+>',' ',html)
    vat="unknown"
    if re.search(r'(?i)(norsk merverdiavgift|norwegian vat|norsk mva|NO\s?\d{9}\s?MVA)',text):vat="norwegian_evidence"
    elif re.search(r'(?i)(inkl\.?\s*mva|inkludert merverdiavgift|inklusive moms|incl\.?\s*vat)',text):vat="vat_mentioned"
    currency="NOK" if any(x.get("priceCurrency")=="NOK" for x in objects) or re.search(r'(?i)\bNOK\b',text) else "unknown"
    return {"search_path":path,"feed_candidates":feeds,"adapter":platform,"vat_status":vat,"currency_hint":currency,"shop":shop}

def probe_candidates(deadline,limit=4):
    rows=db("store_candidates",{"select":"host,source","order":"probe_checked.asc.nullsfirst,host.asc","limit":str(limit),"probe_next":"lte."+stamp()})
    for row in rows:
        if time.monotonic()>deadline-35:break
        h=row["host"];result="unverified";patch={"probe_checked":stamp(),"probe_next":stamp(7)}
        try:
            if not re.fullmatch(r"(?=.{4,150}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}",h) or not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)):raise ValueError("invalid host")
            if db("managed_stores",{"host":"eq."+h,"select":"host","limit":"1"}):
                patch["probe_next"]=stamp(90);result="already registered";continue
            rp=load_robots(h,fetch)
            if not rp.can_fetch(UA,"https://"+h+"/"):
                result="robots restriction";continue
            raw=fetch("https://"+h+"/",h,rp);p=profile(raw,"https://"+h+"/")
            # A search form alone is not proof of a shop.
            if not p["shop"]:result="no storefront evidence";continue
            if db("managed_stores",{"select":"host","limit":"1","offset":"499"}):result="store limit reached";continue
            payload={k:p[k] for k in ("search_path","adapter","vat_status","currency_hint")}
            payload.update(host=h,enabled=True)
            db("managed_stores",{"on_conflict":"host"},"POST",[payload],"resolution=ignore-duplicates,return=minimal")
            result="storefront detected; activated";patch["probe_next"]=stamp(90)
        except Exception as e:result=error_detail(e)
        finally:
            patch["probe_result"]=result
            db("store_candidates",{"host":"eq."+h},"PATCH",patch,"return=minimal")
            print("Candidate",h,result,flush=True)

def public_search(host,adapter,q,rp,fetcher=fetch):
    """Only documented public storefront search endpoints; return product URLs, not guessed prices."""
    if adapter=="shopify":
        path="/search/suggest.json?"+urllib.parse.urlencode({"q":q,"resources[type]":"product","resources[limit]":10})
    elif adapter=="woocommerce":
        path="/wp-json/wc/store/v1/products?"+urllib.parse.urlencode({"search":q,"per_page":10})
    else:return []
    url="https://"+host+path
    if not rp.can_fetch(UA,url):return []
    import json
    try:
        data=json.loads(fetcher(url,host,rp))
        rows=data.get("resources",{}).get("results",{}).get("products",[]) if adapter=="shopify" else data
        if not isinstance(rows,list):return []
        result=[]
        for row in rows[:10]:
            if not isinstance(row,dict):continue
            u=urllib.parse.urlsplit(urllib.parse.urljoin(url,row.get("url") or row.get("permalink") or ""))
            if u.scheme=="https" and same_host(u.hostname,host) and not u.username and not u.password and u.port in (None,443) and u.path not in ("/",path) and rp.can_fetch(UA,u.geturl()):
                result.append(u._replace(fragment="").geturl())
        return list(dict.fromkeys(result))
    except (ValueError,AttributeError,TypeError):return []
    except urllib.error.HTTPError as e:
        if e.code in (401,403,429):raise
        return []

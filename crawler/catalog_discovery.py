"""Bounded catalogue maintenance: product metadata only, no price writes."""
import datetime,os,time,urllib.robotparser,urllib.error,urllib.parse,socket,ipaddress
from durable import db,discover,stamp
from crawl import fetch,UA,error_detail
from product_parser import Page,walk,types,same_page,gtin,product_hint
from merchant_feed import parse_feed,learn_assortment
from sources import candidate_hosts
from store_adapters import profile

def names(raw,url):
    p=Page();p.feed(raw.decode("utf8","replace"))
    products=[x for x in walk(p.scripts) if "Product" in types(x)]
    primary=[x for x in products if same_page(x.get("url"),url) or same_page(x.get("@id"),url)]
    if primary:products=primary
    elif len(products)!=1:products=[]
    for x in products:
        if x.get("url") and not same_page(x["url"],url):continue
        n=x.get("name")
        if isinstance(n,str) and 2<=len(n.strip())<=500:
            g=next((g for k in ("gtin13","gtin14","gtin12","gtin8","gtin") if (g:=gtin(x.get(k)))),None)
            yield {"n":n.strip(),"src":url,"g":g}
    if not products and p.meta.get("og:type","").lower() in ("product","product.item") and (not p.canonical or same_page(p.canonical,url)):
        n=p.meta.get("og:title")
        if n and 2<=len(n.strip())<=500:yield {"n":n.strip(),"src":url,"g":None}

def list_names(raw,url):
    """Only explicit structured Product entries with same-store product URLs."""
    p=Page();p.feed(raw.decode("utf8","replace"));seen=set()
    for x in walk(p.scripts):
        if "Product" not in types(x):continue
        n=x.get("name");u=x.get("url") or x.get("@id")
        if not isinstance(n,str) or not isinstance(u,str) or not 2<=len(n.strip())<=500:continue
        try:
            u=urllib.parse.urljoin(url,u);v=urllib.parse.urlsplit(u)
            if v.scheme!="https" or v.hostname!=urllib.parse.urlsplit(url).hostname or v.username or v.password or v.port not in (None,443) or not product_hint(u):continue
            u=v._replace(fragment="").geturl()
        except ValueError:continue
        g=next((g for k in ("gtin13","gtin14","gtin12","gtin8","gtin") if (g:=gtin(x.get(k)))),None)
        key=(n.strip(),g,u)
        if key not in seen:
            seen.add(key);yield {"n":n.strip(),"src":u,"g":g}

def learn_batch(products,host=None):
    rows=list({(x["n"],x["src"],x["g"]):x for x in products}.values())
    accepted=0
    for i in range(0,len(rows),100):
        n=db("rpc/learn_catalog_batch_v1",None,"POST",{"items":rows[i:i+100]})
        if host and n:db("rpc/index_store_products_v1",None,"POST",{"h":host,"items":rows[i:i+100]})
        accepted+=int(n or 0)
        if not n:break
    if host and accepted:learn_assortment(host,rows[:accepted])
    return accepted

def run(deadline=None,budget=45):
    deadline=deadline or time.monotonic()+300
    size=db("rpc/catalog_capacity_v1",None,"POST",{})
    if not size["allowed"]:
        print("Catalogue storage guard reached");return
    stores=db("managed_stores",{"enabled":"eq.true","select":"host,paused_until,feed_path,search_path","limit":"500","order":"host.asc"})
    now=datetime.datetime.now(datetime.timezone.utc)
    stores=[s for s in stores if not s["paused_until"] or datetime.datetime.fromisoformat(s["paused_until"])<=now]
    if not stores:return
    offset=int(os.environ.get("GITHUB_RUN_NUMBER",str(now.date().toordinal())))%len(stores)
    for s in (stores[offset:]+stores[:offset])[:8]:
        if budget<3 or time.monotonic()>deadline-30:break
        h=s["host"];count=found=0;detail="catalogue"
        try:
            if not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)):continue
            budget-=1;rp=urllib.robotparser.RobotFileParser()
            rp.parse(fetch("https://"+h+"/robots.txt",h).decode("utf8","replace").splitlines())
            if (rp.crawl_delay(UA) or rp.crawl_delay("*") or 0)>2 or rp.request_rate(UA) or rp.request_rate("*"):continue
            if s.get("feed_path") and budget>2 and time.monotonic()<deadline-45:
                u="https://"+h+s["feed_path"]
                if rp.can_fetch(UA,u):
                    budget-=1;count+=1
                    try:found+=learn_batch(list(parse_feed(fetch(u,h,rp),u))[:1000],h)
                    except urllib.error.HTTPError as e:
                        if e.code in (403,429):raise
                    except (ValueError,UnicodeError):pass
            if budget>2 and rp.can_fetch(UA,"https://"+h+"/"):
                budget-=1
                try:
                    raw=fetch("https://"+h+"/",h,rp);found+=learn_batch(list_names(raw,"https://"+h+"/"),h)
                    detected=profile(raw,"https://"+h+"/");path=detected["search_path"];feeds=detected["feed_candidates"]
                    patch={k:detected[k] for k in ("adapter","vat_status","currency_hint")}
                    if path and not s.get("search_path") and rp.can_fetch(UA,"https://"+h+path.replace("{q}","test")):patch["search_path"]=path
                    if not s.get("feed_path"):
                        for f in feeds:
                            if budget<3 or time.monotonic()>deadline-40:break
                            if not rp.can_fetch(UA,"https://"+h+f):continue
                            budget-=1
                            try:
                                items=list(parse_feed(fetch("https://"+h+f,h,rp),"https://"+h+f))[:1000]
                                if items:found+=learn_batch(items,h);patch["feed_path"]=f;break
                            except urllib.error.HTTPError as e:
                                if e.code in (403,429):raise
                            except (ValueError,UnicodeError):pass
                    if patch:db("managed_stores",{"host":"eq."+h},"PATCH",patch,"return=minimal")
                    candidates=[x for x in candidate_hosts(raw,"https://"+h+"/") if x.removeprefix("www.")!=h.removeprefix("www.")]
                    if candidates:db("store_candidates",{"on_conflict":"host"},"POST",[{"host":x,"source":"https://"+h+"/"} for x in candidates],"resolution=ignore-duplicates,return=minimal")
                    from store_search import Anchors
                    parser=Anchors();parser.feed(raw.decode("utf8","replace"));categories=[]
                    for href,_ in parser.rows:
                        u=urllib.parse.urljoin("https://"+h+"/",href);v=urllib.parse.urlsplit(u)
                        if v.scheme=="https" and v.hostname==h and not v.query and not v.fragment and not product_hint(u) and any(k in v.path.lower() for k in ("/kategori","/category","/collections/","/c/")) and rp.can_fetch(UA,u):categories.append(u)
                    for u in list(dict.fromkeys(categories))[:2]:
                        if budget<3 or time.monotonic()>deadline-30:break
                        budget-=1;count+=1;found+=learn_batch(list_names(fetch(u,h,rp),u),h)
                except urllib.error.HTTPError as e:
                    if e.code in (403,429):raise
            due=db("crawl_pages",{"host":"eq."+h,"next_check":"lte."+stamp(),"select":"url","order":"next_check.asc,url.asc","limit":"100"})
            if len(due)<15:
                b=[min(5,budget-1)];before=b[0];urls=discover(h,rp,b);budget-=before-b[0]
                urls=[u for u in urls if product_hint(u)][:5000]
                for i in range(0,len(urls),500):
                    if time.monotonic()>deadline-30:break
                    db("crawl_pages",{"on_conflict":"url"},"POST",[{"host":h,"url":u} for u in urls[i:i+500]],"resolution=ignore-duplicates,return=minimal")
                due=db("crawl_pages",{"host":"eq."+h,"next_check":"lte."+stamp(),"select":"url","order":"next_check.asc,url.asc","limit":"100"})
            for row in due[:max(1,min(15,budget))]:
                if budget<=0 or time.monotonic()>deadline-25:break
                u=row["url"]
                if urllib.parse.urlsplit(u).hostname!=h or not rp.can_fetch(UA,u):continue
                budget-=1;count+=1;outcome="catalogue:no name";days=30
                try:
                    products=list(names(fetch(u,h,rp),u))
                    found+=learn_batch(products,h)
                    if products:outcome="catalogue:name";days=90
                except urllib.error.HTTPError as e:
                    if e.code in (403,429):raise
                    outcome=error_detail(e);days=7
                except Exception as e:outcome=error_detail(e);days=7
                db("crawl_pages",{"url":"eq."+u},"PATCH",{"checked":stamp(),"outcome":outcome,"next_check":stamp(days)},"return=minimal")
        except Exception as e:
            detail=error_detail(e)
            if detail in ("HTTP 403","HTTP 429"):db("managed_stores",{"host":"eq."+h},"PATCH",{"paused_until":stamp(1)},"return=minimal")
        finally:
            db("crawl_reports",None,"POST",{"host":h,"pages":count,"offers":0,"detail":detail+"; product names: "+str(found)},"return=minimal")
            print(h,"catalogue pages",count,"names",found,detail,flush=True)
if __name__=="__main__":run()

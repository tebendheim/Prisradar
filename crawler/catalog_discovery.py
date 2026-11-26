"""Bounded catalogue maintenance: product metadata only, no price writes."""
import datetime,os,time,urllib.robotparser,urllib.error,urllib.parse,socket,ipaddress
from durable import db,discover,stamp
from crawl import fetch,UA,error_detail
from product_parser import Page,walk,types,same_page,gtin,product_hint

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

def run(deadline=None,budget=45):
    deadline=deadline or time.monotonic()+300
    size=db("rpc/catalog_capacity_v1",None,"POST",{})
    if not size["allowed"]:
        print("Catalogue storage guard reached");return
    stores=db("managed_stores",{"enabled":"eq.true","select":"host,paused_until","limit":"500","order":"host.asc"})
    now=datetime.datetime.now(datetime.timezone.utc)
    stores=[s for s in stores if not s["paused_until"] or datetime.datetime.fromisoformat(s["paused_until"])<=now]
    if not stores:return
    offset=(now.date().toordinal()*3)%len(stores)
    for s in (stores[offset:]+stores[:offset])[:3]:
        if budget<3 or time.monotonic()>deadline-30:break
        h=s["host"];count=found=0;detail="catalogue"
        try:
            if not all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(h,443,type=socket.SOCK_STREAM)):continue
            budget-=1;rp=urllib.robotparser.RobotFileParser()
            rp.parse(fetch("https://"+h+"/robots.txt",h).decode("utf8","replace").splitlines())
            if (rp.crawl_delay(UA) or rp.crawl_delay("*") or 0)>2 or rp.request_rate(UA) or rp.request_rate("*"):continue
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
                    for item in products:db("rpc/learn_catalog_v1",None,"POST",item)
                    found+=len(products)
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

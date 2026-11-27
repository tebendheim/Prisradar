"""Bounded, allowlisted crawl. No browser bypass, no paid search API."""
import os,json,time,re,gzip,io,urllib.request,urllib.error,urllib.parse,urllib.robotparser,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from collections import deque
from product_parser import parse, product_hint
import random
UA="PrisRadar/4.0 (private price research)"
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect())
def fetch(url,host,robots=None):
    for hop in range(4):
        try:return fetch_once(url,host,robots)
        except urllib.error.HTTPError as e:
            if e.code not in (301,302,303,307,308) or not e.headers.get("Location"):raise
            url=urllib.parse.urljoin(url,e.headers["Location"])
    raise ValueError("Too many redirects")
def fetch_once(url,host,robots=None):
    p=urllib.parse.urlsplit(url)
    if p.scheme!="https" or p.hostname not in (host,host.removeprefix("www."),"www."+host.removeprefix("www.")) or p.username or p.password or p.port not in (None,443): raise ValueError("URL not allowed")
    if robots is not None and (p.hostname!=host or not robots.can_fetch(UA,url)):raise ValueError("robots disallows URL")
    time.sleep(2)
    with opener.open(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=12) as r:
        raw=r.read(12000001)
        if len(raw)>12000000: raise ValueError("response too large")
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw=stream.read(12000001)
            if len(raw)>12000000: raise ValueError("decompressed response too large")
        return raw
def error_detail(e):
    return "HTTP "+str(e.code) if isinstance(e,urllib.error.HTTPError) else (type(e).__name__+": "+str(e)[:160] if isinstance(e,ValueError) else type(e).__name__)
def extract(raw,url,host):
    yield from parse(raw,url,host,time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
def coupon_extract(raw,host,url):
    class Visible(HTMLParser):
        def __init__(self):super().__init__();self.hidden=0;self.parts=[]
        def handle_starttag(self,t,a):
            if t in ("script","style"):self.hidden+=1
        def handle_endtag(self,t):
            if t in ("script","style"):self.hidden=max(0,self.hidden-1)
        def handle_data(self,s):
            if not self.hidden:self.parts.append(s)
    p=Visible();p.feed(raw.decode("utf8","replace"));text=" ".join(p.parts)
    for m in re.finditer(r"(?:rabattkode|kampanjekode|coupon code)\s*[:–=]?\s*([A-Z0-9][A-Z0-9_-]{3,24})\b",text):
        if m[1] in ("RABATT","KODE","BRUK","HER","NOK"):continue
        yield dict(host=host,code=m[1],source=url,context=text[max(0,m.start()-60):m.end()+90],status="discovered")
def send(table,rows,conflict):
    if not rows:return
    rows=list({tuple(r[k] for k in conflict.split(",")):r for r in rows}.values())
    base=os.environ["SUPABASE_URL"].rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co",base):raise ValueError("Invalid Supabase URL")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    req=urllib.request.Request(base+"/rest/v1/"+table+"?on_conflict="+conflict,data=json.dumps(rows).encode(),headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"},method="POST")
    with opener.open(req,timeout=20):pass
def run():
    hosts=[x.strip() for x in open("crawler/stores.txt") if x.strip() and not x.startswith("#")]
    offset=int(os.environ.get("STORE_OFFSET","0"))%len(hosts)
    budget=min(80,max(1,int(os.environ.get("PAGE_BUDGET","40"))))
    remaining_stores=min(4,len(hosts))
    offers=[];coupons=[]
    for host in (hosts[offset:]+hosts[:offset])[:4]:
        if budget<=0:break
        store_floor=max(0,budget-max(1,budget//remaining_stores))
        remaining_stores-=1
        root="https://"+host
        try:
            raw=fetch(root+"/robots.txt",host);rp=urllib.robotparser.RobotFileParser();rp.parse(raw.decode("utf8","replace").splitlines())
            if (rp.crawl_delay(UA) or rp.crawl_delay("*") or 0)>2 or rp.request_rate(UA) or rp.request_rate("*"):
                print(host,"skipped: robots rate limit");continue
            maps=deque(rp.site_maps() or [root+"/sitemap.xml"]);seen=set();pages=deque();maps_read=0
            while maps and maps_read<10 and budget>store_floor+3 and len(pages)<12000:
                url=maps.popleft()
                if url in seen or not rp.can_fetch(UA,url):continue
                seen.add(url);maps_read+=1;budget-=1
                try:
                    tree=ET.fromstring(fetch(url,host,rp))
                    locs=[n.text for n in tree.findall("./{*}*/{*}loc") if n.text]
                    if tree.tag.endswith("sitemapindex"):
                        locs.sort(key=lambda u:(not bool(re.search(r"product|produkt|vare",u,re.I)),bool(re.search(r"category|kategori|content|brand|merke",u,re.I))))
                        maps.extend(locs[:100])
                    else:
                        locs=[u for u in locs if urllib.parse.urlsplit(u).hostname==host]
                        locs.sort(key=lambda u: (not bool(re.search(r'airpods|headphone|hodetelefon',u,re.I)),not bool(re.search(r'produkt|product|/p/',u,re.I))))
                        pages.extend(locs[:12000])
                    print(host,"sitemap",len(locs),"links")
                except Exception as e:
                    print(host,"map skipped",error_detail(e))
                    if isinstance(e,urllib.error.HTTPError) and e.code in (403,429):raise
            if rp.can_fetch(UA,root+"/") and budget>store_floor+2:
                budget-=1
                try:coupons.extend(coupon_extract(fetch(root+"/",host,rp),host,root+"/"))
                except urllib.error.HTTPError as e:
                    if e.code in (403,429):raise
                except Exception:pass
            print(host,"candidate pages",len(pages))
            candidates=list(set(pages)); candidates.sort(); random.Random(int(os.environ.get("GITHUB_RUN_ID","0"))).shuffle(candidates)
            pages=deque(sorted(candidates,key=lambda u:(not product_hint(u),bool(re.search(r"/kategori/|/category/|/brand/|/merke/",u,re.I)))))
            count=0
            while pages and budget>store_floor and count<15:
                url=pages.popleft()
                if url in seen or not rp.can_fetch(UA,url):continue
                seen.add(url);budget-=1;count+=1
                try:
                    raw=fetch(url,host,rp);found=list(extract(raw,url,host));offers.extend(found);coupons.extend(coupon_extract(raw,host,url));print(host,"page products",len(found),urllib.parse.urlsplit(url).path[:180])
                except Exception as e:
                    print(host,"page skipped",error_detail(e))
                    if isinstance(e,urllib.error.HTTPError) and e.code in (403,429):break
        except Exception as e:print(host,"store skipped",error_detail(e))
    send("offers",offers,"url,name");send("coupons",coupons,"host,code,source");print("Offers:",len(offers),"Coupons:",len(coupons))
    if not offers: raise SystemExit("No products indexed; inspect store diagnostics")
if __name__=="__main__":run()

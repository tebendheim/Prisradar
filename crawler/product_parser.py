"""Conservative product parser: explicit NOK, no guessed prices or variants."""
import json,re,math
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
from decimal import Decimal,InvalidOperation

class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.meta={};self.scripts=[];self.active=False;self.parts=[];self.canonical=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="meta" and a.get("content"):
            k=a.get("property") or a.get("name") or a.get("itemprop")
            if k:self.meta.setdefault(k.lower(),a["content"])
        if tag=="link" and a.get("rel")=="canonical":self.canonical=a.get("href")
        if tag=="script" and a.get("type","").split(";")[0].strip().lower()=="application/ld+json":
            self.active=True;self.parts=[]
    def handle_data(self,s):
        if self.active:self.parts.append(s)
    def handle_endtag(self,tag):
        if tag=="script" and self.active:
            self.active=False
            try:self.scripts.append(json.loads("".join(self.parts)))
            except (ValueError,RecursionError):pass

def walk(x,depth=0):
    if depth>35:return
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v,depth+1)
    elif isinstance(x,list):
        for v in x:yield from walk(v,depth+1)

def types(x):
    t=x.get("@type",[])
    return {str(v).rstrip("/").split("/")[-1] for v in (t if isinstance(t,list) else [t])}

def price(x):
    if isinstance(x,bool) or x is None:return None
    s=str(x).strip().replace("\u00a0","").replace("\u202f","").replace(" ","")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}",s):s=s.replace(".","").replace(",",".")
    elif re.fullmatch(r"\d+,\d{1,2}",s):s=s.replace(",",".")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?",s):return None
    try:
        p=Decimal(s)
        return float(p) if 0<p<=10000000 else None
    except InvalidOperation:return None

def gtin(x):
    s=str(x or "")
    if not re.fullmatch(r"(?:\d{8}|\d{12,14})",s):return None
    return s if (sum(int(d)*(3 if i%2==0 else 1) for i,d in enumerate(reversed(s[:-1])))+int(s[-1]))%10==0 else None

def same_page(a,b):
    if not isinstance(a,str):return False
    p=urlsplit(urljoin(b,a));q=urlsplit(b)
    return p.scheme==q.scheme and p.hostname==q.hostname and p.path.rstrip("/")==q.path.rstrip("/")

def product_hint(url):
    p=urlsplit(url).path.lower()
    return bool(re.search(r"/(?:product|products|produkt|produkter|p)/[^/]+|/p-\d+|/p/\d+|/\d{5,}(?:/|$)",p))

def parse(raw,url,host,checked):
    p=Page();p.feed(raw.decode("utf8","replace"))
    objects=list(walk(p.scripts))
    refs={x["@id"]:x for x in objects if isinstance(x.get("@id"),str) and len(x)>1}
    def resolve(x):
        return refs.get(x.get("@id"),x) if isinstance(x,dict) and len(x)==1 else x
    products=[x for x in objects if "Product" in types(x)]
    # Prefer explicit page identity; never index recommendation carousels as the current product.
    primary=[x for x in products if same_page(x.get("url"),url) or same_page(x.get("@id"),url)]
    if primary:products=primary
    elif len(products)!=1:products=[]
    results=[]
    for item in products:
        name=item.get("name")
        if not isinstance(name,str) or not name.strip():continue
        if item.get("url") and not same_page(item["url"],url):continue
        offers=item.get("offers",[])
        if isinstance(offers,dict):offers=[offers]
        candidates=[]
        for o in offers:
            o=resolve(o)
            if not isinstance(o,dict) or "AggregateOffer" in types(o):continue
            if o.get("url") and not same_page(o["url"],url):continue
            if str(o.get("itemCondition","")).split("/")[-1] in ("UsedCondition","RefurbishedCondition","DamagedCondition"):continue
            val=price(o.get("price")) if str(o.get("priceCurrency","")).upper()=="NOK" else None
            if val is None:
                specs=o.get("priceSpecification",[])
                if isinstance(specs,dict):specs=[specs]
                for sp in specs:
                    sp=resolve(sp)
                    if not isinstance(sp,dict) or str(sp.get("priceCurrency","")).upper()!="NOK":continue
                    if sp.get("eligibleQuantity") or sp.get("validForMemberTier") or sp.get("priceType") or sp.get("billingDuration") or "UnitPriceSpecification" in types(sp):continue
                    val=price(sp.get("price"))
                    if val is not None:break
            if val is None or o.get("validForMemberTier") or o.get("eligibleQuantity"):continue
            candidates.append((val,str(o.get("availability","")).split("/")[-1]))
        if not candidates or len(set(candidates))!=1:continue
        val,availability=candidates[0]
        results.append(dict(url=url,name=name.strip()[:500],host=host,gtin=next((g for k in ("gtin13","gtin14","gtin12","gtin8","gtin") if (g:=gtin(item.get(k)))),None),model=str(item.get("mpn") or item.get("model") or "")[:200],price=val,shipping=None,availability=availability,checked=checked))
    if results:return results
    # Do not use metadata to override ambiguous or used structured offers.
    if products or any("Product" in types(x) for x in objects):return []
    m=p.meta
    if m.get("og:type","").lower() not in ("product","product.item") and not product_hint(url):return []
    if p.canonical and not same_page(p.canonical,url):return []
    if m.get("product:condition","").lower() in ("used","refurbished"):return []
    name=m.get("og:title") or m.get("name")
    currency=m.get("product:price:currency") or m.get("og:price:currency")
    val=price(m.get("product:price:amount") or m.get("og:price:amount"))
    if name and val is not None and str(currency).upper()=="NOK":
        return [dict(url=url,name=name[:500],host=host,gtin=None,model="",price=val,shipping=None,availability=m.get("product:availability",""),checked=checked)]
    return []

"""Conservative product parser: explicit NOK, no guessed prices or variants."""
import json,re,math
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
from decimal import Decimal,InvalidOperation

def json_documents(raw):
    text=raw.strip().removeprefix("<!--").removesuffix("-->").strip()
    decoder=json.JSONDecoder()
    # Remove trailing commas outside JSON strings only.
    text=re.sub(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',lambda m:m.group() if m.group().startswith('"') else "",text)
    while text:
        try:obj,end=decoder.raw_decode(text)
        except (ValueError,RecursionError):break
        yield obj
        text=text[end:].lstrip(" \r\n\t;")

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
            self.scripts.extend(json_documents("".join(self.parts)))

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
    if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{12,14})",s) or not s.strip("0"):return None
    return s if (sum(int(d)*(3 if i%2==0 else 1) for i,d in enumerate(reversed(s[:-1])))+int(s[-1]))%10==0 else None

def normalized_gtin(x):
    g=gtin(x)
    return g.zfill(14) if g else None

def same_page(a,b):
    if not isinstance(a,str):return False
    p=urlsplit(urljoin(b,a));q=urlsplit(b)
    return p.scheme==q.scheme and (p.hostname or "").removeprefix("www.")== (q.hostname or "").removeprefix("www.") and p.path.rstrip("/")==q.path.rstrip("/")

def product_hint(url):
    p=urlsplit(url).path.lower()
    return bool(re.search(r"/(?:product|products|produkt|produkter|p)/[^/]+|/p-\d+|/p/\d+|/\d{5,}(?:/|$)|/[^/]+\.html$",p))

def documented_shipping(offer):
    """Only unconditional flat NOK shipping explicitly applicable to Norway."""
    rows=offer.get("shippingDetails",[])
    if isinstance(rows,dict):rows=[rows]
    values=[]
    if not isinstance(rows,list):return None
    for row in rows:
        if not isinstance(row,dict):return None
        dest=row.get("shippingDestination",{})
        if not isinstance(dest,dict) or dest.get("addressCountry")!="NO" or any(dest.get(k) for k in ("addressRegion","postalCode","postalCodeRange")):return None
        if any(row.get(k) for k in ("eligibleTransactionVolume","shippingRateSettings","doesNotShip","validForMemberTier")):return None
        rate=row.get("shippingRate",{})
        if not isinstance(rate,dict) or rate.get("currency")!="NOK":return None
        value=rate.get("value")
        if any(rate.get(k) is not None for k in ("minValue","maxValue")):return None
        val=0 if str(value) in ("0","0.0","0.00") else price(value)
        if val is None:return None
        values.append(val)
    return values[0] if values and len(set(values))==1 else None

def conditional_prices(raw,url):
    """Document member offers separately; never substitute for public prices."""
    p=Page();p.feed(raw.decode("utf8","replace"))
    for item in walk(p.scripts):
        if "Product" not in types(item) or not same_page(item.get("url") or item.get("@id"),url):continue
        offers=item.get("offers",[])
        if isinstance(offers,dict):offers=[offers]
        if not isinstance(offers,list):continue
        for o in offers:
            if not isinstance(o,dict) or not o.get("validForMemberTier") or o.get("eligibleQuantity"):continue
            if o.get("priceCurrency")!="NOK":continue
            val=price(o.get("price"))
            tier=o["validForMemberTier"]
            if isinstance(tier,dict):tier=tier.get("name") or tier.get("@id")
            if val is not None and isinstance(tier,str) and tier.strip():
                yield {"name":str(item.get("name",""))[:500],"price":val,"condition":tier[:300],"source":url}

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
        inherited=item.get("priceCurrency") or p.meta.get("product:price:currency") or p.meta.get("og:price:currency")
        expanded=[]
        for o in offers:
            o=resolve(o)
            if not isinstance(o,dict):continue
            if "AggregateOffer" in types(o):
                nested=o.get("offers",[])
                if isinstance(nested,dict):nested=[nested]
                if nested:
                    for child in nested:
                        child=resolve(child)
                        if isinstance(child,dict):expanded.append(({**o,**child},False))
                elif o.get("lowPrice") is not None:expanded.append(({**o,"price":o["lowPrice"]},True))
            else:expanded.append((o,False))
        for o,aggregate in expanded:
            if o.get("url") and not same_page(o["url"],url):continue
            if str(o.get("itemCondition","")).split("/")[-1] in ("UsedCondition","RefurbishedCondition","DamagedCondition"):continue
            val=price(o.get("price")) if str(o.get("priceCurrency") or inherited or "").upper()=="NOK" else None
            if val is None:
                specs=o.get("priceSpecification",[])
                if isinstance(specs,dict):specs=[specs]
                for sp in specs:
                    sp=resolve(sp)
                    if not isinstance(sp,dict) or str(sp.get("priceCurrency") or o.get("priceCurrency") or inherited or "").upper()!="NOK":continue
                    if sp.get("eligibleQuantity") or sp.get("validForMemberTier") or sp.get("priceType") or sp.get("billingDuration") or "UnitPriceSpecification" in types(sp):continue
                    val=price(sp.get("price"))
                    if val is not None:break
            if val is None or o.get("validForMemberTier") or o.get("eligibleQuantity"):continue
            candidates.append((val,"AggregatePrice" if aggregate else str(o.get("availability","")).split("/")[-1],aggregate,documented_shipping(o)))
        if not candidates:continue
        # A lowPrice alone is only a from-price, never a verified in-stock variant.
        in_stock=[c for c in candidates if c[1]=="InStock" and not c[2]]
        val,availability,aggregate,shipping=min(in_stock or candidates,key=lambda c:c[0])
        kind="from" if len(set(candidates))>1 or aggregate else "exact"
        brand=item.get("brand");brand=brand.get("name") if isinstance(brand,dict) else brand
        results.append(dict(brand=brand[:200] if isinstance(brand,str) else None,mpn=item.get("mpn")[:200] if kind=="exact" and isinstance(item.get("mpn"),str) else None,url=url,name=name.strip()[:500],host=host,gtin=None if len(set(candidates))>1 or aggregate else next((g for k in ("gtin13","gtin14","gtin12","gtin8","gtin") if (g:=gtin(item.get(k)))),None),model=str(item.get("mpn") or item.get("model") or "")[:200],price=val,price_kind=kind,shipping=shipping if kind=="exact" else None,availability=availability,checked=checked))
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
        return [dict(url=url,name=name[:500],host=host,gtin=None,model="",price=val,price_kind="exact",shipping=None,availability=m.get("product:availability",""),checked=checked)]
    return []

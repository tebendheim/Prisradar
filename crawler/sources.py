"""Additional extraction sources. Only explicit product identity and NOK prices."""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin
import re
from product_parser import price,gtin,same_page

class Microdata(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.products=[]
    def handle_starttag(self,t,attrs):
        a=dict(attrs);parent=self.stack[-1][1] if self.stack else None
        scope=parent
        if "itemscope" in a:
            scope={"type":a.get("itemtype","").split("/")[-1],"fields":{}}
            if scope["type"]=="Product":self.products.append(scope)
            if parent and a.get("itemprop"):parent["fields"].setdefault(a["itemprop"],[]).append(scope)
        field=a.get("itemprop");value=a.get("content") or a.get("href") or a.get("value")
        if field and scope is parent and scope is not None and value:scope["fields"].setdefault(field,[]).append(value)
        if t not in ("area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"):self.stack.append((t,scope,field if not value and scope is parent else None,[]))
    def handle_data(self,s):
        for row in self.stack:
            if row[2]:row[3].append(s)
    def handle_endtag(self,t):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==t:
                for _,scope,field,parts in self.stack[i:]:
                    if scope and field and parts:scope["fields"].setdefault(field,[]).append(" ".join(parts).strip())
                del self.stack[i:];break

def one(scope,k):
    v=[x for x in scope["fields"].get(k,[]) if isinstance(x,str) and x.strip()]
    return v[0] if len(set(v))==1 else None

def microdata(raw,url,host,checked):
    p=Microdata();p.feed(raw.decode("utf8","replace"))
    if len(p.products)!=1:return []
    item=p.products[0];name=one(item,"name")
    if not name:return []
    u=one(item,"url")
    if u and not same_page(u,url):return []
    offers=item["fields"].get("offers",[])
    if len(offers)!=1 or not isinstance(offers[0],dict) or offers[0]["type"]!="Offer":return []
    o=offers[0]
    if one(o,"priceCurrency")!="NOK" or o["fields"].get("validForMemberTier") or o["fields"].get("eligibleQuantity"):return []
    condition=one(o,"itemCondition") or one(item,"itemCondition") or ""
    if condition and condition.split("/")[-1]!="NewCondition":return []
    val=price(one(o,"price"))
    if val is None:return []
    ou=one(o,"url")
    if ou and not same_page(ou,url):return []
    return [dict(url=url,name=name[:500],host=host,gtin=next((g for k in ("gtin13","gtin14","gtin12","gtin8","gtin") if (g:=gtin(one(item,k)))),None),model=(one(item,"mpn") or one(item,"model") or "")[:200],price=val,shipping=None,availability=(one(o,"availability") or "").split("/")[-1],checked=checked)]

class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[]
    def handle_starttag(self,t,a):
        if t=="a" and dict(a).get("href"):self.links.append(dict(a)["href"])
def candidate_hosts(raw,url):
    """Discovery only; candidates are never fetched without review."""
    p=Links();p.feed(raw.decode("utf8","replace"));origin=urlsplit(url).hostname
    hosts=set()
    for link in p.links:
        try:
            u=urlsplit(urljoin(url,link));h=u.hostname
            if u.scheme=="https" and h and h.endswith(".no") and h!=origin and len(h)<150 and not u.username and not u.password and u.port in (None,443):
                hosts.add(h)
        except ValueError:pass
    return sorted(hosts)[:20]

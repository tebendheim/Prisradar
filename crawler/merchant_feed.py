"""Explicitly configured public merchant feeds. Never guess feed endpoints."""
import csv,io,xml.etree.ElementTree as ET
import urllib.error
from urllib.parse import urljoin,urlsplit
from product_parser import gtin,price
from crawl import same_host
import re
from store_rank import categories
from durable import db,stamp
from collections import Counter,OrderedDict
from threading import Lock
import time
_feed_cache=OrderedDict()
_feed_lock=Lock()
_feed_locks={}

def cached_feed(url,host,rp,fetcher):
    """Bounded per-process cache; serialize downloads of the same feed."""
    with _feed_lock:lock=_feed_locks.setdefault(url,Lock())
    with lock:
        with _feed_lock:
            hit=_feed_cache.get(url)
            if hit and time.monotonic()-hit[0]<900:
                _feed_cache.move_to_end(url);return hit[1]
        items=tuple(parse_feed(fetcher(url,host,rp),url))
        with _feed_lock:
            _feed_cache[url]=(time.monotonic(),items);_feed_cache.move_to_end(url)
            while len(_feed_cache)>8:_feed_cache.popitem(last=False)
        return items

def clean(row,base):
    name=row.get("title") or row.get("name");link=row.get("link") or row.get("url")
    if not isinstance(name,str) or not isinstance(link,str) or not 2<=len(name.strip())<=500:return None
    try:
        url=urljoin(base,link);u=urlsplit(url)
        if u.scheme!="https" or not same_host(u.hostname,urlsplit(base).hostname) or u.username or u.password or u.port not in (None,443):return None
    except ValueError:return None
    result={"n":name.strip(),"src":u._replace(fragment="").geturl(),"g":gtin(row.get("gtin"))}
    def nok(value):
        m=re.fullmatch(r"\s*(.*?)\s+NOK\s*",str(value or ""),re.I)
        if m:return price(m.group(1))
        if str(row.get("currency") or row.get("price_currency") or "").upper()=="NOK":return price(value)
        return None
    regular=nok(row.get("price"))
    sale=nok(row.get("sale_price"))
    condition=str(row.get("condition") or "").lower()
    if regular is not None and condition not in ("used","refurbished","damaged"):
        result["price"]=regular
        # A sale date range must be verified before using sale_price.
        if sale is not None:result["sale_price"]=sale
        result["availability"]={"in_stock":"InStock","out_of_stock":"OutOfStock","preorder":"PreOrder","backorder":"BackOrder"}.get(str(row.get("availability") or "").lower().replace(" ","_"),"")
    return result

def parse_feed(raw,base):
    text=raw.decode("utf-8-sig","replace")
    if text.lstrip().startswith("<"):
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():raise ValueError("XML declarations not supported")
        root=ET.fromstring(text)
        rows=({c.tag.split("}")[-1]:c.text for c in item} for item in root.iter() if item.tag.split("}")[-1] in ("item","entry","product"))
    else:
        rows=csv.DictReader(io.StringIO(text),delimiter="\t" if "\t" in text.partition("\n")[0] else ",")
    for i,row in enumerate(rows):
        if i>=10000:break
        item=clean(row,base)
        if item:yield item

def learn_assortment(host,items):
    counts=Counter(c for item in items for c in categories(item["n"]))
    if counts:
        try:db("rpc/record_assortment_v1",None,"POST",{"h":host,"counts":dict(counts)})
        except urllib.error.HTTPError as e:
            if e.code != 404:raise
            print("WARNING: assortment learning unavailable; price data retained",flush=True)

def feed_offers(items,host,query_matches):
    """Price storage remains demand-driven: never import every feed price."""
    for item in items:
        if item.get("price") is None or not query_matches(item):continue
        if not same_host(urlsplit(item["src"]).hostname,host):continue
        yield dict(url=item["src"],name=item["n"],host=host,gtin=item.get("g"),model="",price=item["price"],price_kind="exact",shipping=None,availability=item.get("availability",""),checked=stamp())

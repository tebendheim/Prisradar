"""Approved external feeds, configured in a private Actions secret.
Never follow tracking URLs or discover credential-bearing feeds automatically.
"""
import os,json,re,urllib.parse
from crawl import fetch,load_robots,same_host,UA
from merchant_feed import parse_feed,feed_offers
from collections import OrderedDict

_cache=OrderedDict()
def configurations():
    raw=os.environ.get("AFFILIATE_FEEDS_JSON","")
    if not raw:return {}
    try:data=json.loads(raw)
    except ValueError:raise ValueError("Invalid affiliate feed configuration") from None
    if not isinstance(data,dict) or len(data)>50:raise ValueError("Invalid affiliate feed configuration")
    return data

def approved_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!="https" or not p.hostname or p.username or p.password or p.port not in (None,443) or p.fragment:
        raise ValueError("Invalid approved feed URL")
    return p

def affiliate_items(host,fetcher=fetch,robots_loader=load_robots):
    cfg=configurations().get(host.removeprefix("www."))
    if not cfg:return ()
    if not isinstance(cfg,dict) or cfg.get("provider") not in ("adtraction","awin","partner-ads","merchant"):raise ValueError("Unknown approved feed provider")
    url=cfg.get("url")
    p=approved_url(url)
    # The private configuration must explicitly name the feed host.
    if p.hostname!=cfg.get("feed_host"):raise ValueError("Feed host mismatch")
    if host in _cache:return _cache[host]
    rp=robots_loader(p.hostname)
    if not rp.can_fetch(UA,url):raise ValueError("Affiliate feed disallowed")
    try:
        raw=fetcher(url,p.hostname,rp)
        items=tuple(parse_feed(raw,url,merchant_host=host))
    except Exception as e:
        # Never include secret URLs, query strings or response bodies in logs.
        raise ValueError("Affiliate feed fetch or parse failed: "+type(e).__name__) from None
    _cache[host]=items
    while len(_cache)>8:_cache.popitem(last=False)
    return items

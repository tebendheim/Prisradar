"""Discover advertised GET search forms and explicitly linked public product feeds."""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,urlencode
import re
from crawl import same_host
class Discovery(HTMLParser):
    def __init__(self):
        super().__init__();self.form=None;self.paths=[];self.feeds=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="form":
            self.form={"action":a.get("action") or "", "method":(a.get("method") or "get").lower(),"inputs":[],"search":a.get("role")=="search"}
        if tag=="input" and self.form is not None:
            name=a.get("name");typ=(a.get("type") or "text").lower()
            if name and typ not in ("password","file") and "disabled" not in a:
                self.form["inputs"].append((name,typ,a.get("value") or ""))
        if tag in ("link","a"):
            href=a.get("href") or "";typ=a.get("type") or "";rel=a.get("rel") or ""
            if href and ("product" in href.lower() or "merchant" in href.lower()) and (re.search(r"\.(xml|csv|tsv)(?:\?|$)",href,re.I) or ("alternate" in rel and typ in ("text/csv","application/rss+xml"))):
                self.feeds.append(href)
    def handle_endtag(self,tag):
        if tag=="form" and self.form is not None:
            f=self.form;self.form=None
            if f["method"]!="get" or any(t in ("password","file") for _,t,_ in f["inputs"]):return
            for n,t,v in f["inputs"]:
                if t=="search" or (t=="text" and (f["search"] or n.lower() in ("q","query","search","searchterm","keyword","s"))):
                    self.paths.append((f["action"],n,[(k,v) for k,t,v in f["inputs"] if t=="hidden" and k!=n and k.lower() not in ("token","csrf","auth","session")]))
                    break
def safe_relative(base,href):
    try:
        u=urlsplit(urljoin(base,href))
        if u.scheme!="https" or not same_host(u.hostname,urlsplit(base).hostname) or u.username or u.password or u.port not in (None,443):return None
        p=u.path or "/"
        if p.startswith("//") or "\\" in p:return None
        return p+("?" +u.query if u.query else "")
    except ValueError:return None
def discover_paths(raw,base):
    p=Discovery();p.feed(raw.decode("utf8","replace"))
    search=None
    for action,name,hidden in p.paths:
        path=safe_relative(base,action)
        if path is None:continue
        # Do not replay arbitrary hidden values; only public search input.
        path=path+("&" if "?" in path else "?")+urlencode({name:"{q}"}).replace("%7Bq%7D","{q}")
        if len(path)<=300:search=path;break
    feeds=list(dict.fromkeys(x for href in p.feeds if (x:=safe_relative(base,href)) and len(x)<=1000))
    return search,feeds[:3]

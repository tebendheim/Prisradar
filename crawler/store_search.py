"""Public search-page discovery. No private APIs or challenge bypass."""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,quote
from product_parser import product_hint
from durable import words
from crawl import same_host
import re
class Anchors(HTMLParser):
    def __init__(self):
        super().__init__();self.current=None;self.rows=[]
    def handle_starttag(self,t,a):
        if t=="a":
            if self.current:self.rows.append(self.current)
            self.current=[dict(a).get("href",""),[]]
    def handle_data(self,s):
        if self.current:self.current[1].append(s)
    def handle_endtag(self,t):
        if t=="a" and self.current:self.rows.append(self.current);self.current=None
def search_url(host,path,q):
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or "{q}" not in path:raise ValueError("invalid search path")
    return "https://"+host+path.replace("{q}",quote(q,safe=""))
def links(raw,url,host,q):
    parser=Anchors();parser.feed(raw.decode("utf8","replace"))
    out={}
    terms=set(words(q))
    for href,parts in parser.rows:
        try:
            u=urlsplit(urljoin(url,href))
            if u.scheme!="https" or not same_host(u.hostname,host) or u.username or u.password or u.port not in (None,443):continue
            if not product_hint(u.geturl()):continue
            tokens=set(words(u.path+" "+" ".join(parts)))
            score=len(terms & tokens)
            if score>=max(1,len(terms)-1):
                clean=u._replace(fragment="").geturl()
                out[clean]=max(score,out.get(clean,0))
        except ValueError:continue
    return sorted(out,key=lambda u:(-out[u],u))[:12]

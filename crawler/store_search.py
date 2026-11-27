"""Public search-page discovery. No private APIs or challenge bypass."""
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,quote,unquote
from product_parser import product_hint,matched_terms
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
# Path segments that mark listing/info pages; slug-only product links are never taken from these.
NOT_PRODUCT={"search","sok","s\u00f8k","kategori","category","categories","blog","blogg","nyheter","news","kundeservice","customer-service","om-oss","about","kontakt","contact","cart","handlekurv","checkout","login","account","brand","brands","merke","merker","tag","tags","collections","guide","guider","artikler","articles"}
def links(raw,url,host,q):
    """Product links from a search page. Links with a product-like path are scored by matching terms; slug-only
    links (no /product/ style segment, common in Norwegian shops) need nearly all terms in the path itself."""
    parser=Anchors();parser.feed(raw.decode("utf8","replace"))
    out={}
    terms=list(dict.fromkeys(words(q)))
    for href,parts in parser.rows:
        try:
            u=urlsplit(urljoin(url,href))
            if u.scheme!="https" or not same_host(u.hostname,host) or u.username or u.password or u.port not in (None,443):continue
            hinted=product_hint(u.geturl())
            path_tokens=words(unquote(u.path))
            if not hinted:
                segs=[x for x in u.path.lower().split("/") if x]
                if not segs or any(x in NOT_PRODUCT for x in segs) or u.path.rstrip("/")==urlsplit(url).path.rstrip("/"):continue
                got=matched_terms(terms,path_tokens)
                # Every model-number term (anything with a digit) must be in the slug itself.
                if len(got)<max(1,len(terms)-1) or len(path_tokens)<2 or any(t not in got for t in terms if re.search(r"\d",t)):continue
            score=len(matched_terms(terms,words(u.path+" "+" ".join(parts))))
            if score>=max(1,len(terms)-1):
                clean=u._replace(fragment="").geturl()
                out[clean]=(max(score,out.get(clean,(0,0))[0]),hinted)
        except ValueError:continue
    return sorted(out,key=lambda u:(-out[u][0],not out[u][1],u))[:12]

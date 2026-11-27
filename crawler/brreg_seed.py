"""Bounded candidate discovery from the public Norwegian business register."""
import json,os,re
from urllib.parse import urlsplit,urlencode
from crawl import fetch
from durable import db
HOST="data.brreg.no"
BASE="https://"+HOST+"/enhetsregisteret/api/enheter"
def normalize_site(value):
    if not isinstance(value,str) or not value.strip():return None
    value=value.strip()
    try:
        p=urlsplit(value if "://" in value else "https://"+value)
        h=(p.hostname or "").lower().rstrip(".").removeprefix("www.")
        if p.scheme not in ("http","https") or p.username or p.password or p.port not in (None,80,443):return None
        if not re.fullmatch(r"(?=.{4,150}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}",h):return None
        if h in ("facebook.com","instagram.com","linkedin.com","tiktok.com","youtube.com","linktr.ee") or h.endswith((".facebook.com",".instagram.com",".linkedin.com")):return None
        return h
    except ValueError:return None
def rows_from_response(data):
    rows=data.get("_embedded",{}).get("enheter",[])
    result={}
    for r in rows:
        if r.get("konkurs") or r.get("underAvvikling"):continue
        h=normalize_site(r.get("hjemmeside"))
        if h:result[h]={"host":h,"source":BASE}
    return list(result.values())
def run():
    # BRREG pagination is bounded; rotate pages rather than repeatedly import page zero.
    from crawl import load_robots
    rp=load_robots(HOST)
    args={"naeringskode":"47","konkurs":"false","underAvvikling":"false","size":100}
    data=json.loads(fetch(BASE+"?"+urlencode({**args,"page":0}),HOST,rp))
    pages=min(100,int(data.get("page",{}).get("totalPages",1)))
    if pages<1:return
    start=int(os.environ.get("GITHUB_RUN_NUMBER","0"))*3%pages
    total=0
    for page in [(start+i)%pages for i in range(min(3,pages))]:
        d=data if page==0 else json.loads(fetch(BASE+"?"+urlencode({**args,"page":page}),HOST,rp))
        rows=rows_from_response(d)
        if rows:
            db("store_candidates",{"on_conflict":"host"},"POST",rows,"resolution=ignore-duplicates,return=minimal")
            total+=len(rows)
    print("BRREG candidate rows submitted:",total,flush=True)
if __name__=="__main__":run()

"""Bounded candidate discovery from the public Norwegian business register."""
import json,os,re
from urllib.parse import urlsplit,urlencode,urljoin
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
def run(deadline=None):
    # BRREG pagination is bounded; rotate pages rather than repeatedly import page zero.
    from crawl import load_robots
    rp=load_robots(HOST)
    args={"naeringskode":"47","konkurs":"false","underAvvikling":"false","size":100}
    data=json.loads(fetch(BASE+"?"+urlencode({**args,"page":0}),HOST,rp))
    pages=min(100,int(data.get("page",{}).get("totalPages",1)))
    if pages<1:return
    start=int(os.environ.get("GITHUB_RUN_NUMBER","0"))*3%pages
    total=0
    import time
    for page in [(start+i)%pages for i in range(min(3,pages))]:
        if deadline is not None and time.monotonic()+14>deadline:print("BRREG: deadline reached",flush=True);break
        d=data if page==0 else json.loads(fetch(BASE+"?"+urlencode({**args,"page":page}),HOST,rp))
        rows=rows_from_response(d)
        if rows:
            db("store_candidates",{"on_conflict":"host"},"POST",rows,"resolution=ignore-duplicates,return=minimal")
            total+=len(rows)
    print("BRREG candidate rows submitted:",total,flush=True)

# Hosts that are linked from many shops but are never shops themselves (carriers, payment, public bodies, social).
NOISE=frozenset("posten.no bring.no klarna.com vipps.no nets.no schibsted.no forbrukerradet.no forbrukertilsynet.no brreg.no regjeringen.no skatteetaten.no google.com apple.com microsoft.com facebook.com trustpilot.com bring.com postnord.no helthjem.no instabox.no schenker.no ehandel.no norgesbank.no finansportalen.no personvernbloggen.no datatilsynet.no mattilsynet.no lovdata.no nkom.no".split())
def curated_hosts(text):
    """stores.txt: one host per line, '#' starts a comment, 'www.' optional. Invalid lines are skipped."""
    out={}
    for line in text.splitlines():
        h=normalize_site(line.split("#")[0].strip())
        if h and h not in NOISE:out[h]=None
    return list(out)
def seed_curated(path=None):
    """Curated list -> store_candidates (ignore-duplicates: never resets probe state of known hosts). Probing verifies them."""
    path=path or os.path.join(os.path.dirname(os.path.abspath(__file__)),"stores.txt")
    with open(path,encoding="utf8") as f:hosts=curated_hosts(f.read())
    for i in range(0,len(hosts),200):
        db("store_candidates",{"on_conflict":"host"},"POST",[{"host":h,"source":"crawler/stores.txt"} for h in hosts[i:i+200]],"resolution=ignore-duplicates,return=minimal")
    print("Curated candidate rows submitted:",len(hosts),flush=True)
    return len(hosts)
def linked_hosts(raw,url):
    """Outbound .no links on a page, normalised, excluding the page's own host and known non-shop hosts."""
    from sources import Links
    p=Links();p.feed(raw.decode("utf8","replace"));own=(urlsplit(url).hostname or "").removeprefix("www.");found={}
    for link in p.links:
        try:u=urlsplit(urljoin(url,link))
        except ValueError:continue
        if u.scheme!="https":continue
        h=normalize_site(u.geturl())
        if h and h.endswith(".no") and h!=own and h not in NOISE and not h.endswith(".gov.no"):found[h]=None
    return list(found)[:40]
def seed_from_active(budget_seconds=40,max_stores=12,deadline=None):
    """Front pages of enabled stores (rotating subset per run) -> linked shops as candidates. Uses fetch(): robots/delay respected."""
    import time
    from crawl import load_robots,UA
    stores=db("managed_stores",{"select":"host","enabled":"eq.true","order":"host.asc","limit":"500"}) or []
    if not stores:return 0
    start=int(os.environ.get("GITHUB_RUN_NUMBER","0"))*max_stores%len(stores)
    end=time.monotonic()+budget_seconds
    if deadline is not None:end=min(end,deadline)
    total=0
    for s in [stores[(start+i)%len(stores)] for i in range(min(max_stores,len(stores)))]:
        if time.monotonic()+28>end:break   # robots.txt + front page, each at most ~14 s
        h=s["host"]
        try:
            rp=load_robots(h,fetch)
            if not rp.can_fetch(UA,"https://"+h+"/"):continue
            hosts=linked_hosts(fetch("https://"+h+"/",h,rp),"https://"+h+"/")
        except Exception as e:
            print("Link source skipped",h,type(e).__name__,flush=True)
            continue
        if hosts:
            db("store_candidates",{"on_conflict":"host"},"POST",[{"host":x,"source":"https://"+h+"/"} for x in hosts],"resolution=ignore-duplicates,return=minimal");total+=len(hosts)
    print("Linked candidate rows submitted:",total,flush=True)
    return total
if __name__=="__main__":
    import discovery_job;discovery_job.main()

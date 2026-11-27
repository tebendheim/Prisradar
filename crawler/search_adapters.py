"""Platform detection and public search endpoints that shops expose to every browser.
Only robots.txt-permitted GET requests; prices are used only when the response states NOK explicitly."""
import json,re,urllib.parse,urllib.error
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from html import unescape
from decimal import Decimal,InvalidOperation
from crawl import UA,same_host
from durable import stamp
from product_parser import price,gtin
from discover_settings import safe_relative

# Adapters with a JSON search endpoint. Other platforms are detected and get a documented HTML search path.
API_ADAPTERS=("shopify","woocommerce","magento","squarespace")

PLATFORM_PATTERNS=(
    ("shopify",r"cdn\.shopify\.com|Shopify\.shop"),
    ("woocommerce",r"woocommerce"),
    ("magento",r"Magento_|data-mage-init|text/x-magento-init|/static/version\d+/|mage/cookies"),
    ("shopware",r"shopware|/bundles/storefront/"),
    ("prestashop",r"prestashop|/modules/ps_"),
    ("squarespace",r"static1\.squarespace\.com|squarespace\.com/universal"),
    ("wix",r"static\.wixstatic\.com|wix-ecommerce|_wixCIDX"),
    ("quickbutik",r"quickbutik"),
    ("mystore",r"mystore\.no"),
    ("ehandel",r"ehandel\.no"),
)
# Standard HTML search routes of the platform, used only when the front page advertises no search form.
DEFAULT_SEARCH={
    "shopify":"/search?q={q}&type=product",
    "woocommerce":"/?s={q}&post_type=product",
    "magento":"/catalogsearch/result/?q={q}",
    "shopware":"/search?search={q}",
    "prestashop":"/search?controller=search&s={q}",
    "squarespace":"/search?q={q}",
}

def detect_platform(html):
    for name,pattern in PLATFORM_PATTERNS:
        if re.search(pattern,html,re.I):return name
    return "generic"

# ---- Generic search discovery: OpenSearch and schema.org SearchAction ----
class _Links(HTMLParser):
    def __init__(self):
        super().__init__();self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="link" and "search" in (a.get("rel") or "").lower().split() and "opensearchdescription" in (a.get("type") or "").lower() and a.get("href"):
            self.hrefs.append(a["href"])

def opensearch_href(html,base):
    """Same-host path of the advertised OpenSearch description document, or None."""
    p=_Links();p.feed(html)
    for href in p.hrefs:
        path=safe_relative(base,href)
        if path and len(path)<=500:return path
    return None

def _finish(url,base):
    path=safe_relative(base,url)
    if not path or len(path)>300 or path.count("{")!=1 or "{q}" not in path:return None
    return path

def searchaction_path(objects,base):
    """schema.org potentialAction SearchAction target -> '/path?x={q}' on the same host."""
    for obj in objects:
        actions=obj.get("potentialAction")
        for action in (actions if isinstance(actions,list) else [actions]):
            if not isinstance(action,dict) or "SearchAction" not in str(action.get("@type")):continue
            targets=action.get("target")
            for t in (targets if isinstance(targets,list) else [targets]):
                if isinstance(t,dict):t=t.get("urlTemplate")
                if not isinstance(t,str) or len(re.findall(r"\{[^{}]*\}",t))!=1:continue
                path=_finish(re.sub(r"\{[^{}]*\}","{q}",t),base)
                if path:return path
    return None

def opensearch_path(raw,base):
    """Parse an OpenSearch description (text/html Url template) into a same-host search path."""
    if len(raw)>100_000 or b"\x00" in raw:return None
    try:text=raw.decode("utf-8")
    except UnicodeDecodeError:return None
    if re.search(r"<!(?:DOCTYPE|ENTITY)",text,re.I):return None  # no entity expansion
    try:root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):return None
    for el in root.iter():
        if not el.tag.endswith("Url") or (el.get("type") or "text/html").split(";")[0].strip().lower() not in ("text/html","application/xhtml+xml"):continue
        if (el.get("method") or "get").lower()!="get":continue
        t=el.get("template") or ""
        if not re.search(r"\{searchTerms\??\}",t):continue
        head,_,query=t.partition("?")
        kept=[]
        for part in query.split("&") if query else []:
            m=re.fullmatch(r"([^=]*)=(\{[^{}]*\})",part)
            if m and m.group(2).endswith("?}") :continue       # optional parameter: omit
            kept.append(part.replace("{searchTerms}","{q}"))
        head=head.replace("{searchTerms}","{q}")
        if "{" in head.replace("{q}","") or any("{" in k and "{q}" not in k for k in kept):continue
        path=_finish(head+("?"+"&".join(kept) if kept else ""),base)
        if path:return path
    return None

# ---- Price helpers ----
def money(v):
    """Shopify money: integer = minor units (cents/ore); string = decimal major units like '1299.00'."""
    try:
        if isinstance(v,bool):return None
        if isinstance(v,int):return price(str(Decimal(v)/100))
        if isinstance(v,str) and re.fullmatch(r"[0-9]+\.[0-9]{1,2}",v.strip()):return price(v.strip())
    except (InvalidOperation,ValueError):pass
    return None

_CURRENCY={}
def shopify_currency(host,rp,fetcher):
    """Currency of the shop from its public /meta.json; None when unavailable or not stated."""
    # Positive and negative results are cached: at most one /meta.json request per shop and process.
    if host in _CURRENCY:return _CURRENCY[host]
    url="https://"+host+"/meta.json"
    if not rp.can_fetch(UA,url):_CURRENCY[host]=None;return None
    try:c=json.loads(fetcher(url,host,rp)).get("currency")
    except (ValueError,AttributeError,TypeError,urllib.error.URLError,OSError) as e:
        if isinstance(e,urllib.error.HTTPError) and e.code in (401,403,429):raise
        _CURRENCY[host]=None;return None
    _CURRENCY[host]=c if isinstance(c,str) and re.fullmatch(r"[A-Z]{3}",c) else None
    return _CURRENCY[host]

def _offer(url,name,host,val,kind,availability="",gt=None):
    return dict(url=url,name=unescape(name).strip()[:500],host=host,gtin=gt,model="",price=val,price_kind=kind,shipping=None,availability=availability,checked=stamp())

def shopify_offer(row,host,url,currency,decimal_only=False):
    """/products/<handle>.js rows use integer minor units; suggest.json rows (decimal_only=True) only decimal strings.
    NOK must be confirmed, and a currency stated by the row itself must also be NOK."""
    if currency!="NOK":return None
    if any(row.get(k) not in (None,"NOK") for k in ("currency","price_currency","currency_code","presentment_currency")):return None
    if decimal_only and any(row.get(k) is not None and not isinstance(row.get(k),str) for k in ("price","price_min","price_max")):return None
    name=row.get("title") or row.get("name")
    if not isinstance(name,str) or not name.strip():return None
    variants=row.get("variants")
    if isinstance(variants,list) and variants:
        prices=[money(v.get("price")) if isinstance(v,dict) else None for v in variants]
        if any(p is None for p in prices):return None
        lo=min(prices);kind="from" if len(set(prices))>1 else "exact"
        gt=gtin(variants[0].get("barcode")) if kind=="exact" and len(variants)==1 and isinstance(variants[0],dict) else None
    else:
        lo=money(row.get("price_min") if row.get("price_min") is not None else row.get("price"))
        hi=money(row.get("price_max")) if row.get("price_max") is not None else lo
        if lo is None or hi is None:return None
        kind="exact" if lo==hi else "from";gt=None
    avail="InStock" if row.get("available") is True else "OutOfStock" if row.get("available") is False else ""
    return _offer(url,name,host,lo,kind,avail,gt)

def magento_offer(row,host,url):
    try:
        pr=row["price_range"]
        lo,hi=pr["minimum_price"]["final_price"],pr["maximum_price"]["final_price"]
    except (KeyError,TypeError):return None
    if not isinstance(lo,dict) or not isinstance(hi,dict) or lo.get("currency")!="NOK" or hi.get("currency")!="NOK":return None
    a=price(lo.get("value"));b=price(hi.get("value"))
    name=row.get("name")
    if a is None or b is None or not isinstance(name,str) or not name.strip():return None
    return _offer(url,name,host,a,"exact" if a==b else "from")

MAGENTO_QUERY='{products(search:%s,pageSize:10){items{name sku url_key url_suffix price_range{minimum_price{final_price{value currency}}maximum_price{final_price{value currency}}}}}}'

def woo_offer(row,host,url):
    """Only explicit NOK simple products; ranges and variable products use HTML verification."""
    if row.get("type")!="simple" or row.get("is_purchasable") is not True or row.get("has_options") or row.get("price_range"):return None
    if row.get("condition") in ("used","refurbished","damaged"):return None
    p=row.get("prices")
    if not isinstance(p,dict) or p.get("currency_code")!="NOK" or p.get("price_range"):return None
    n=row.get("name")
    if not isinstance(n,str) or not n.strip():return None
    unit=p.get("currency_minor_unit");raw=p.get("price")
    if type(unit) is not int or not 0<=unit<=3 or not re.fullmatch(r"[0-9]+",str(raw)):return None
    val=price(str(Decimal(str(raw)).scaleb(-unit)))
    if val is None:return None
    return dict(url=url,name=unescape(n).strip()[:500],host=host,gtin=gtin(row.get("global_unique_id")),model="",price=val,price_kind="exact",shipping=None,availability="InStock" if row.get("is_in_stock") is True else "OutOfStock" if row.get("is_in_stock") is False else "",checked=stamp())

def _safe_product_url(base,href,host,rp):
    if not isinstance(href,str) or not href:return None
    u=urllib.parse.urlsplit(urllib.parse.urljoin(base,href))
    if u.scheme=="https" and same_host(u.hostname,host) and not u.username and not u.password and u.port in (None,443) and u.path not in ("","/") and rp.can_fetch(UA,u.geturl()):
        return u._replace(fragment="").geturl()
    return None

def api_search(host,adapter,q,rp,fetcher,offers=None):
    """Return product URLs (and append explicit-NOK offers to `offers`) from the platform's public JSON search."""
    enc=urllib.parse.urlencode
    if adapter=="shopify":path="/search/suggest.json?"+enc({"q":q,"resources[type]":"product","resources[limit]":10})
    elif adapter=="woocommerce":path="/wp-json/wc/store/v1/products?"+enc({"search":q,"per_page":10})
    elif adapter=="magento":path="/graphql?"+enc({"query":MAGENTO_QUERY%json.dumps(q)})
    elif adapter=="squarespace":path="/search?"+enc({"q":q,"format":"json"})
    else:return []
    url="https://"+host+path
    if not rp.can_fetch(UA,url):return []
    try:
        data=json.loads(fetcher(url,host,rp))
        if adapter=="shopify":rows=data.get("resources",{}).get("results",{}).get("products",[])
        elif adapter=="magento":rows=data.get("data",{}).get("products",{}).get("items",[])
        elif adapter=="squarespace":rows=data.get("items",[])
        else:rows=data
        if not isinstance(rows,list):return []
        result=[]
        for row in rows[:10]:
            if not isinstance(row,dict):continue
            if adapter=="magento":
                key=row.get("url_key");href="/"+key+(row.get("url_suffix") or "") if isinstance(key,str) and key else None
            else:href=row.get("url") or row.get("permalink") or row.get("fullUrl")
            purl=_safe_product_url(url,href,host,rp)
            if not purl or purl==url:continue
            result.append(purl)
            # WooCommerce/Magento API prices may be ex. VAT and carry no VAT flag: those APIs only supply URLs, and the
            # product page's JSON-LD (explicit NOK) supplies the price. woo_offer/magento_offer are kept but not used here.
            # No API prices for any adapter: Shopify Markets may present non-NOK currency and WooCommerce/Magento may be
            # ex. VAT. The product page JSON-LD (explicit NOK) supplies the price.
        return list(dict.fromkeys(result))
    except (ValueError,AttributeError,TypeError):return []
    except urllib.error.HTTPError as e:
        if e.code in (401,403,429):raise
        return []
    except (urllib.error.URLError,OSError):return []

"""Offline tests: platform detection, public JSON search adapters, OpenSearch/SearchAction discovery, matching."""
import unittest,json,time,urllib.error,urllib.robotparser
from unittest.mock import patch
import demand,store_adapters,search_adapters as sa
from product_parser import parse,matched_terms
from store_search import links
from durable import words

H="a.no"
def rp(text="User-agent: *\nDisallow:\n"):
    r=urllib.robotparser.RobotFileParser();r.parse(text.splitlines());return r
def fetcher(table):
    """table: substring -> payload (dict/list/bytes) or exception."""
    seen=[]
    def f(url,host,robots=None):
        seen.append(url)
        for k,v in table.items():
            if k in url:
                if isinstance(v,Exception):raise v
                return v if isinstance(v,bytes) else json.dumps(v).encode()
        raise urllib.error.HTTPError(url,404,"nf",{},None)
    f.seen=seen;return f

class Detection(unittest.TestCase):
    def test_platforms(self):
        cases={"shopify":'<script src="https://cdn.shopify.com/x.js">',"woocommerce":'<link href="/wp-content/plugins/woocommerce/a.css">',
               "magento":'<script type="text/x-magento-init">{}</script>',"shopware":'<link href="/bundles/storefront/a.css">',
               "prestashop":'<meta name="generator" content="PrestaShop">',"squarespace":'<script src="https://static1.squarespace.com/x.js">',
               "wix":'<img src="https://static.wixstatic.com/a.png">',"quickbutik":'<a href="https://quickbutik.com">',"mystore":'<a href="https://mystore.no">',
               "ehandel":'<a href="https://ehandel.no">',"generic":'<p>hei</p>'}
        for want,html in cases.items():
            self.assertEqual(sa.detect_platform(html),want)
            self.assertEqual(store_adapters.profile(html.encode(),"https://a.no/")["adapter"],want)
    def test_default_paths(self):
        for html,path in (('<script type="text/x-magento-init">','/catalogsearch/result/?q={q}'),('<i>shopware</i> Add to cart','/search?search={q}'),('prestashop Add to cart','/search?controller=search&s={q}')):
            self.assertEqual(store_adapters.profile(html.encode(),"https://a.no/")["search_path"],path)
    def test_form_beats_default(self):
        raw=b'<script type="text/x-magento-init"></script><form action="/find"><input type="search" name="k"></form>'
        self.assertEqual(store_adapters.profile(raw,"https://a.no/")["search_path"],"/find?k={q}")

class GenericDiscovery(unittest.TestCase):
    OS=b'<?xml version="1.0"?><OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/"><Url type="application/x-suggestions+json" template="https://a.no/suggest?q={searchTerms}"/><Url type="text/html" method="get" template="https://a.no/sok?query={searchTerms}&amp;page={startPage?}&amp;lang={language?}"/></OpenSearchDescription>'
    def test_opensearch_link_in_profile(self):
        raw=b'<link rel="search" type="application/opensearchdescription+xml" href="/opensearch.xml" title="x">'
        self.assertEqual(store_adapters.profile(raw,"https://a.no/")["opensearch"],"/opensearch.xml")
        raw=b'<link href="https://evil.no/o.xml" type="application/opensearchdescription+xml" rel="search">'
        self.assertIsNone(store_adapters.profile(raw,"https://a.no/")["opensearch"])
        self.assertIsNone(store_adapters.profile(b'<link rel="search" href="/x.xml">',"https://a.no/")["opensearch"])
    def test_opensearch_template(self):
        self.assertEqual(sa.opensearch_path(self.OS,"https://a.no/"),"/sok?query={q}")
        path_style=b'<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/"><Url type="text/html" template="https://www.a.no/s/{searchTerms}"/></OpenSearchDescription>'
        self.assertEqual(sa.opensearch_path(path_style,"https://a.no/"),"/s/{q}")
    def test_opensearch_rejects(self):
        ns='xmlns="http://a9.com/-/spec/opensearch/1.1/"'
        bad=[b"not xml",
             b'<!DOCTYPE x [<!ENTITY a "b">]><OpenSearchDescription '+ns.encode()+b'/>',
             ('<OpenSearchDescription %s><Url type="text/html" template="https://evil.no/?q={searchTerms}"/></OpenSearchDescription>'%ns).encode(),
             ('<OpenSearchDescription %s><Url type="text/html" template="https://a.no/?q={searchTerms}&amp;x={required}"/></OpenSearchDescription>'%ns).encode(),
             ('<OpenSearchDescription %s><Url type="text/html" method="post" template="https://a.no/?q={searchTerms}"/></OpenSearchDescription>'%ns).encode(),
             ('<OpenSearchDescription %s><Url type="text/html" template="http://a.no/?q={searchTerms}"/></OpenSearchDescription>'%ns).encode()]
        for raw in bad:self.assertIsNone(sa.opensearch_path(raw,"https://a.no/"),raw)
    def ld(self,target):
        return [{"@type":"WebSite","potentialAction":{"@type":"SearchAction","target":target,"query-input":"required name=search_term_string"}}]
    def test_searchaction_variants(self):
        self.assertEqual(sa.searchaction_path(self.ld("https://a.no/search?q={search_term_string}"),"https://a.no/"),"/search?q={q}")
        self.assertEqual(sa.searchaction_path(self.ld({"@type":"EntryPoint","urlTemplate":"https://www.a.no/sok/{search_term_string}"}),"https://a.no/"),"/sok/{q}")
        self.assertEqual(sa.searchaction_path(self.ld(["https://evil.no/?q={s}","/s?q={s}"]),"https://a.no/"),"/s?q={q}")
    def test_searchaction_rejects(self):
        for t in ("https://evil.no/?q={s}","https://a.no/?q=x","https://a.no/?q={a}&r={b}","http://a.no/?q={s}",5,None):
            self.assertIsNone(sa.searchaction_path(self.ld(t),"https://a.no/"),t)
    def test_searchaction_in_profile(self):
        raw=b'<script type="application/ld+json">{"@type":"WebSite","potentialAction":{"@type":"SearchAction","target":"https://a.no/sok?s={search_term_string}"}}</script>'
        self.assertEqual(store_adapters.profile(raw,"https://a.no/")["search_path"],"/sok?s={q}")

class ShopifyAdapter(unittest.TestCase):
    SUG={"resources":{"results":{"products":[{"title":"Acme &amp; Co","url":"/products/acme?_pos=1","price":"1299.00","price_min":"1299.00","price_max":"1599.00","available":True},
                                              {"title":"Other","url":"/products/other","price":"99.50","available":False}]}}}
    def test_money_conversion(self):
        self.assertEqual(sa.money(129900),1299);self.assertEqual(sa.money(12995),129.95);self.assertEqual(sa.money("1299.00"),1299)
        for bad in (True,None,"1299","abc",12.5,0,"-1.00"):self.assertIsNone(sa.money(bad),bad)
    def test_js_format_cents_and_variants(self):
        row={"title":"Acme","variants":[{"price":129900,"barcode":None},{"price":149900}],"available":True}
        o=sa.shopify_offer(row,H,"https://a.no/products/acme","NOK")
        self.assertEqual((o["price"],o["price_kind"]),(1299,"from"))
        row={"title":"Acme","variants":[{"price":129900}]};o=sa.shopify_offer(row,H,"u","NOK")
        self.assertEqual((o["price"],o["price_kind"]),(1299,"exact"))
        self.assertIsNone(sa.shopify_offer({"title":"A","variants":[{"price":1},{"price":None}]},H,"u","NOK"))
    def test_requires_explicit_nok(self):
        for c in (None,"SEK","USD"):self.assertIsNone(sa.shopify_offer({"title":"A","price":"10.00"},H,"u",c))
    def test_search_gives_urls_only_and_no_meta_request(self):
        offers=[];f=fetcher({"/search/suggest.json":self.SUG,"/meta.json":{"currency":"NOK"}})
        urls=sa.api_search(H,"shopify","acme",rp(),f,offers)
        self.assertEqual(urls,["https://a.no/products/acme?_pos=1","https://a.no/products/other"])
        self.assertEqual(offers,[])  # Markets may present non-NOK: price comes from the product page JSON-LD
        self.assertEqual(len(f.seen),1);self.assertNotIn("meta.json",f.seen[0])

class MagentoAdapter(unittest.TestCase):
    def item(self,lo="1299",hi="1299",cur="NOK",**kw):
        d={"name":"Acme TV","sku":"S1","url_key":"acme-tv","url_suffix":".html","price_range":{"minimum_price":{"final_price":{"value":float(lo),"currency":cur}},"maximum_price":{"final_price":{"value":float(hi),"currency":cur}}}}
        d.update(kw);return d
    def run_search(self,items,**kw):
        offers=[];f=fetcher({"/graphql":{"data":{"products":{"items":items}}}})
        return sa.api_search(H,"magento",'ac"me',rp(),f,offers),offers,f
    def test_exact_and_from(self):
        urls,offers,f=self.run_search([self.item(),self.item("100","200",url_key="b")])
        self.assertEqual(urls,["https://a.no/acme-tv.html","https://a.no/b.html"])
        self.assertEqual(offers,[])  # URLs only; price comes from the product page JSON-LD
        self.assertIn("/graphql?query=",f.seen[0]);self.assertIn("%5C%22me",f.seen[0])  # quote escaped in GraphQL string
    def test_non_nok_dropped_but_url_kept(self):
        urls,offers,_=self.run_search([self.item(cur="SEK")]);self.assertEqual(len(urls),1);self.assertEqual(offers,[])
        self.assertEqual(sa.magento_offer(self.item(cur="SEK"),H,"u"),None)
    def test_errors_and_missing_key(self):
        sa_=sa.api_search
        self.assertEqual(sa_(H,"magento","q",rp(),fetcher({"/graphql":{"errors":[{"message":"x"}],"data":None}}),[]),[])
        self.assertEqual(self.run_search([self.item(url_key=None)])[0],[])
        self.assertEqual(sa_(H,"magento","q",rp("User-agent: *\nDisallow: /graphql\n"),fetcher({}),[]),[])

class SquarespaceAndWoo(unittest.TestCase):
    def test_squarespace_urls_only(self):
        offers=[];f=fetcher({"format=json":{"items":[{"fullUrl":"/shop/p/acme","title":"Acme"},{"fullUrl":"https://evil.no/x"}]}})
        self.assertEqual(sa.api_search(H,"squarespace","acme",rp(),f,offers),["https://a.no/shop/p/acme"]);self.assertEqual(offers,[])
    def test_woocommerce_store_api(self):
        row={"type":"simple","is_purchasable":True,"is_in_stock":True,"name":"Acme","permalink":"https://a.no/p/acme","prices":{"currency_code":"NOK","currency_minor_unit":2,"price":"129900"}}
        offers=[];f=fetcher({"/wp-json/wc/store/v1/products":[row]})
        self.assertEqual(sa.api_search(H,"woocommerce","acme",rp(),f,offers),["https://a.no/p/acme"])
        self.assertEqual(offers,[])  # Store API price may be ex. VAT: URL only
        self.assertEqual(store_adapters.woo_offer(row,H,"https://a.no/p/acme")["price"],1299)  # converter itself still correct
    def test_auth_errors_propagate(self):
        for ad in ("magento","squarespace","shopify"):
            f=fetcher({"":urllib.error.HTTPError("u",403,"x",{},None)})
            with self.assertRaises(urllib.error.HTTPError):sa.api_search(H,ad,"q",rp(),f,[])

class Matching(unittest.TestCase):
    def m(self,name,q):return demand.matches(name,q)
    def test_model_codes_with_and_without_separators(self):
        for name,q in (("Sony WH-1000XM5 Hodetelefoner","sony wh1000xm5"),("Sony WH1000XM5","sony wh-1000xm5"),("Sony WH 1000XM5 black","wh1000xm5"),
                       ("Samsung Galaxy S24 Ultra","galaxys24 ultra"),("https://a.no/p/sony-wh-1000xm5-black","sony wh1000xm5")):
            self.assertTrue(self.m(name,q),(name,q))
    def test_still_rejects(self):
        self.assertFalse(self.m("Sony WH-1000XM4","sony wh1000xm5"))
        self.assertFalse(self.m("iPhone 150 case","iphone 15"))
        self.assertFalse(self.m("AirPods Pro deksel","airpods pro"))
        self.assertFalse(self.m("Apple AirPods 3 etui","airpods 4"))
        self.assertFalse(self.m("Sony headphones","sony wh1000xm5"))
    def test_matched_terms_boundaries(self):
        self.assertEqual(matched_terms(["wh","1000xm5"],words("sony wh1000xm5")),{"wh","1000xm5"})
        self.assertNotIn("15",matched_terms(["iphone","15"],words("iphone 150")))
    def test_offer_model_squash(self):
        self.assertTrue(demand.offer_matches("Hodetelefoner",None,"WH-1000XM5","wh1000xm5"))
        self.assertFalse(demand.offer_matches("Hodetelefoner",None,"WH-1000XM4","wh1000xm5"))
        self.assertFalse(demand.offer_matches("Hodetelefoner",None,"---","---x"))

class SlugLinks(unittest.TestCase):
    def test_slug_only_product_links(self):
        raw=b'<a href="/hodetelefoner/sony-wh-1000xm5-svart">Sony WH-1000XM5</a><a href="/kategori/sony-wh-1000xm5">Sony WH-1000XM5</a><a href="/sony">Sony</a><a href="/p/sony-wh1000xm5-hvit">x</a><a href="/kundeservice/sony-wh1000xm5">x</a>'
        out=links(raw,"https://a.no/sok?q=x","a.no","sony wh1000xm5")
        self.assertEqual(out,["https://a.no/p/sony-wh1000xm5-hvit","https://a.no/hodetelefoner/sony-wh-1000xm5-svart"])  # product-like path first

class ProductGroup(unittest.TestCase):
    def test_variants_become_one_from_offer(self):
        doc={"@context":"https://schema.org","@type":"ProductGroup","name":"Acme Jakke","url":"https://a.no/p/jakke","hasVariant":[
            {"@type":"Product","name":"Acme Jakke S","offers":{"@type":"Offer","price":"999","priceCurrency":"NOK","availability":"https://schema.org/InStock"}},
            {"@type":"Product","name":"Acme Jakke L","offers":{"@type":"Offer","price":"1099","priceCurrency":"NOK","availability":"https://schema.org/InStock"}}]}
        raw=('<script type="application/ld+json">'+json.dumps(doc)+'</script>').encode()
        r=parse(raw,"https://a.no/p/jakke",H,"t")
        self.assertEqual([(x["name"],x["price"],x["price_kind"]) for x in r],[("Acme Jakke",999,"from")])
        doc["hasVariant"][0]["offers"]["priceCurrency"]="SEK";doc["hasVariant"][1]["offers"]["priceCurrency"]="SEK"
        self.assertEqual(parse(('<script type="application/ld+json">'+json.dumps(doc)+'</script>').encode(),"https://a.no/p/jakke",H,"t"),[])

def _ld(d):return ('<script type="application/ld+json">'+json.dumps(d)+'</script>').encode()
def _offer(p,c="NOK",**k):return {"@type":"Offer","price":p,"priceCurrency":c,**k}
def _group(offs):return {"@type":"ProductGroup","name":"J","url":"https://a.no/p/j","hasVariant":[{"@type":"Product","name":"J %d"%i,"offers":o} for i,o in enumerate(offs)]}
def _pg(offs):return parse(_ld(_group(offs)),"https://a.no/p/j",H,"t")

class ReviewShopifyFormats(unittest.TestCase):
    def search(self,row,host="r.no"):
        sa._CURRENCY.clear();offers=[]
        sa.api_search(host,"shopify","acme",rp(),fetcher({"/search/suggest.json":{"resources":{"results":{"products":[row]}}},"/meta.json":{"currency":"NOK"}}),offers)
        sa._CURRENCY.clear();return offers
    def test_decimal_string_is_major_units(self):
        self.assertEqual(self.search({"title":"A","url":"/products/a","price":"1499.00"}),[])  # no API prices any more
        self.assertEqual(sa.money("1499.00"),1499)
    def test_integer_string_is_not_guessed(self):
        self.assertEqual(self.search({"title":"A","url":"/products/a","price":"1499"}),[])
    def test_js_integer_is_minor_units(self):
        self.assertEqual(sa.shopify_offer({"title":"A","price":149900},H,"u","NOK")["price"],1499)
        self.assertEqual(sa.shopify_offer({"title":"A","price":1499},H,"u","NOK")["price"],14.99)
    def test_suggest_json_integer_must_not_be_guessed(self):
        # REVIEW: suggest.json documents decimal strings; an integer there has unknown unit and 1499 becomes 14.99 kr.
        self.assertEqual(self.search({"title":"A","url":"/products/a","price":1499}),[])
    def test_empty_and_timeout_search(self):
        self.assertEqual(sa.api_search(H,"shopify","q",rp(),fetcher({"/search/suggest.json":{}}),[]),[])
        self.assertEqual(sa.api_search(H,"shopify","q",rp(),fetcher({"":TimeoutError("t")}),[]),[])
    def test_unknown_currency_is_looked_up_once(self):
        # REVIEW: failed /meta.json lookups are not cached, so each product row repeats the request.
        f=fetcher({"/search/suggest.json":ShopifyAdapter.SUG})
        sa.api_search("m.no","shopify","acme",rp(),f,[])
        self.assertEqual(sum("meta.json" in u for u in f.seen),0)

class ReviewMagentoVat(unittest.TestCase):
    def test_magento_price_not_stored_without_vat_evidence(self):
        # REVIEW: Magento final_price may be ex. VAT; managed_stores.vat_status is "unknown" here and is never consulted.
        item=MagentoAdapter().item(name="Acme Mixer")
        page={"https://a.no/graphql?*":json.dumps({"data":{"products":{"items":[item]}}}).encode()}
        n,calls,writes,prices=ProcessStoreDiscovery().go({"search_path":"/s?q={q}","adapter":"magento","vat_status":"unknown"},page,{"profiled":{H}})
        # Magento API prices are never stored (may be ex. VAT); only the URL is used, and its page is unavailable here.
        self.assertEqual(n,0)
        self.assertEqual(prices,[])
        self.assertIn("https://a.no/acme-tv.html",calls)

class ReviewProductGroup(unittest.TestCase):
    def test_equal_prices_are_exact(self):
        r=_pg([_offer("999"),_offer("999")]);self.assertEqual((r[0]["price"],r[0]["price_kind"]),(999,"exact"))
    def test_foreign_currency_variant_never_supplies_price(self):
        for offs in ([_offer("1099"),_offer("500","SEK")],[_offer("500","SEK"),_offer("1099")],[_offer("500","EUR")],[_offer("500",None)]):
            for r in _pg(offs):self.assertEqual(r["price"],1099,offs)
    def test_used_variant_not_lowest(self):
        r=_pg([_offer("500",itemCondition="https://schema.org/UsedCondition"),_offer("1099")]);self.assertEqual([x["price"] for x in r],[1099])

class ReviewMatchingAndLinks(unittest.TestCase):
    def test_slug_links_skip_category_blog_and_short(self):
        raw=b'<a href="/blogg/iphone-15-test">x</a><a href="/guider/iphone-15-kjopsguide">x</a><a href="/merke/iphone-15">x</a><a href="/iphone-15">x</a><a href="/iphone-15-128gb">x</a>'
        self.assertEqual(links(raw,"https://a.no/sok?q=x","a.no","iphone 15"),["https://a.no/iphone-15","https://a.no/iphone-15-128gb"])
    def test_slug_link_with_wrong_model_number(self):
        # REVIEW: one missing term is tolerated, so /iphone-150-deksel passes the link filter for "iphone 15".
        raw=b'<a href="/iphone-150-deksel">iPhone 150</a>'
        self.assertEqual(links(raw,"https://a.no/sok?q=x","a.no","iphone 15"),[])
    def test_joined_tokens_across_spaces(self):
        # REVIEW: "s2"+"4" is merged into "s24".
        self.assertFalse(demand.matches("Galaxy S2 4 stk","galaxys24"))
    def test_iphone_150_rejected(self):
        self.assertFalse(demand.matches("iPhone 150","iphone 15"))
        self.assertFalse(demand.offer_matches("x",None,"iPhone150","iphone15"))

DNS=[(2,1,6,"",("8.8.8.8",443))]
class ProcessStoreDiscovery(unittest.TestCase):
    PAGE=('<script type="application/ld+json">'+json.dumps({"@type":"Product","name":"Acme Mixer","url":"https://a.no/mixers/acme-mixer","offers":{"@type":"Offer","price":"499","priceCurrency":"NOK"}})+'</script>').encode()
    def go(self,config,pages,ctx=None):
        calls=[];writes=[];prices=[]
        def fetch(url,host,rp=None):
            calls.append(url)
            for k,v in pages.items():
                if url==k or (k.endswith("*") and url.startswith(k[:-1])):return v
            if url.endswith("/robots.txt"):return b"User-agent: *\nDisallow:\n"
            raise urllib.error.HTTPError(url,404,"nf",{},None)
        def db(table,params=None,method="GET",body=None,prefer=None):
            if method!="GET":writes.append((table,method,body));return None
            return [{"id":1}] if table=="offers" else []
        with patch.object(demand,"fetch",side_effect=fetch),patch.object(demand,"db",side_effect=db),patch.object(demand,"send",side_effect=lambda t,r,k:prices.extend(r)),patch.object(demand,"learn_assortment"),patch.object(demand.socket,"getaddrinfo",return_value=DNS),patch.object(demand,"discover",return_value=[]):
            n=demand.process_store(H,"acme mixer",config,[],time.monotonic()+100,12,ctx)
        return n,calls,writes,prices
    def test_opensearch_found_and_saved(self):
        home=b'<link rel="search" type="application/opensearchdescription+xml" href="/os.xml">'
        xml=b'<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/"><Url type="text/html" template="https://a.no/finn?x={searchTerms}"/></OpenSearchDescription>'
        res=b'<a href="/mixers/acme-mixer">Acme Mixer</a>'
        n,calls,writes,prices=self.go({"search_path":None,"adapter":"generic"},{"https://a.no/":home,"https://a.no/os.xml":xml,"https://a.no/finn?*":res,"https://a.no/mixers/acme-mixer":self.PAGE},{})
        self.assertEqual(n,1);self.assertEqual(prices[0]["price"],499)
        self.assertTrue(any(t=="managed_stores" and b.get("search_path")=="/finn?x={q}" for t,m,b in writes))
    def test_generic_store_with_path_gets_adapter_once_per_run(self):
        home=b'<script src="https://cdn.shopify.com/a.js"></script>'
        ctx={}
        n,calls,writes,_=self.go({"search_path":"/search?q={q}","adapter":"generic"},{"https://a.no/":home},ctx)
        self.assertTrue(any(t=="managed_stores" and b=={"adapter":"shopify"} for t,m,b in writes))
        self.assertTrue(any("suggest.json" in c for c in calls))
        n,calls,writes,_=self.go({"search_path":"/search?q={q}","adapter":"generic"},{"https://a.no/":home},ctx)
        self.assertNotIn("https://a.no/",calls)

class FiltersAndOpenSearchHardening(unittest.TestCase):
    def test_used_and_demo_names_rejected_unless_asked(self):
        for name in ("Brukt iPhone 15","iPhone 15 refurbished","iPhone 15 Demo","Renovert iPhone 15 128GB"):
            self.assertFalse(demand.matches(name,"iphone 15"),name)
        self.assertTrue(demand.matches("Brukt iPhone 15","brukt iphone 15"))
        self.assertTrue(demand.matches("iPhone 15 128GB","iphone 15"))
    def test_accessories_rejected_for_model_queries(self):
        for name in ("iPhone 15 deksel","iPhone 15 skjermbeskytter","Lader til iPhone 15","iPhone 15 etui","USB-C kabel iPhone 15"):
            self.assertFalse(demand.matches(name,"iphone 15"),name)
        self.assertTrue(demand.matches("iPhone 15 deksel","iphone 15 deksel"))
        self.assertTrue(demand.matches("HDMI kabel 2m","hdmi"))  # no model number in the query: product may be the accessory
    def test_opensearch_size_nul_and_encoding(self):
        ok=b'<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/"><Url type="text/html" template="https://a.no/s?q={searchTerms}"/></OpenSearchDescription>'
        self.assertEqual(sa.opensearch_path(ok,"https://a.no/"),"/s?q={q}")
        self.assertIsNone(sa.opensearch_path(ok+b" "*100_001,"https://a.no/"))
        self.assertIsNone(sa.opensearch_path(ok.replace(b"</Open",b"\x00</Open"),"https://a.no/"))
        self.assertIsNone(sa.opensearch_path(b'\xff\xfe'+ok,"https://a.no/"))
        self.assertIsNone(sa.opensearch_path(ok.replace(b"<Url",b"<!DOCTYPE a [<!ENTITY x 'y'>]><Url"),"https://a.no/"))
        self.assertIsNone(sa.opensearch_path(b'<?xml version="1.0" encoding="latin-1"?>'+ok.replace(b"s?q",b"\xe9"),"https://a.no/"))
    def test_opensearch_href_with_control_chars_does_not_skip_store(self):
        home=b'<link rel="search" type="application/opensearchdescription+xml" href="/o s.xml">'
        n,calls,writes,prices=ProcessStoreDiscovery().go({"search_path":None,"adapter":"generic"},{"https://a.no/":home},{})
        self.assertFalse(any("o s.xml" in c or "o%20s" in c for c in calls))
        self.assertTrue(any(t=="crawl_reports" and b["detail"]=="no matching product URLs" for t,m,b in writes))
    def test_opensearch_fetch_failure_does_not_abort_store(self):
        home=b'<link rel="search" type="application/opensearchdescription+xml" href="/os.xml">'
        with patch.object(demand,"opensearch_path",side_effect=RuntimeError("boom")):
            n,calls,writes,prices=ProcessStoreDiscovery().go({"search_path":None,"adapter":"generic"},{"https://a.no/":home,"https://a.no/os.xml":b"x"},{})
        self.assertTrue(any(t=="crawl_reports" and b["detail"]=="no matching product URLs" for t,m,b in writes))
    def test_shopify_currency_row_must_be_nok(self):
        self.assertIsNone(sa.shopify_offer({"title":"A","price":"10.00","currency":"EUR"},H,"u","NOK",True))
        self.assertEqual(sa.shopify_offer({"title":"A","price":"10.00","currency":"NOK"},H,"u","NOK",True)["price"],10)
    def test_meta_json_negative_cache_covers_timeouts_and_robots(self):
        sa._CURRENCY.clear();f=fetcher({"/meta.json":TimeoutError("t")})
        for _ in range(3):self.assertIsNone(sa.shopify_currency("n.no",rp(),f))
        self.assertEqual(sum("meta.json" in u for u in f.seen),1)
        sa._CURRENCY.clear()
if __name__=="__main__":unittest.main()

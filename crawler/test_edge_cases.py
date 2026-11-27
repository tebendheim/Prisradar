"""Offline edge-case tests: price parsing, robots/HTTP errors, hosts, feeds, microdata, migrations."""
import unittest,json,os,re,io,gzip,urllib.error
from unittest.mock import patch,MagicMock
from pathlib import Path
import product_parser,crawl,brreg_seed,merchant_feed,affiliate_feed,sources,store_rank,store_search,store_adapters,durable,demand
from product_parser import parse,price,gtin,normalized_gtin,documented_shipping,conditional_prices

ROOT=Path(__file__).resolve().parent.parent
U="https://example.no/product/12345"
def ld(obj):return ('<script type="application/ld+json">'+json.dumps(obj)+'</script>').encode()
def prod(offers,**kw):return dict({"@type":"Product","name":"Headphones","offers":offers},**kw)
def run(raw,url=U):return parse(raw,url,"example.no","2026-11-27T00:00:00Z")
def http(code):return urllib.error.HTTPError("https://x/",code,"err",{},None)

class PriceParsing(unittest.TestCase):
    def test_accepted_formats(self):
        for s,want in (("1.299,00",1299),("1 299,00",1299),("1 299",1299),("12,5",12.5),("1299,5",1299.5),("0,99",0.99),(1299,1299),(99.9,99.9),(" 99 ",99)):
            self.assertEqual(price(s),want,s)
    def test_rejected_formats(self):
        # Conservative parser: ambiguous or decorated strings are rejected, never guessed.
        for s in ("1 299,-","kr 1 299","1 299 kr","1299,-","1,299.00","99,999","1e3","Infinity","-Infinity","-5","0,00","0","10000001","","  ",None,False,"abc","1..5","1,2,3"):
            self.assertIsNone(price(s),repr(s))
    def test_ore_are_not_kroner(self):
        self.assertEqual(price("0,50"),0.5)
        self.assertEqual(price("49,90"),49.9)
    def test_ceiling(self):
        self.assertEqual(price("10000000"),10000000)
    def test_non_ascii_digits_rejected(self):
        self.assertIsNone(price("٣"))
        self.assertIsNone(price("１２３"))
    def test_gtin_edge(self):
        for v in (None,"","0000000000000","123","abcdefgh12345",4006381333931.0):self.assertIsNone(gtin(v))
        self.assertEqual(normalized_gtin("4006381333931"),"04006381333931")
        self.assertIsNone(normalized_gtin("4006381333932"))

class StructuredOffers(unittest.TestCase):
    def one(self,offers,**kw):
        r=run(ld(prod(offers,**kw)));return r[0] if r else None
    def test_missing_currency_rejected(self):
        self.assertIsNone(self.one({"price":99}))
    def test_currency_inherited_from_product(self):
        self.assertEqual(self.one({"price":99},priceCurrency="NOK")["price"],99)
    def test_inherited_foreign_currency(self):
        self.assertIsNone(self.one({"price":99},priceCurrency="SEK"))
    def test_lowercase_currency(self):
        self.assertEqual(self.one({"price":99,"priceCurrency":"nok"})["price"],99)
    def test_negative_zero_unrealistic(self):
        for v in (-5,0,"0","0,00",10000001,"NaN",None,True,[],{}):
            self.assertIsNone(self.one({"price":v,"priceCurrency":"NOK"}),repr(v))
    def test_string_prices(self):
        self.assertEqual(self.one({"price":"1 299,00","priceCurrency":"NOK"})["price"],1299)
        self.assertEqual(self.one({"price":"1.299,00","priceCurrency":"NOK"})["price"],1299)
    def test_used_refurb_damaged(self):
        for c in ("UsedCondition","RefurbishedCondition","DamagedCondition"):
            for pre in ("https://schema.org/","http://schema.org/",""):
                self.assertIsNone(self.one({"price":99,"priceCurrency":"NOK","itemCondition":pre+c}),pre+c)
    def test_new_condition_kept(self):
        self.assertEqual(self.one({"price":99,"priceCurrency":"NOK","itemCondition":"https://schema.org/NewCondition"})["price"],99)
    def test_used_only_does_not_fall_back_to_metadata(self):
        html=ld(prod({"price":99,"priceCurrency":"NOK","itemCondition":"https://schema.org/UsedCondition"}))+b'<meta property="og:type" content="product"><meta property="og:title" content="H"><meta property="product:price:amount" content="10"><meta property="product:price:currency" content="NOK">'
        self.assertEqual(run(html),[])
    def test_cheap_used_offer_ignored_among_new(self):
        r=run(ld(prod([{"price":10,"priceCurrency":"NOK","itemCondition":"https://schema.org/UsedCondition"},{"price":99,"priceCurrency":"NOK"}])))
        self.assertEqual(r[0]["price"],99);self.assertEqual(r[0]["price_kind"],"exact")
    def test_out_of_stock_reported_as_such(self):
        r=self.one({"price":99,"priceCurrency":"NOK","availability":"https://schema.org/OutOfStock"})
        self.assertEqual(r["availability"],"OutOfStock")
    def test_instock_preferred_over_cheaper_outofstock(self):
        r=self.one([{"price":99,"priceCurrency":"NOK","availability":"https://schema.org/OutOfStock"},{"price":120,"priceCurrency":"NOK","availability":"https://schema.org/InStock"}])
        self.assertEqual((r["price"],r["availability"],r["price_kind"]),(120,"InStock","from"))
    def test_identical_offers_are_exact(self):
        r=self.one([{"price":99,"priceCurrency":"NOK"},{"price":99,"priceCurrency":"NOK"}])
        self.assertEqual(r["price_kind"],"exact")
    def test_mixed_currency_list_uses_only_nok(self):
        r=self.one([{"price":5,"priceCurrency":"USD"},{"price":99,"priceCurrency":"NOK"}])
        self.assertEqual(r["price"],99)
    def test_aggregate_with_children(self):
        r=self.one({"@type":"AggregateOffer","priceCurrency":"NOK","offers":[{"price":99,"availability":"https://schema.org/InStock"},{"price":200}]})
        self.assertEqual((r["price"],r["price_kind"]),(99,"from"))
    def test_aggregate_low_price_is_from_and_has_no_gtin_or_mpn(self):
        r=self.one({"@type":"AggregateOffer","lowPrice":"1 299,00","highPrice":2000,"priceCurrency":"NOK"},gtin13="4006381333931",mpn="X1")
        self.assertEqual((r["price"],r["price_kind"],r["gtin"],r["mpn"]),(1299,"from",None,None))
    def test_aggregate_foreign_currency(self):
        self.assertIsNone(self.one({"@type":"AggregateOffer","lowPrice":99,"priceCurrency":"EUR"}))
    def test_aggregate_without_prices(self):
        self.assertIsNone(self.one({"@type":"AggregateOffer","priceCurrency":"NOK"}))
    def test_member_offer_never_used_as_public(self):
        r=run(ld(prod([{"price":50,"priceCurrency":"NOK","validForMemberTier":{"name":"Club"}},{"price":99,"priceCurrency":"NOK"}])))
        self.assertEqual((r[0]["price"],r[0]["price_kind"]),(99,"exact"))
    def test_quantity_offer_ignored(self):
        self.assertIsNone(self.one({"price":50,"priceCurrency":"NOK","eligibleQuantity":{"minValue":10}}))
    def test_list_price_spec_skipped(self):
        r=self.one({"priceSpecification":[{"price":150,"priceCurrency":"NOK","priceType":"https://schema.org/ListPrice"},{"price":99,"priceCurrency":"NOK"}]})
        self.assertEqual(r["price"],99)
    def test_only_list_price_spec_rejected(self):
        self.assertIsNone(self.one({"priceSpecification":{"price":150,"priceCurrency":"NOK","priceType":"https://schema.org/ListPrice"}}))
    def test_unit_price_spec_rejected(self):
        self.assertIsNone(self.one({"priceSpecification":{"@type":"UnitPriceSpecification","price":5,"priceCurrency":"NOK"}}))
    def test_non_dict_offers_skipped(self):
        r=self.one([1,None,"x",{"price":5,"priceCurrency":"NOK"}])
        self.assertEqual(r["price"],5)
    def test_offers_string(self):
        self.assertEqual(run(ld(prod("x"))),[])
    def test_offers_null_or_scalar_does_not_crash(self):
        for v in (None,5,True):self.assertEqual(run(ld(prod(v))),[])
    def test_offers_missing(self):
        self.assertEqual(run(ld({"@type":"Product","name":"H"})),[])
    def test_missing_or_blank_name(self):
        for n in (None,"","  ",5):self.assertEqual(run(ld({"@type":"Product","name":n,"offers":{"price":9,"priceCurrency":"NOK"}})),[])
    def test_name_truncated(self):
        r=run(ld(prod({"price":9,"priceCurrency":"NOK"},name="x"*900)))
        self.assertEqual(len(r[0]["name"]),500)
    def test_offer_url_for_other_page_rejected(self):
        self.assertIsNone(self.one({"price":9,"priceCurrency":"NOK","url":"https://example.no/product/999"}))
    def test_type_as_list_and_url_form(self):
        r=run(ld({"@type":["Thing","https://schema.org/Product"],"name":"H","offers":{"price":9,"priceCurrency":"NOK"}}))
        self.assertEqual(r[0]["price"],9)
    def test_multiple_products_without_identity_rejected(self):
        a=prod({"price":9,"priceCurrency":"NOK"});b=prod({"price":19,"priceCurrency":"NOK"},name="Other")
        self.assertEqual(run(ld([a,b])),[])
    def test_primary_product_picked_among_carousel(self):
        a=prod({"price":9,"priceCurrency":"NOK"},url=U);b=prod({"price":19,"priceCurrency":"NOK"},name="Other",url="https://example.no/product/2")
        r=run(ld([b,a]));self.assertEqual((len(r),r[0]["price"]),(1,9))
    def test_url_trailing_slash_and_www_same_page(self):
        r=run(ld(prod({"price":9,"priceCurrency":"NOK"},url="https://www.example.no/product/12345/")))
        self.assertEqual(r[0]["price"],9)
    def test_shipping_only_flat_nok_norway(self):
        ok={"shippingDestination":{"addressCountry":"NO"},"shippingRate":{"currency":"NOK","value":"99"}}
        self.assertEqual(documented_shipping({"shippingDetails":ok}),99)
        self.assertEqual(documented_shipping({"shippingDetails":dict(ok,shippingRate={"currency":"NOK","value":"0"})}),0)
        self.assertIsNone(documented_shipping({"shippingDetails":dict(ok,shippingRate={"currency":"SEK","value":"99"})}))
        self.assertIsNone(documented_shipping({"shippingDetails":dict(ok,shippingDestination={"addressCountry":"SE"})}))
        self.assertIsNone(documented_shipping({"shippingDetails":dict(ok,shippingDestination={"addressCountry":"NO","postalCode":"0150"})}))
        self.assertIsNone(documented_shipping({"shippingDetails":[ok,dict(ok,shippingRate={"currency":"NOK","value":"49"})]}))
        self.assertIsNone(documented_shipping({}))

class BrokenInput(unittest.TestCase):
    def test_empty_and_garbage(self):
        for raw in (b"",b"   ",b"<html>",b"\xff\xfe\x00garbage",b"<script type='application/ld+json'>",b'<script type="application/ld+json">{"@type":"Product",</script>',b'<script type="application/ld+json">[[[[</script>',b'<script type="application/ld+json">null</script>'):
            self.assertEqual(run(raw),[],raw)
    def test_nan_literal(self):
        self.assertEqual(run(b'<script type="application/ld+json">{"@type":"Product","name":"N","offers":{"price":NaN,"priceCurrency":"NOK"}}</script>'),[])
    def test_deep_nesting_does_not_crash(self):
        self.assertEqual(run(b'<script type="application/ld+json">'+b"["*5000+b"]"*5000+b'</script>'),[])
    def test_html_comment_wrapped_and_trailing_comma(self):
        raw=b'<script type="application/ld+json"><!-- {"@type":"Product","name":"N","offers":{"price":9,"priceCurrency":"NOK",},} --></script>'
        self.assertEqual(run(raw)[0]["price"],9)
    def test_second_script_valid_when_first_broken(self):
        raw=b'<script type="application/ld+json">{oops</script>'+ld(prod({"price":9,"priceCurrency":"NOK"}))
        self.assertEqual(run(raw)[0]["price"],9)
    def test_non_utf8_bytes(self):
        raw=ld(prod({"price":9,"priceCurrency":"NOK"},name="H")).replace(b"H",b"H\xe6")
        self.assertEqual(run(raw)[0]["price"],9)

class MetadataFallback(unittest.TestCase):
    META='<meta property="og:type" content="product"><meta property="og:title" content="Hp"><meta property="product:price:amount" content="%s"><meta property="product:price:currency" content="%s">'
    def test_ok(self):self.assertEqual(run((self.META%("1 299,00","NOK")).encode())[0]["price"],1299)
    def test_foreign_currency(self):self.assertEqual(run((self.META%("99","SEK")).encode()),[])
    def test_missing_currency(self):self.assertEqual(run(b'<meta property="og:type" content="product"><meta property="og:title" content="Hp"><meta property="product:price:amount" content="9">'),[])
    def test_used_condition(self):
        for c in ("used","refurbished","USED"):
            self.assertEqual(run((self.META%("99","NOK")+'<meta property="product:condition" content="%s">'%c).encode()),[])
    def test_not_a_product_page(self):
        self.assertEqual(run((self.META%("99","NOK")).replace("og:type\" content=\"product","og:type\" content=\"website").encode(),"https://example.no/blog/x"),[])
    def test_canonical_elsewhere(self):
        self.assertEqual(run((self.META%("99","NOK")+'<link rel="canonical" href="https://example.no/product/999">').encode()),[])
    def test_zero_price(self):self.assertEqual(run((self.META%("0","NOK")).encode()),[])
    def test_structured_product_without_price_blocks_metadata(self):
        self.assertEqual(run(ld({"@type":"Product","name":"N"})+(self.META%("99","NOK")).encode()),[])

class CrawlExtract(unittest.TestCase):
    def test_coupon_filters(self):
        self.assertEqual(list(crawl.coupon_extract(b"rabattkode: RABATT","a.no","https://a.no")),[])
        self.assertEqual(list(crawl.coupon_extract(b"rabattkode: ab","a.no","https://a.no")),[])
        self.assertEqual(list(crawl.coupon_extract(b"<script>rabattkode: SECRET20</script>","a.no","https://a.no")),[])
        self.assertEqual(list(crawl.coupon_extract(b"",  "a.no","https://a.no")),[])
        self.assertEqual(list(crawl.coupon_extract(b"<p>kampanjekode = SUMMER-25</p>","a.no","https://a.no"))[0]["code"],"SUMMER-25")
    def test_coupon_capitalised_label(self):
        self.assertEqual(list(crawl.coupon_extract(b"<p>Rabattkode: SOMMER25</p>","a.no","https://a.no"))[0]["code"],"SOMMER25")
    def test_extract_empty(self):
        self.assertEqual(list(crawl.extract(b"","https://a.no/p/1","a.no")),[])

class Robots(unittest.TestCase):
    def rp(self,body):return crawl.load_robots("a.no",lambda *a:body)
    def test_disallow(self):
        rp=self.rp(b"User-agent: *\nDisallow: /kasse\n")
        self.assertFalse(rp.can_fetch(crawl.UA,"https://a.no/kasse/1"));self.assertTrue(rp.can_fetch(crawl.UA,"https://a.no/p/1"))
    def test_disallow_all(self):self.assertFalse(self.rp(b"User-agent: *\nDisallow: /\n").can_fetch(crawl.UA,"https://a.no/"))
    def test_own_agent_rule(self):
        rp=self.rp(b"User-agent: PrisRadar\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
        self.assertFalse(rp.can_fetch(crawl.UA,"https://a.no/x"))
    def test_empty_robots_allows(self):self.assertTrue(self.rp(b"").can_fetch(crawl.UA,"https://a.no/x"))
    def test_missing_robots_404_410_allow(self):
        for c in (404,410):
            def f(*a,c=c):raise http(c)
            self.assertTrue(crawl.load_robots("a.no",f).can_fetch(crawl.UA,"https://a.no/x"))
    def test_robots_5xx_401_403_429_propagate(self):
        for c in (500,503,401,403,429):
            def f(*a,c=c):raise http(c)
            with self.assertRaises(urllib.error.HTTPError):crawl.load_robots("a.no",f)
    def test_robots_timeout_propagates(self):
        def f(*a):raise TimeoutError()
        with self.assertRaises(TimeoutError):crawl.load_robots("a.no",f)
    def test_crawl_delay(self):
        self.assertEqual(crawl.delay_for(self.rp(b"User-agent: *\nCrawl-delay: 10\n")),10)
        self.assertEqual(crawl.delay_for(self.rp(b"User-agent: *\nCrawl-delay: 0\n")),2)
        self.assertEqual(crawl.delay_for(self.rp(b"User-agent: *\n")),2)
        self.assertEqual(crawl.delay_for(None),2)
        self.assertEqual(crawl.delay_for(self.rp(b"User-agent: *\nRequest-rate: 1/20\n")),20)
    def test_excessive_delay_aborts_before_sleeping(self):
        rp=self.rp(b"User-agent: *\nCrawl-delay: 99\n")
        with patch.object(crawl.time,"sleep") as s,self.assertRaises(ValueError):crawl.throttle("a.no",rp)
        s.assert_not_called()
    def test_throttle_spaces_requests(self):
        crawl._last_request.clear()
        with patch.object(crawl.time,"sleep") as s:
            crawl.throttle("www.t.no",None);crawl.throttle("t.no",None)
        self.assertGreater(s.call_args[0][0],0)
    def test_same_host(self):
        self.assertTrue(crawl.same_host("WWW.a.no","a.no"));self.assertFalse(crawl.same_host("a.no","b.no"));self.assertFalse(crawl.same_host(None,"a.no"));self.assertFalse(crawl.same_host("a.no",""))

class FetchLayer(unittest.TestCase):
    DNS=[(2,1,6,"",("8.8.8.8",443))]
    def opener(self,body=b"ok",exc=None):
        m=MagicMock()
        if exc:m.open.side_effect=exc
        else:
            r=MagicMock();r.read.return_value=body;r.__enter__.return_value=r;m.open.return_value=r
        return m
    def fetch_once(self,url="https://a.no/x",host="a.no",robots=None,**kw):
        with patch.object(crawl.socket,"getaddrinfo",return_value=kw.get("dns",self.DNS)),patch.object(crawl,"opener",self.opener(kw.get("body",b"ok"),kw.get("exc"))),patch.object(crawl,"throttle"):
            return crawl.fetch_once(url,host,robots)
    def test_ok(self):self.assertEqual(self.fetch_once(),b"ok")
    def test_gzip(self):self.assertEqual(self.fetch_once(body=gzip.compress(b"hello")),b"hello")
    def test_oversize(self):
        with self.assertRaises(ValueError):self.fetch_once(body=b"x"*12000001)
    def test_gzip_bomb(self):
        with self.assertRaises(ValueError):self.fetch_once(body=gzip.compress(b"0"*12000001))
    def test_rejected_urls(self):
        for u in ("http://a.no/x","https://b.no/x","https://u:p@a.no/x","https://a.no:8443/x","ftp://a.no/x","https://a.no.evil.com/x"):
            with self.assertRaises(ValueError,msg=u):self.fetch_once(url=u)
    def test_private_address_rejected(self):
        for ip in ("127.0.0.1","10.0.0.5","169.254.169.254","192.168.1.1","::1"):
            with self.assertRaises(ValueError,msg=ip):self.fetch_once(dns=[(2,1,6,"",(ip,443))])
    def test_robots_block_before_network(self):
        rp=crawl.load_robots("a.no",lambda *a:b"User-agent: *\nDisallow: /x\n")
        o=self.opener()
        with patch.object(crawl.socket,"getaddrinfo",return_value=self.DNS),patch.object(crawl,"opener",o),self.assertRaises(ValueError):crawl.fetch_once("https://a.no/x","a.no",rp)
        o.open.assert_not_called()
    def test_http_errors_propagate(self):
        for c in (401,403,429,500,503):
            with self.assertRaises(urllib.error.HTTPError,msg=str(c)):self.fetch_once(exc=http(c))
    def test_timeout_and_urlerror_propagate(self):
        for e in (TimeoutError(),urllib.error.URLError("down"),ConnectionResetError()):
            with self.assertRaises(type(e)):self.fetch_once(exc=e)
    def test_redirect_followed_then_limited(self):
        def redir(loc):return urllib.error.HTTPError("u",301,"m",{"Location":loc},None)
        calls=[]
        def once(url,host,robots=None):
            calls.append(url)
            if len(calls)==1:raise redir("/b")
            return b"done"
        with patch.object(crawl,"fetch_once",once):self.assertEqual(crawl.fetch("https://a.no/a","a.no"),b"done")
        self.assertEqual(calls,["https://a.no/a","https://a.no/b"])
        with patch.object(crawl,"fetch_once",side_effect=lambda *a:(_ for _ in ()).throw(redir("/loop"))),self.assertRaises(ValueError):crawl.fetch("https://a.no/a","a.no")
    def test_redirect_without_location_and_403_not_followed(self):
        with patch.object(crawl,"fetch_once",side_effect=http(301)),self.assertRaises(urllib.error.HTTPError):crawl.fetch("https://a.no/a","a.no")
        with patch.object(crawl,"fetch_once",side_effect=http(403)),self.assertRaises(urllib.error.HTTPError):crawl.fetch("https://a.no/a","a.no")
    def test_redirect_to_other_host_blocked(self):
        exc=urllib.error.HTTPError("https://a.no/a",302,"m",{"Location":"https://evil.com/x"},None)
        with patch.object(crawl.socket,"getaddrinfo",return_value=self.DNS),patch.object(crawl,"opener",self.opener(exc=exc)),patch.object(crawl,"throttle"),self.assertRaises(ValueError):
            crawl.fetch("https://a.no/a","a.no")
    def test_error_detail(self):
        self.assertEqual(crawl.error_detail(http(429)),"HTTP 429")
        self.assertEqual(crawl.error_detail(TimeoutError("secret")),"TimeoutError")
        self.assertTrue(crawl.error_detail(ValueError("x")).startswith("ValueError"))
    def test_send_validations(self):
        crawl.send("offers",[],"url")  # empty: no env needed
        with patch.dict(os.environ,{"SUPABASE_URL":"https://evil.com","SUPABASE_SERVICE_ROLE_KEY":"k"}),self.assertRaises(ValueError):crawl.send("offers",[{"url":"u"}],"url")
    def test_send_dedupes_conflict_key(self):
        o=self.opener();sent=[]
        o.open.side_effect=lambda req,timeout=0:(sent.append(json.loads(req.data)),MagicMock())[1]
        with patch.dict(os.environ,{"SUPABASE_URL":"https://abc.supabase.co","SUPABASE_SERVICE_ROLE_KEY":"k"}),patch.object(crawl,"opener",o):
            crawl.send("offers",[{"url":"u","name":"n","price":1},{"url":"u","name":"n","price":2}],"url,name")
        self.assertEqual(sent,[[{"url":"u","name":"n","price":2}]])

class Brreg(unittest.TestCase):
    def test_normalise(self):
        for v,want in (("WWW.Butikk.NO","butikk.no"),("https://www.butikk.no/","butikk.no"),("http://butikk.no/a?b=1","butikk.no"),("butikk.no.","butikk.no"),("BUTIKK.NO/path","butikk.no"),("https://butikk.no:443/","butikk.no"),("  butikk.no  ","butikk.no"),("sub.butikk.no","sub.butikk.no")):
            self.assertEqual(brreg_seed.normalize_site(v),want,v)
    def test_rejected(self):
        for v in ("butikk.no:8080","http://u:p@butikk.no","facebook.com/x","m.facebook.com","www.instagram.com/x","linkedin.com","tiktok.com","youtube.com","linktr.ee/x","localhost","butikk","ftp://butikk.no","javascript:alert(1)","192.168.0.1","a b.no","","  ",None,5,[],"bütikk.no","-a.no","a..no","a.n"):
            self.assertIsNone(brreg_seed.normalize_site(v),repr(v))
    def test_overlong(self):
        self.assertIsNone(brreg_seed.normalize_site("a"*150+".no"))
    def test_rows(self):
        self.assertEqual(brreg_seed.rows_from_response({}),[])
        self.assertEqual(brreg_seed.rows_from_response({"_embedded":{}}),[])
        rows=brreg_seed.rows_from_response({"_embedded":{"enheter":[{"hjemmeside":"www.a.no","konkurs":True},{"hjemmeside":"b.no","underAvvikling":True},{"hjemmeside":"C.no"},{"hjemmeside":"www.c.no"},{"hjemmeside":None},{}]}})
        self.assertEqual([r["host"] for r in rows],["c.no"])
    def test_run_pages_and_writes(self):
        pages={0:{"page":{"totalPages":2},"_embedded":{"enheter":[{"hjemmeside":"a.no"}]}},1:{"_embedded":{"enheter":[{"hjemmeside":"b.no"}]}}}
        fetched=[];writes=[]
        def fetch(url,host,rp=None):
            fetched.append(url);return json.dumps(pages[int(re.search(r"page=(\d+)",url).group(1))]).encode()
        with patch.object(brreg_seed,"fetch",fetch),patch("crawl.load_robots",return_value=MagicMock()),patch.object(brreg_seed,"db",side_effect=lambda *a:writes.append(a)),patch.dict(os.environ,{"GITHUB_RUN_NUMBER":"0"}):
            brreg_seed.run()
        self.assertEqual([w[3][0]["host"] for w in writes],["a.no","b.no"])
        self.assertTrue(all(w[0]=="store_candidates" and "ignore-duplicates" in w[4] for w in writes))
    def test_run_empty_register_writes_nothing(self):
        writes=[]
        with patch.object(brreg_seed,"fetch",return_value=b'{"page":{"totalPages":0}}'),patch("crawl.load_robots",return_value=MagicMock()),patch.object(brreg_seed,"db",side_effect=lambda *a:writes.append(a)):
            brreg_seed.run()
        self.assertEqual(writes,[])
    def test_run_no_embedded_rows(self):
        writes=[]
        with patch.object(brreg_seed,"fetch",return_value=b'{"page":{"totalPages":1}}'),patch("crawl.load_robots",return_value=MagicMock()),patch.object(brreg_seed,"db",side_effect=lambda *a:writes.append(a)):
            brreg_seed.run()
        self.assertEqual(writes,[])
    def test_run_429_propagates(self):
        with patch.object(brreg_seed,"fetch",side_effect=http(429)),patch("crawl.load_robots",return_value=MagicMock()),self.assertRaises(urllib.error.HTTPError):brreg_seed.run()

class MerchantFeed(unittest.TestCase):
    B="https://shop.no/feed"
    def c(self,row,mh=None):return merchant_feed.clean(row,self.B,mh)
    def row(self,**kw):return dict({"title":"Abc","link":"https://shop.no/p/1","price":"1 299,00 NOK"},**kw)
    def test_price_nok_suffix(self):self.assertEqual(self.c(self.row())["price"],1299)
    def test_currency_column(self):self.assertEqual(self.c(self.row(price="1299.00",currency="NOK"))["price"],1299)
    def test_foreign_or_missing_currency_has_no_price(self):
        for kw in (dict(price="1299.00",currency="SEK"),dict(price="1299.00"),dict(price="1299.00 USD")):
            self.assertNotIn("price",self.c(self.row(**kw)))
    def test_used_has_no_price(self):
        for c in ("used","Refurbished","DAMAGED"):self.assertNotIn("price",self.c(self.row(condition=c)))
    def test_sale_price_recorded_separately(self):
        r=self.c(self.row(sale_price="999 NOK"));self.assertEqual((r["price"],r["sale_price"]),(1299,999))
    def test_bad_sale_price_ignored(self):self.assertNotIn("sale_price",self.c(self.row(sale_price="abc NOK")))
    def test_invalid_prices(self):
        for p in ("-1 NOK","0 NOK","NaN NOK","","99999999999 NOK"):self.assertNotIn("price",self.c(self.row(price=p)),p)
    def test_availability_map(self):
        for v,want in (("in stock","InStock"),("out of stock","OutOfStock"),("preorder","PreOrder"),("backorder","BackOrder"),("weird","")):
            self.assertEqual(self.c(self.row(availability=v))["availability"],want)
    def test_rejects_wrong_host_scheme_credentials_short_name(self):
        for kw in (dict(link="https://other.no/p"),dict(link="http://shop.no/p"),dict(link="https://u:p@shop.no/p"),dict(link="https://shop.no:8443/p"),dict(title="A"),dict(title=None),dict(link=None),dict(title="x"*501)):
            self.assertIsNone(self.c(self.row(**kw)),kw)
    def test_relative_link_and_fragment(self):
        self.assertEqual(self.c(self.row(link="/p/1#x"))["src"],"https://shop.no/p/1")
    def test_merchant_host_prefers_direct_and_ued(self):
        r=self.c(self.row(link="https://t.net/c?ued=https%3A%2F%2Fshop.no%2Fp%2F1"),"shop.no");self.assertEqual(r["src"],"https://shop.no/p/1")
        self.assertIsNone(self.c(self.row(link="https://t.net/c?ued=https%3A%2F%2Fevil.no%2Fp"),"shop.no"))
        self.assertIsNone(self.c(self.row(link="https://t.net/c?ued=http%3A%2F%2Fshop.no%2Fp"),"shop.no"))
    def test_gtin_checked(self):
        self.assertEqual(self.c(self.row(gtin="4006381333931"))["g"],"4006381333931")
        self.assertIsNone(self.c(self.row(gtin="4006381333932"))["g"])
    def test_parse_feed_csv_tsv_xml(self):
        self.assertEqual(next(merchant_feed.parse_feed(b"title,link,price,currency\nAbc,https://shop.no/p/1,99.50,NOK\n",self.B))["price"],99.5)
        self.assertEqual(next(merchant_feed.parse_feed(b"title\tlink\tprice\tcurrency\nAbc\thttps://shop.no/p/1\t99,50\tNOK\n",self.B))["price"],99.5)
        self.assertEqual(next(merchant_feed.parse_feed(b"\xef\xbb\xbf<rss><channel><item><title>Abc</title><link>https://shop.no/p</link><price>5 NOK</price></item></channel></rss>",self.B))["price"],5)
    def test_parse_feed_empty_and_header_only(self):
        self.assertEqual(list(merchant_feed.parse_feed(b"",self.B)),[])
        self.assertEqual(list(merchant_feed.parse_feed(b"title,link,price\n",self.B)),[])
    def test_parse_feed_xml_attacks_and_broken(self):
        with self.assertRaises(ValueError):list(merchant_feed.parse_feed(b'<!DOCTYPE x [<!ENTITY a "b">]><r/>',self.B))
        with self.assertRaises(Exception):list(merchant_feed.parse_feed(b"<rss><item>",self.B))
    def test_parse_feed_row_cap(self):
        body="title,link,price,currency\n"+"".join("Abc%d,https://shop.no/p/%d,5,NOK\n"%(i,i) for i in range(10005))
        self.assertEqual(len(list(merchant_feed.parse_feed(body.encode(),self.B))),10000)
    def test_feed_offers_filters(self):
        items=[{"src":"https://shop.no/a","n":"Abc","price":None},{"src":"https://other.no/b","n":"Abc","price":5},{"src":"https://shop.no/c","n":"Abc","price":5,"g":None},{"src":"https://shop.no/d","n":"Nope","price":5}]
        out=list(merchant_feed.feed_offers(items,"shop.no",lambda i:i["n"]=="Abc"))
        self.assertEqual([o["url"] for o in out],["https://shop.no/c"])
        self.assertEqual(out[0]["price_kind"],"exact")
    def test_cached_feed_caches_and_expires(self):
        merchant_feed._feed_cache.clear();calls=[]
        def f(url,host,rp):calls.append(url);return b"title,link,price,currency\nAbc,https://shop.no/p/1,5,NOK\n"
        merchant_feed.cached_feed("https://shop.no/f","shop.no",None,f);merchant_feed.cached_feed("https://shop.no/f","shop.no",None,f)
        self.assertEqual(len(calls),1)
        with patch.object(merchant_feed.time,"monotonic",return_value=merchant_feed.time.monotonic()+1000):merchant_feed.cached_feed("https://shop.no/f","shop.no",None,f)
        self.assertEqual(len(calls),2);merchant_feed._feed_cache.clear()
    def test_cache_bounded(self):
        merchant_feed._feed_cache.clear()
        for i in range(12):merchant_feed.cached_feed("https://shop.no/f%d"%i,"shop.no",None,lambda *a:b"")
        self.assertLessEqual(len(merchant_feed._feed_cache),8);merchant_feed._feed_cache.clear()
    def test_learn_assortment(self):
        with patch.object(merchant_feed,"db") as d:
            merchant_feed.learn_assortment("shop.no",[{"n":"AirPods Pro"},{"n":"Ukjent ting"}])
        self.assertEqual(d.call_args[0][3]["counts"],{"electronics":1})
        with patch.object(merchant_feed,"db") as d:
            merchant_feed.learn_assortment("shop.no",[{"n":"Ukjent ting"}]);d.assert_not_called()
        with patch.object(merchant_feed,"db",side_effect=http(404)):merchant_feed.learn_assortment("shop.no",[{"n":"airpods"}])
        with patch.object(merchant_feed,"db",side_effect=http(500)),self.assertRaises(urllib.error.HTTPError):merchant_feed.learn_assortment("shop.no",[{"n":"airpods"}])

class AffiliateFeed(unittest.TestCase):
    class RP:
        def __init__(s,ok=True):s.ok=ok
        def can_fetch(s,*a):return s.ok
    def setUp(self):affiliate_feed._cache.clear()
    def tearDown(self):affiliate_feed._cache.clear()
    def cfg(self,**kw):
        d={"provider":"awin","url":"https://f.com/x?k=SECRET","feed_host":"f.com"};d.update(kw);return {"env":patch.dict(os.environ,{"AFFILIATE_FEEDS_JSON":json.dumps({"a.no":d})})}
    def test_no_config(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop("AFFILIATE_FEEDS_JSON",None);self.assertEqual(affiliate_feed.affiliate_items("a.no"),())
    def test_invalid_config(self):
        for v in ("{bad","[]","null"):
            with patch.dict(os.environ,{"AFFILIATE_FEEDS_JSON":v}),self.assertRaises(ValueError):affiliate_feed.configurations()
        with patch.dict(os.environ,{"AFFILIATE_FEEDS_JSON":json.dumps({str(i):{} for i in range(51)})}),self.assertRaises(ValueError):affiliate_feed.configurations()
    def test_unknown_provider_url_and_host_mismatch(self):
        for kw in (dict(provider="x"),dict(url="http://f.com/x"),dict(url="https://u:p@f.com/x"),dict(url="https://f.com:8443/x"),dict(url="https://f.com/x#frag"),dict(feed_host="other.com")):
            with self.cfg(**kw)["env"],self.assertRaises(ValueError,msg=str(kw)):affiliate_feed.affiliate_items("a.no",lambda *a:b"",lambda h:self.RP())
    def test_robots_disallow(self):
        with self.cfg()["env"],self.assertRaises(ValueError):affiliate_feed.affiliate_items("a.no",lambda *a:b"",lambda h:self.RP(False))
    def test_failure_hides_secret(self):
        def boom(*a):raise RuntimeError("SECRET")
        with self.cfg()["env"],self.assertRaises(ValueError) as cm:affiliate_feed.affiliate_items("a.no",boom,lambda h:self.RP())
        self.assertNotIn("SECRET",str(cm.exception));self.assertIsNone(cm.exception.__cause__)
    def test_success_and_cache(self):
        n=[]
        def f(*a):n.append(1);return b"title,link,price,currency\nAbc,https://a.no/p/1,5,NOK\n"
        with self.cfg()["env"]:
            self.assertEqual(len(affiliate_feed.affiliate_items("a.no",f,lambda h:self.RP())),1)
            affiliate_feed.affiliate_items("a.no",f,lambda h:self.RP())
        self.assertEqual(len(n),1)
    def test_www_host_uses_same_config(self):
        with self.cfg()["env"]:
            self.assertEqual(len(affiliate_feed.affiliate_items("www.a.no",lambda *a:b"title,link,price,currency\nAbc,https://www.a.no/p/1,5,NOK\n",lambda h:self.RP())),1)
    def test_feed_http_error_wrapped(self):
        def f(*a):raise http(403)
        with self.cfg()["env"],self.assertRaises(ValueError):affiliate_feed.affiliate_items("a.no",f,lambda h:self.RP())

class Microdata(unittest.TestCase):
    T='<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">N</span><div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="priceCurrency" content="%s"><meta itemprop="price" content="%s"><link itemprop="availability" href="https://schema.org/InStock">%s</div></div>'
    def m(self,h,url=U):return sources.microdata(h.encode(),url,"example.no","x")
    def test_ok_and_formats(self):
        for p in ("1299.00","1 299,00","1.299,00"):
            self.assertEqual(self.m(self.T%("NOK",p,""))[0]["price"],1299)
    def test_availability(self):self.assertEqual(self.m(self.T%("NOK","5",""))[0]["availability"],"InStock")
    def test_foreign_currency(self):self.assertEqual(self.m(self.T%("SEK","5","")),[])
    def test_missing_currency(self):self.assertEqual(self.m((self.T%("NOK","5","")).replace('<meta itemprop="priceCurrency" content="NOK">',"")),[])
    def test_condition(self):
        for c in ("UsedCondition","RefurbishedCondition","DamagedCondition"):
            self.assertEqual(self.m(self.T%("NOK","5",'<link itemprop="itemCondition" href="https://schema.org/%s">'%c)),[])
        self.assertEqual(len(self.m(self.T%("NOK","5",'<link itemprop="itemCondition" href="https://schema.org/NewCondition">'))),1)
    def test_invalid_prices(self):
        for p in ("0","-5","abc","","NaN"):self.assertEqual(self.m(self.T%("NOK",p,"")),[],p)
    def test_member_price_ignored(self):
        self.assertEqual(self.m(self.T%("NOK","5",'<meta itemprop="validForMemberTier" content="Gold">')),[])
    def test_two_products_or_two_offers_ambiguous(self):
        self.assertEqual(self.m(self.T%("NOK","5","")+self.T%("NOK","6","")),[])
        two=self.T%("NOK","5","")
        self.assertEqual(self.m(two.replace("</div></div>",'</div><div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="priceCurrency" content="NOK"><meta itemprop="price" content="9"></div></div>')),[])
    def test_other_page_url_rejected(self):
        self.assertEqual(self.m(self.T%("NOK","5","")+'',"https://example.no/product/1")[0]["price"],5)
        self.assertEqual(self.m((self.T%("NOK","5","")).replace('<span itemprop="name">','<meta itemprop="url" content="https://example.no/other"><span itemprop="name">')),[])
    def test_broken_and_empty(self):
        for h in ("","<div itemscope","<div itemscope itemtype='https://schema.org/Product'><span itemprop='name'>N"):self.assertEqual(self.m(h),[])
    def test_candidate_hosts(self):
        raw=b'<a href="https://www.b.no/x">x</a><a href="http://c.no">y</a><a href="https://example.no/q">s</a><a href="https://d.com">z</a><a href="https://u:p@e.no">z</a><a href="https://f.no:8443/">z</a><a href="//g.no/x">z</a>'
        self.assertEqual(sources.candidate_hosts(raw,U),["g.no","www.b.no"])
        self.assertEqual(sources.candidate_hosts(b"",U),[])
        self.assertEqual(len(sources.candidate_hosts(b"".join(b'<a href="https://s%d.no/">x</a>'%i for i in range(50)),U)),20)

class StoreRankAndSearch(unittest.TestCase):
    def test_rank(self):
        self.assertEqual(store_rank.categories("AirPods Pro"),{"electronics"})
        self.assertEqual(store_rank.categories(""),set())
        self.assertGreater(store_rank.rank("power.no","airpods"),store_rank.rank("ikea.no","airpods"))
        self.assertEqual(store_rank.store_categories("www.power.no"),{"electronics"})
        self.assertEqual(store_rank.store_categories("ukjent.no"),set())
        self.assertGreater(store_rank.rank("ukjent.no","airpods",known=1),store_rank.rank("power.no","airpods"))
        self.assertEqual(store_rank.rank("ukjent.no","airpods",known=500),120)
    def test_relevant(self):
        self.assertFalse(store_rank.relevant("ikea.no","airpods"))
        self.assertTrue(store_rank.relevant("ikea.no","airpods",known=1))
        self.assertTrue(store_rank.relevant("ukjent.no","airpods"))
        self.assertTrue(store_rank.relevant("ikea.no","noe helt ukjent"))
    def test_search_url(self):
        self.assertEqual(store_search.search_url("a.no","/s?q={q}","a b&c"),"https://a.no/s?q=a%20b%26c")
        self.assertEqual(store_search.search_url("a.no","/s?q={q}","../x#"),"https://a.no/s?q=..%2Fx%23")
        for p in ("//evil/{q}","s?q={q}","/s","/a\\b{q}","",None):
            with self.assertRaises(ValueError,msg=str(p)):store_search.search_url("a.no",p,"q")
    def test_links(self):
        raw=b'<a href="/p/airpods-pro">Airpods Pro</a><a href="http://a.no/p/airpods-pro-2">x</a><a href="https://evil.no/p/airpods-pro">Airpods Pro</a><a href="/category/audio">Airpods</a><a href="/p/x#f">airpods pro</a><a href="https://u:p@a.no/p/airpods-pro">z</a><a>no href</a>'
        self.assertEqual(store_search.links(raw,"https://a.no/s","a.no","airpods pro"),["https://a.no/p/airpods-pro","https://a.no/p/x"])
        self.assertEqual(store_search.links(b"","https://a.no/s","a.no","airpods"),[])
        self.assertEqual(store_search.links(b'<a href="/p/1"',"https://a.no/s","a.no","airpods"),[])
    def test_links_capped_and_ordered(self):
        raw="".join('<a href="/p/airpods-%d">Airpods</a>'%i for i in range(30)).encode()
        self.assertEqual(len(store_search.links(raw,"https://a.no/s","a.no","airpods")),12)

class PublicSearchAndWoo(unittest.TestCase):
    class RP:
        def __init__(s,ok=True):s.ok=ok
        def can_fetch(s,*a):return s.ok
    def ps(self,adapter,payload,offers=None,rp=None):
        f=payload if callable(payload) else (lambda *a:payload if isinstance(payload,bytes) else json.dumps(payload).encode())
        return store_adapters.public_search("a.no",adapter,"q",rp or self.RP(),f,offers)
    def test_unknown_adapter(self):self.assertEqual(self.ps("generic",b"[]"),[])
    def test_robots_blocks(self):self.assertEqual(self.ps("shopify",b"{}",rp=self.RP(False)),[])
    def test_garbage_payloads(self):
        for p in (b"",b"not json",b"null",b"[]",b'{"resources":null}',b'{"resources":{"results":{"products":"x"}}}',b"[1,null,{}]",b'[{"permalink":5}]'):
            self.assertEqual(self.ps("woocommerce",p) if p.startswith(b"[") else self.ps("shopify",p),[],p)
    def test_http_errors(self):
        for c in (401,403,429):
            def f(*a,c=c):raise http(c)
            with self.assertRaises(urllib.error.HTTPError):self.ps("shopify",f)
        for exc in (http(404),http(500),TimeoutError(),urllib.error.URLError("x")):
            def f(*a,exc=exc):raise exc
            self.assertEqual(self.ps("shopify",f),[],repr(exc))
    def test_links_filtered_dedup(self):
        rows=[{"url":"/products/a"},{"url":"/products/a#v"},{"url":"https://evil.no/products/b"},{"url":"http://a.no/products/c"},{"url":"/"},{"url":"https://u:p@a.no/p"}]
        out=self.ps("shopify",{"resources":{"results":{"products":rows}}})
        self.assertEqual(out,["https://a.no/products/a"])
    def woo(self,**kw):
        row={"type":"simple","is_purchasable":True,"name":"Hp &amp; Co","prices":{"currency_code":"NOK","currency_minor_unit":2,"price":"129900"},"is_in_stock":True,"permalink":"https://a.no/p/1"}
        row.update(kw);return row
    def test_woo_ore_to_kroner(self):
        o=store_adapters.woo_offer(self.woo(),"a.no","https://a.no/p/1")
        self.assertEqual((o["price"],o["name"],o["availability"]),(1299,"Hp & Co","InStock"))
        o=store_adapters.woo_offer(self.woo(prices={"currency_code":"NOK","currency_minor_unit":0,"price":"1299"}),"a.no","u")
        self.assertEqual(o["price"],1299)
    def test_woo_rejections(self):
        base=self.woo()["prices"]
        for kw in (dict(type="variable"),dict(is_purchasable=False),dict(has_options=True),dict(price_range={"a":1}),dict(condition="used"),dict(condition="refurbished"),dict(name=" "),dict(name=None),dict(prices=None),
                   dict(prices=dict(base,currency_code="SEK")),dict(prices=dict(base,price_range={"min":1})),dict(prices=dict(base,price="-5")),dict(prices=dict(base,price="abc")),dict(prices=dict(base,price="0")),dict(prices=dict(base,currency_minor_unit=9)),dict(prices=dict(base,currency_minor_unit="2")),dict(prices=dict(base,currency_minor_unit=True))):
            self.assertIsNone(store_adapters.woo_offer(self.woo(**kw),"a.no","u"),kw)
    def test_woo_availability_variants(self):
        self.assertEqual(store_adapters.woo_offer(self.woo(is_in_stock=False),"a.no","u")["availability"],"OutOfStock")
        self.assertEqual(store_adapters.woo_offer(self.woo(is_in_stock=None),"a.no","u")["availability"],"")
    def test_woo_api_gives_urls_only(self):
        # Store API prices may be ex. VAT with no flag: the product page JSON-LD supplies the price.
        offers=[];out=self.ps("woocommerce",[self.woo()],offers)
        self.assertEqual(out,["https://a.no/p/1"]);self.assertEqual(offers,[])
    def test_profile_edge(self):
        for raw in (b"",b"<html>",b"\xff\xfe"):
            p=store_adapters.profile(raw,"https://a.no/");self.assertFalse(p["shop"]);self.assertEqual(p["currency_hint"],"unknown")
        self.assertEqual(store_adapters.profile(b'<script src="/wp-content/plugins/woocommerce/x.js"></script>',"https://a.no/")["search_path"],"/?s={q}&post_type=product")
        self.assertEqual(store_adapters.profile(b'<script type="application/ld+json">{"@type":"Product","name":"x","offers":{"priceCurrency":"NOK"}}</script>',"https://a.no/")["currency_hint"],"NOK")

class DurableAndDemand(unittest.TestCase):
    def test_db_rejects_bad_url_and_needs_env(self):
        with patch.dict(os.environ,{"SUPABASE_URL":"https://evil.com","SUPABASE_SERVICE_ROLE_KEY":"k"}),self.assertRaises(ValueError):durable.db("offers")
        with patch.dict(os.environ,{"SUPABASE_URL":"http://abc.supabase.co","SUPABASE_SERVICE_ROLE_KEY":"k"}),self.assertRaises(ValueError):durable.db("offers")
    def fake_opener(self,body):
        m=MagicMock();r=MagicMock();r.read.return_value=body;r.__enter__.return_value=r;m.open.return_value=r;return m
    def test_db_empty_and_json_bodies(self):
        env={"SUPABASE_URL":"https://abc.supabase.co/","SUPABASE_SERVICE_ROLE_KEY":"k"}
        with patch.dict(os.environ,env):
            with patch.object(durable,"opener",self.fake_opener(b"")):self.assertIsNone(durable.db("offers"))
            with patch.object(durable,"opener",self.fake_opener(b"[]")):self.assertEqual(durable.db("offers",{"a":"b"}),[])
            o=self.fake_opener(b"[{\"id\":1}]")
            with patch.object(durable,"opener",o):self.assertEqual(durable.db("offers",None,"POST",{"x":1},"return=minimal"),[{"id":1}])
            req=o.open.call_args[0][0];self.assertEqual(req.get_method(),"POST");self.assertEqual(req.headers["Prefer"],"return=minimal")
    def test_db_http_error_propagates(self):
        with patch.dict(os.environ,{"SUPABASE_URL":"https://abc.supabase.co","SUPABASE_SERVICE_ROLE_KEY":"k"}),patch.object(durable,"opener",MagicMock(open=MagicMock(side_effect=http(500)))),self.assertRaises(urllib.error.HTTPError):durable.db("offers")
    def test_words_relevance(self):
        self.assertEqual(durable.words("Æble-Pære 3x"),["æble","pære","3x"]);self.assertEqual(durable.words(""),[])
        self.assertEqual(durable.relevance("https://a.no/p/airpods-pro","AirPods Pro"),2)
        self.assertEqual(durable.relevance("https://a.no/p/air%70ods","airpods"),1)
    def test_discover_empty_sitemap_and_errors(self):
        rp=crawl.load_robots("a.no",lambda *a:b"")
        for effect in (lambda *a:b"<urlset/>",lambda *a:b"not xml",lambda *a:(_ for _ in ()).throw(http(404)),lambda *a:(_ for _ in ()).throw(http(500))):
            with patch.object(durable,"fetch",effect):self.assertEqual(durable.discover("a.no",rp,[5]),[])
    def test_discover_403_429_raise(self):
        rp=crawl.load_robots("a.no",lambda *a:b"")
        for c in (401,403,429):
            with patch.object(durable,"fetch",side_effect=http(c)),self.assertRaises(urllib.error.HTTPError):durable.discover("a.no",rp,[5])
    def test_discover_filters_hosts_and_sorts(self):
        rp=crawl.load_robots("a.no",lambda *a:b"")
        xml=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://a.no/om-oss</loc></url><url><loc>https://a.no/product/1</loc></url><url><loc>https://evil.no/product/2</loc></url><url><loc>http://a.no/product/3</loc></url></urlset>'
        with patch.object(durable,"fetch",return_value=xml):self.assertEqual(durable.discover("a.no",rp,[5]),["https://a.no/product/1","https://a.no/om-oss"])
    def test_discover_budget_zero(self):
        rp=crawl.load_robots("a.no",lambda *a:b"")
        with patch.object(durable,"fetch") as f:self.assertEqual(durable.discover("a.no",rp,[0]),[]);f.assert_not_called()
    def test_matches(self):
        self.assertTrue(demand.matches("Apple AirPods Pro 2","airpods pro 2"))
        self.assertFalse(demand.matches("AirPods Pro 2 deksel","airpods pro 2"))
        self.assertTrue(demand.matches("AirPods Pro 2 deksel","airpods deksel"))
        self.assertFalse(demand.matches("Apple AirPods 3","airpods 4"))
        self.assertFalse(demand.matches("AirPods","")) 
        self.assertFalse(demand.matches("Sony hodetelefon","airpods"))
    def test_offer_matches_gtin_and_model(self):
        self.assertTrue(demand.offer_matches("x","4006381333931",None,"4006381333931"))
        self.assertTrue(demand.offer_matches("x","04006381333931",None,"4006381333931"))
        self.assertFalse(demand.offer_matches("airpods","5901234123457",None,"4006381333931"))
        self.assertTrue(demand.offer_matches("x",None,"ABC-1","abc-1"))
        self.assertFalse(demand.offer_matches("x",None,"","abc-1"))
    def test_run_refuses_when_db_not_ready(self):
        for health in ({"ready":False,"version":2026112707,"missing":["x"]},{"ready":True,"version":1},{}):
            with patch.object(demand,"db",return_value=health),self.assertRaises(SystemExit):demand.run()
        with patch.object(demand,"db",side_effect=http(404)),self.assertRaises(SystemExit):demand.run()
    def test_optional_assortment(self):
        with patch.object(demand,"db_all",return_value=[]):self.assertEqual(demand.optional_assortment(),[])
        with patch.object(demand,"db_all",side_effect=http(404)):self.assertEqual(demand.optional_assortment(),[])
        with patch.object(demand,"db_all",side_effect=http(500)),self.assertRaises(urllib.error.HTTPError):demand.optional_assortment()

class Migrations(unittest.TestCase):
    def migrations(self):return sorted((ROOT/"supabase"/"migrations").glob("2*.sql"))
    def test_migrations_idempotent(self):
        for f in self.migrations():
            sql=f.read_text()
            for m in re.finditer(r"(?im)^\s*create\s+(?!or\s+replace|extension\s+if|table\s+if|index\s+if|unique\s+index\s+if|schema\s+if)(table|index|unique\s+index|trigger|policy|type)\b[^;\n]*",sql):
                pre=sql[max(0,m.start()-120):m.start()]
                self.assertRegex(pre,r"(?is)drop\s+(trigger|policy)\s+if\s+exists[^;]*;\s*$",f.name+": "+m.group().strip())
            for m in re.finditer(r"(?im)^\s*alter\s+table\s+\S+\s+add\s+column\s+(?!if\s+not\s+exists)",sql):self.fail(f.name+": add column without if not exists")
            for m in re.finditer(r"(?im)^\s*insert\s+into\s+public\.schema_migrations[^;]*;",sql):self.assertIn("on conflict",m.group().lower(),f.name)
    def test_each_migration_registers_own_version(self):
        for f in self.migrations():
            self.assertRegex(f.read_text().replace(" ",""),r"schema_migrations\(version\)values\(%s\)"%f.stem)
    def test_guard_price_jump_semantics_in_latest_definition(self):
        sql=(ROOT/"supabase"/"migrations"/"2026112707.sql").read_text()
        body=sql[sql.index("guard_price_jump"):sql.index("$$;")]
        self.assertIn("interval '1 hour'",body)
        self.assertIn("old.pending_price is not null",body)
        self.assertIn("abs(new.price-old.pending_price)<0.01",body)
        self.assertIn("old.price_kind=new.price_kind",body)
        self.assertIn("0.4",body);self.assertIn("1.6",body)
        self.assertIn("review_required:=false",body.split("end if;")[0])
    def test_trigger_is_attached_by_a_migration(self):
        self.assertTrue(any("create trigger guard_price_jump" in f.read_text() for f in self.migrations()))

class MemberPrices(unittest.TestCase):
    def offers(self,*offers):return ld(prod(list(offers),url=U))
    def test_conditional_prices_documented_separately(self):
        raw=self.offers({"price":99,"priceCurrency":"NOK"},{"price":79,"priceCurrency":"NOK","validForMemberTier":{"name":"Club"}})
        rows=list(conditional_prices(raw,U))
        self.assertEqual([(r["price"],r["condition"]) for r in rows],[(79,"Club")])
        self.assertEqual(run(raw)[0]["price"],99)
    def test_conditional_prices_rejections(self):
        for o in ({"price":79,"priceCurrency":"SEK","validForMemberTier":"Club"},{"price":0,"priceCurrency":"NOK","validForMemberTier":"Club"},{"price":79,"priceCurrency":"NOK","validForMemberTier":"  "},{"price":79,"priceCurrency":"NOK","validForMemberTier":{}},{"price":79,"priceCurrency":"NOK","validForMemberTier":"Club","eligibleQuantity":{"minValue":2}},{"price":79,"priceCurrency":"NOK"}):
            self.assertEqual(list(conditional_prices(self.offers(o),U)),[],o)
    def test_conditional_prices_other_product_or_garbage(self):
        self.assertEqual(list(conditional_prices(ld(prod([{"price":79,"priceCurrency":"NOK","validForMemberTier":"C"}],url="https://example.no/other")),U)),[])
        for raw in (b"",b"<script type='application/ld+json'>{bad</script>"):self.assertEqual(list(conditional_prices(raw,U)),[])
    def test_extract_never_lets_member_price_replace_public_price(self):
        raw=self.offers({"price":99,"priceCurrency":"NOK"},{"price":79,"priceCurrency":"NOK","validForMemberTier":"Club"})
        o=list(crawl.extract(raw,U,"example.no"))[0]
        self.assertEqual((o["price"],o["price_kind"]),(99,"exact"))
        self.assertEqual(o["member_prices"],[{"price":79,"condition":"Club","source":U}])
    def test_extract_without_member_prices(self):
        o=list(crawl.extract(ld(prod({"price":99,"priceCurrency":"NOK"},url=U)),U,"example.no"))[0]
        self.assertEqual(o["member_prices"],[])
    def test_extract_member_only_page_yields_nothing(self):
        self.assertEqual(list(crawl.extract(self.offers({"price":79,"priceCurrency":"NOK","validForMemberTier":"Club"}),U,"example.no")),[])

if __name__=="__main__":unittest.main()

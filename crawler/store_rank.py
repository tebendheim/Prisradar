"""Store assortment hints; unknown categories are not treated as exclusions."""
from durable import words
GROUPS={
 "electronics": "airpods hodetelefon headphones iphone ipad macbook laptop pc skjerm tv kamera mobil robotstøvsuger playstation xbox samsung apple garmin".split(),
 "sport": "ski sykkel løpesko telt sovepose tursekk fjellsko squash".split(),
 "home": "gryte stekepanne kjøkken kniv kaffetrakter blender kjøkkenmaskin tallerken mummikopp".split(),
 "fashion": "kjole bukse jakke genser skjorte ullsokker".split(),
 "beauty": "parfyme mascara sjampo serum leppestift".split(),
 "building": "drill skrutrekker sag maling verktøy".split(),
 "furniture": "sofa seng madrass spisebord stol".split()
}
STORES={
 "electronics":"power elkjop komplett eplehuset proshop netonnet multicom dustin kjell teknikmagasinet computersalg cdon deal.no digitalimpuls foto.no scandinavianphoto".split(),
 "sport":"fjellsport xxl sport1 intersport outnorth milrab anton sportshopen bikeshop løplabbet".split(),
 "home":"jernia kitchn bakerenogkokken tilbords christiania-glasmagasin kitchenone royaldesign nordicnest".split(),
 "fashion":"zalando boozt match dressmann volt cubus hm carlings".split(),
 "beauty":"lyko kicks vita blivakker fredrikoglouisa".split(),
 "building":"clasohlson biltema jula obsbygg maxbo byggmakker megaflis".split(),
 "furniture":"ikea jysk bohus skeidar trademax".split()
}
def categories(q):
    tokens=set(words(q))
    return {k for k,v in GROUPS.items() if tokens.intersection(v)}
def store_categories(host):
    label=host.removeprefix("www.").split(".")[0]
    return {k for k,v in STORES.items() if label in v}
def rank(host,q,known=0,history=0):
    a,b=categories(q),store_categories(host)
    return (100 if known else 0)+min(known,20)+(35 if a&b else -40 if a and b else 0)+min(history,15)
def relevant(host,q,known=0):
    a,b=categories(q),store_categories(host)
    return bool(known or not a or not b or a&b)

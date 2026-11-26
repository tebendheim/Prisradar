"""Import a legally reusable local CSV catalogue without fetching product prices.
CSV columns: name, source. Source must identify the catalogue/provider.
Run with the existing Supabase service credentials in a trusted environment.
"""
import csv,sys
from durable import db

def run(path):
    batch={}
    with open(path,encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            name=(row.get("name") or "").strip()
            source=(row.get("source") or "").strip()
            if not (2<=len(name)<=500 and 1<=len(source)<=1500):continue
            batch[name]={"name":name,"source":source}
            if len(batch)>=500:
                db("product_catalog",{"on_conflict":"name"},"POST",list(batch.values()),"resolution=ignore-duplicates,return=minimal");batch.clear()
        if batch:db("product_catalog",{"on_conflict":"name"},"POST",list(batch.values()),"resolution=ignore-duplicates,return=minimal")
if __name__=="__main__":run(sys.argv[1])

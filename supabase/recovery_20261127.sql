begin;
create or replace function public.catalog_capacity_v1() returns jsonb language sql stable security definer set search_path='' as $fn$
select jsonb_build_object('bytes',pg_database_size(current_database()),'allowed',pg_database_size(current_database())<350000000)
$fn$;
revoke all on function public.catalog_capacity_v1() from public,anon,authenticated;
grant execute on function public.catalog_capacity_v1() to service_role;



create or replace function public.learn_catalog_batch_v1(items jsonb) returns integer language plpgsql security definer set search_path='' as $fn$
declare r jsonb; n integer:=0;
begin
 if jsonb_typeof(items) is distinct from 'array' or jsonb_array_length(items)>100 then raise exception 'Invalid batch';end if;
 if pg_database_size(current_database())>=350000000 then return 0;end if;
 for r in select value from jsonb_array_elements(items) loop
  perform public.learn_catalog_v1(r->>'n',r->>'src',r->>'g');n:=n+1;
 end loop;
 return n;
end $fn$;
revoke all on function public.learn_catalog_batch_v1(jsonb) from public,anon,authenticated;
grant execute on function public.learn_catalog_batch_v1(jsonb) to service_role;



insert into public.store_candidates(host,source) values
('www.multicom.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.dustinhome.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.kjell.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.computersalg.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.cdon.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.scandinavianphoto.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.foto.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.xxl.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.sport1.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.intersport.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.outnorth.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.milrab.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.antonsport.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.bikeshop.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.loplabbet.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.tilbords.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.cg.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.kitchenone.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.royaldesign.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.nordicnest.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.zalando.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.boozt.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.matchfashion.no','manual expansion candidate; verify Norway delivery and crawl permission'),('dressmann.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.cubus.com','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.lyko.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.kicks.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.vita.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.blivakker.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.fredrikoglouisa.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.clasohlson.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.biltema.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.jula.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.obsbygg.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.maxbo.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.byggmakker.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.megaflis.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.ikea.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.jysk.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.bohus.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.skeidar.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.trademax.no','manual expansion candidate; verify Norway delivery and crawl permission'),
('www.ark.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.norli.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.adlibris.com','manual expansion candidate; verify Norway delivery and crawl permission'),('www.extra-leker.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.jollyroom.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.babyshop.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.apotek1.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.vitusapotek.no','manual expansion candidate; verify Norway delivery and crawl permission'),('www.farmasiet.no','manual expansion candidate; verify Norway delivery and crawl permission')
on conflict(host) do nothing;

alter table public.managed_stores add column if not exists feed_path text;
alter table public.managed_stores add column if not exists delivery_evidence text;
alter table public.managed_stores add column if not exists delivery_checked timestamptz;
create table if not exists public.store_assortment(host text not null references public.managed_stores(host) on delete cascade, category text not null, samples bigint not null default 0, updated timestamptz not null default now(), primary key(host,category));
alter table public.store_assortment enable row level security;
revoke all on public.store_assortment from public,anon,authenticated;
grant all on public.store_assortment to service_role;
create or replace function public.record_assortment_v1(h text,counts jsonb) returns void language plpgsql security definer set search_path='' as $fn$
begin
 insert into public.store_assortment(host,category,samples) select h,key,least(1000,greatest(0,value::bigint)) from jsonb_each_text(counts) where key in ('electronics','sport','home','fashion','beauty','building','furniture') on conflict(host,category) do update set samples=least(1000000,store_assortment.samples+excluded.samples),updated=now();
end $fn$;
revoke all on function public.record_assortment_v1(text,jsonb) from public,anon,authenticated;
grant execute on function public.record_assortment_v1(text,jsonb) to service_role;
create or replace function public.configure_store_v1(h text,p text,active boolean,feed text,evidence text) returns void language plpgsql security definer set search_path='' as $fn$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501';end if;
 h:=lower(trim(h));p:=nullif(trim(p),'');feed:=nullif(trim(feed),'');evidence:=nullif(trim(evidence),'');
 if h is null or length(h)>150 or h !~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?([.][a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' or h !~ '[.][a-z]{2,24}$' then raise exception 'Invalid store hostname';end if;
 if p is not null and (length(p)>300 or left(p,1)<>'/' or left(p,2)='//' or strpos(p,'{q}')=0 or strpos(p,chr(92))>0 or p ~ '[[:cntrl:]]') then raise exception 'Invalid search path';end if;
 if feed is not null and (length(feed)>1000 or left(feed,1)<>'/' or left(feed,2)='//' or strpos(feed,chr(92))>0 or feed ~ '[[:cntrl:]]') then raise exception 'Invalid feed path';end if;
 if evidence is not null and length(evidence)>1000 then raise exception 'Evidence too long';end if;
 if not exists(select 1 from public.managed_stores where host=h) and (select count(*) from public.managed_stores)>=500 then raise exception 'Store limit';end if;
 if coalesce(active,false) and not exists(select 1 from public.managed_stores where host=h and enabled) and evidence is null then raise exception 'Confirm Norway delivery before enabling';end if;
 insert into public.managed_stores(host,search_path,enabled,feed_path,delivery_evidence,delivery_checked) values(h,p,coalesce(active,false),feed,evidence,case when evidence is not null then now() end)
 on conflict(host) do update set search_path=excluded.search_path,enabled=excluded.enabled,feed_path=excluded.feed_path,delivery_evidence=coalesce(excluded.delivery_evidence,managed_stores.delivery_evidence),delivery_checked=coalesce(excluded.delivery_checked,managed_stores.delivery_checked);
end $fn$;
revoke all on function public.configure_store_v1(text,text,boolean,text,text) from public,anon;
grant execute on function public.configure_store_v1(text,text,boolean,text,text) to authenticated;



create or replace function public.display_model_v1(n text) returns text language sql immutable set search_path='' as $fn$
select case when lower(n) ~ '^(apple )?airpods pro 3([ .]|$)' and lower(n) !~ '(etui alene|case only|deksel|reservedel|replacement|ear tips|ørepropper alene|tilbehør)' then 'Apple AirPods Pro 3'
when lower(n) ~ '^(apple )?airpods pro 2([ .]|$)' and lower(n) !~ '(deksel|reservedel|replacement|case only|etui alene)' then 'Apple AirPods Pro 2'
else trim(n) end
$fn$;
create or replace function public.browse_models_v1(q text) returns table(name text,source text) language sql stable security definer set search_path='' as $fn$
with input as (select public.catalog_key_v1(q) k), hits as (
select p.identity_key,public.display_model_v1(p.name) label,p.source,
max(case when a.search_key=i.k then 4 when strpos(a.search_key,i.k)>0 then 3 when i.k in ('hodetelefoner','hodetelefon','headphones') and a.search_key ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)' then 2 else extensions.word_similarity(i.k,a.search_key) end) score
from public.catalog_products p join public.catalog_aliases a using(identity_key) cross join input i
where (select public.is_member()) and length(i.k) between 2 and 160 and (strpos(a.search_key,i.k)>0 or (i.k in ('hodetelefoner','hodetelefon','headphones') and a.search_key ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)') or (length(i.k)>=4 and a.search_key operator(extensions.%>) i.k))
group by p.identity_key,p.name,p.source
), grouped as (select distinct on(label) label,source,score from hits order by label,score desc,source)
select label,source from grouped order by score desc,length(label),label limit 100
$fn$;
create or replace function public.suggest_products_v1(q text) returns table(name text,source text) language sql stable security definer set search_path='' as $fn$
select * from public.browse_models_v1(q) limit 12
$fn$;
revoke all on function public.browse_models_v1(text),public.display_model_v1(text) from public,anon;
grant execute on function public.browse_models_v1(text),public.display_model_v1(text) to authenticated,service_role;
create or replace function public.category_offers_v1(q text) returns table(id bigint,name text,host text,url text,gtin text,model text,price numeric,shipping numeric,total_price numeric,availability text,checked timestamptz)
language sql stable security invoker set search_path='' as $fn$
select o.id,o.name,o.host,o.url,o.gtin,o.model,o.price,o.shipping,o.price+o.shipping,o.availability,o.checked
from public.offers o where (select public.is_member()) and length(trim(q)) between 2 and 160
and (strpos(lower(o.name),lower(trim(q)))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',q)
or (lower(trim(q)) in ('hodetelefoner','hodetelefon','headphones') and lower(o.name) ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)'))
order by o.checked desc,o.price limit 200
$fn$;
revoke all on function public.category_offers_v1(text) from public,anon;
grant execute on function public.category_offers_v1(text) to authenticated;



insert into public.store_candidates(host,source) values
('hifiklubben.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.whiteaway.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.skousen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.maxgaming.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.elektroimportoren.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.telia.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.telenor.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.stormberg.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.bergans.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.norrona.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.sportoutlet.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.oslosportslager.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.skittfiske.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.braasport.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.foss-sport.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.sportsmaster.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.treningspartner.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.getinspired.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.kid.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.nille.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.europris.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.rusta.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.plantasjen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.monter.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.byggmax.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.felleskjopet.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.barnashus.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.lekekassen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.outland.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.panduro.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.platekompaniet.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.musti.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.dyrekassen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.bilxtra.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.mekonomen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.lampehuset.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.bolia.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.mobelringen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.fagmobler.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.lindex.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.kappahl.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.eurosko.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.dinsko.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.skoringen.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.ginatricot.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.carlings.com','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.ellos.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.coolshop.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.coolstuff.no','Store directory candidate; verify host, Norway delivery and access before activation'),
('www.gullfunn.no','Store directory candidate; verify host, Norway delivery and access before activation')
on conflict(host) do nothing;
insert into public.managed_stores(host,enabled,delivery_evidence,delivery_checked) values ('www.xxl.no',true,'https://www.xxl.no/kundeservice/frakt-og-levering',now()) on conflict(host) do nothing;

commit;
notify pgrst,'reload schema';

SELECT to_regclass('public.store_assortment') AS sortiment, to_regprocedure('public.record_assortment_v1(text,jsonb)') AS laering, to_regprocedure('public.learn_catalog_batch_v1(jsonb)') AS katalogimport, to_regprocedure('public.catalog_capacity_v1()') AS kapasitet, to_regprocedure('public.browse_models_v1(text)') AS modellsok, to_regprocedure('public.category_offers_v1(text)') AS kategorisok;

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



commit;
notify pgrst,'reload schema';

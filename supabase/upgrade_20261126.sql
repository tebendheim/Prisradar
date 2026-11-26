begin;
create table if not exists public.managed_stores(host text primary key, search_path text, enabled boolean not null default true, paused_until timestamptz);
alter table public.managed_stores enable row level security;
revoke all on public.managed_stores from public,anon,authenticated;
grant all on public.managed_stores to service_role;
grant select on public.managed_stores to authenticated;
drop policy if exists admin_store_read on public.managed_stores;
create policy admin_store_read on public.managed_stores for select to authenticated using(exists(select 1 from public.members where user_id=auth.uid() and role='admin'));
insert into public.managed_stores(host,search_path) values ('www.power.no',null),('www.komplett.no','/search?q={q}'),('www.elkjop.no',null),('www.eplehuset.no',null),('www.fjellsport.no',null),('www.jernia.no',null),('www.kitchn.no',null),('www.bakerenogkokken.no',null),('www.proshop.no',null),('www.netonnet.no',null) on conflict do nothing;
create or replace function public.save_store_v1(h text,p text,active boolean) returns void language plpgsql security definer set search_path='' as $$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 h:=lower(trim(h));p:=nullif(trim(p),'');
 if h is null or length(h)>150 or h !~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' or h !~ '\.no$' then raise exception 'Use Norwegian store hostname';end if;
 if p is not null and (length(p)>300 or left(p,1)<>'/' or left(p,2)='//' or strpos(p,'{q}')=0 or strpos(p,chr(92))>0 or p ~ '[[:cntrl:]]') then raise exception 'Use relative search path containing {q}';end if;
 if not exists(select 1 from public.managed_stores where host=h) and (select count(*) from public.managed_stores)>=500 then raise exception 'Store limit';end if;
 insert into public.managed_stores(host,search_path,enabled) values(h,p,coalesce(active,false)) on conflict(host) do update set search_path=excluded.search_path,enabled=excluded.enabled;
end $$;
create or replace function public.touch_search_v1(q text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare normalized text; due timestamptz; n bigint;
begin
 if not (select public.is_member()) then raise exception 'Membership required' using errcode='42501'; end if;
 normalized:=lower(regexp_replace(trim(q),'[[:space:]]+',' ','g'));
 if normalized is null or length(normalized) not between 2 and 160 then raise exception 'Invalid query'; end if;
 perform pg_catalog.pg_advisory_xact_lock(812340023);
 if not exists(select 1 from public.active_searches where query=normalized) and (select count(*) from public.active_searches)>=500 then raise exception 'Active search limit';end if;
 insert into public.active_searches(query) values(normalized) on conflict(query) do update set last_searched=now() returning next_check into due;

 insert into public.search_offer_links(query,offer_id)
 select normalized,o.id from public.offers o where o.gtin=normalized or lower(o.model)=normalized or strpos(lower(o.name),normalized)>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',normalized)
 on conflict do nothing;

 select count(*) into n from public.search_offer_links where query=normalized;
 return jsonb_build_object('query',normalized,'due',due<=now(),'offers',n);
end $$;

create or replace function public.suggest_products_v1(q text) returns table(name text,source text)
language sql stable security definer set search_path='' as $$
select distinct on(lower(c.name)) c.name,c.source from public.product_catalog c where (select public.is_member()) and length(trim(q)) between 2 and 160 and c.source<>'search' and strpos(lower(c.name),lower(trim(q)))>0 order by lower(c.name),c.name limit 12
$$;
create or replace function public.search_progress_v1(q text) returns jsonb language sql stable security definer set search_path='' as $$
select jsonb_build_object('last_attempt',a.last_attempt,'next_check',a.next_check) from public.active_searches a where (select public.is_member()) and a.query=lower(regexp_replace(trim(q),'[[:space:]]+',' ','g'))
$$;
revoke all on function public.save_store_v1(text,text,boolean),public.search_progress_v1(text) from public,anon;
grant execute on function public.save_store_v1(text,text,boolean),public.search_progress_v1(text) to authenticated;
-- Normalize only formatting, preserving model numbers and variants.
create or replace function public.catalog_key_v1(n text) returns text
language sql immutable set search_path='' as $fn$
select trim(regexp_replace(lower(n),'[^[:alnum:]æøå]+',' ','g'))
$fn$;
create index if not exists catalog_key_idx on public.product_catalog(public.catalog_key_v1(name));
alter table public.product_catalog add column if not exists gtin text;
create index if not exists catalog_gtin_idx on public.product_catalog(gtin) where gtin is not null;
-- Canonical identity and aliases, independent of prices.
create table if not exists public.catalog_products (
 identity_key text primary key, name text not null, gtin text unique, source text not null
);
create table if not exists public.catalog_aliases (
 identity_key text not null references public.catalog_products(identity_key) on delete cascade,
 name text not null, search_key text not null, primary key(identity_key,search_key)
);
alter table public.catalog_products enable row level security;
alter table public.catalog_aliases enable row level security;
revoke all on public.catalog_products,public.catalog_aliases from public,anon,authenticated;
grant all on public.catalog_products,public.catalog_aliases to service_role;
create extension if not exists pg_trgm with schema extensions;
create index if not exists catalog_alias_trgm on public.catalog_aliases using gin(search_key extensions.gin_trgm_ops);
create index if not exists price_history_offer_checked on public.price_history(offer_id,checked desc);
create index if not exists crawl_dispatches_time on public.crawl_dispatches(requested_at);
create or replace function public.valid_gtin_v1(g text) returns text language plpgsql immutable set search_path='' as $fn$
declare total int:=0; i int; n int;
begin
 if g is null or g !~ '^([0-9]{8}|[0-9]{12,14})$' or g ~ '^0+$' then return null;end if;
 n:=length(g);
 for i in 1..n loop total:=total+substr(g,i,1)::int*(case when (n-i)%2=1 then 3 else 1 end);end loop;
 if total%10<>0 then return null;end if;
 return lpad(g,14,'0');
end $fn$;
create or replace function public.learn_catalog_v1(n text,src text,g text default null) returns void language plpgsql security definer set search_path='' as $fn$
declare k text; nk text; oldkey text;
begin
 if n is null or length(trim(n)) not between 2 and 500 or src is null or src='search' then return;end if;
 nk:=public.catalog_key_v1(n);if length(nk)<2 then return;end if;
 g:=public.valid_gtin_v1(g);
 k:=case when g is not null then 'gtin:'||g else 'name:'||nk end;
 perform pg_catalog.pg_advisory_xact_lock(812340024);
 if g is null then
  select min(a.identity_key) into oldkey from public.catalog_aliases a where a.search_key=nk and a.identity_key like 'gtin:%' having count(distinct a.identity_key)=1;
  k:=coalesce(oldkey,k);
 end if;
 insert into public.catalog_products(identity_key,name,gtin,source) values(k,trim(n),g,src) on conflict(identity_key) do nothing;
 insert into public.catalog_aliases(identity_key,name,search_key) values(k,trim(n),nk) on conflict do nothing;
 if g is not null then
  insert into public.catalog_aliases(identity_key,name,search_key) select k,a.name,a.search_key from public.catalog_aliases a where a.identity_key='name:'||nk on conflict do nothing;
  delete from public.catalog_products where identity_key='name:'||nk;
 end if;
end $fn$;
create or replace function public.suggest_products_v1(q text) returns table(name text,source text)
language sql stable security definer set search_path='' as $fn$
 with input as (select public.catalog_key_v1(q) k), candidates as (
 select a.identity_key,max(case when strpos(a.search_key,i.k)=1 then 2.0 when strpos(a.search_key,i.k)>0 then 1.5 else extensions.word_similarity(i.k,a.search_key) end) score
 from public.catalog_aliases a cross join input i
 where (select public.is_member()) and length(i.k) between 2 and 160
 and (a.search_key like '%'||i.k||'%' or (length(i.k)>=4 and a.search_key operator(extensions.%>) i.k))
 group by a.identity_key
 )
 select p.name,p.source from candidates c join public.catalog_products p using(identity_key)
 order by c.score desc,length(p.name),p.name limit 12
$fn$;
-- Learn from already stored verified offers and trusted imports; ignore raw queries.
do $fn$ declare r record;begin
 for r in select name,url,gtin from public.offers loop perform public.learn_catalog_v1(r.name,r.url,r.gtin);end loop;
 for r in select name,source,gtin from public.product_catalog where source<>'search' loop perform public.learn_catalog_v1(r.name,r.source,r.gtin);end loop;
end $fn$;
delete from public.product_catalog where source='search';
revoke all on function public.learn_catalog_v1(text,text,text) from public,anon,authenticated;
grant execute on function public.learn_catalog_v1(text,text,text) to service_role;
revoke all on function public.valid_gtin_v1(text),public.catalog_key_v1(text) from public,anon,authenticated;
grant execute on function public.valid_gtin_v1(text),public.catalog_key_v1(text) to service_role;
revoke execute on function public.is_member(),public.record_price() from public,anon;
revoke execute on function public.record_price() from authenticated;
commit;
notify pgrst,'reload schema';

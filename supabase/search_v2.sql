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
 insert into public.product_catalog(name,source) select o.name,o.url from public.offers o join public.search_offer_links l on l.offer_id=o.id where l.query=normalized on conflict(name) do update set source=excluded.source where product_catalog.source='search';
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
commit;
notify pgrst,'reload schema';

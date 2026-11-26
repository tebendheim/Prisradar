begin;
-- Independent lightweight catalogue: names and source URLs, not prices.
create table if not exists public.product_catalog (name text primary key, source text not null, created timestamptz not null default now());
create table if not exists public.active_searches (query text primary key, last_searched timestamptz not null default now(), last_attempt timestamptz, next_check timestamptz not null default now());
create table if not exists public.search_offer_links (query text references public.active_searches(query) on delete cascade, offer_id bigint references public.offers(id) on delete cascade, primary key(query,offer_id));
create index if not exists search_offer_links_offer on public.search_offer_links(offer_id);
create index if not exists active_searches_due on public.active_searches(next_check);
alter table public.product_catalog enable row level security;
alter table public.active_searches enable row level security;
alter table public.search_offer_links enable row level security;
revoke all on public.product_catalog,public.active_searches,public.search_offer_links from public,anon,authenticated;
grant all on public.product_catalog,public.active_searches,public.search_offer_links to service_role;
create or replace function public.suggest_products_v1(q text) returns table(name text,source text)
language sql stable security definer set search_path='' as $$
 select c.name,c.source from public.product_catalog c
 where (select public.is_member()) and length(trim(q)) between 2 and 160
 and strpos(lower(c.name),lower(trim(q)))>0
 order by (strpos(lower(c.name),lower(trim(q)))=1) desc,length(c.name),c.name limit 12
$$;
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
 insert into public.product_catalog(name,source) values(trim(q),'search') on conflict do nothing;
 insert into public.search_offer_links(query,offer_id)
 select normalized,o.id from public.offers o where o.gtin=normalized or lower(o.model)=normalized or strpos(lower(o.name),normalized)>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',normalized)
 on conflict do nothing;
 select count(*) into n from public.search_offer_links where query=normalized;
 return jsonb_build_object('query',normalized,'due',due<=now(),'offers',n);
end $$;
-- Only delete offers explicitly linked to expired queries, never shared or untracked legacy data.
create or replace function public.prune_searches_v1() returns integer
language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 perform pg_catalog.pg_advisory_xact_lock(812340023);
 delete from public.offers o where exists(select 1 from public.search_offer_links l join public.active_searches a on a.query=l.query where l.offer_id=o.id and a.last_searched<now()-interval '4 months')
 and not exists(select 1 from public.search_offer_links l join public.active_searches a on a.query=l.query where l.offer_id=o.id and a.last_searched>=now()-interval '4 months')
 and not exists(select 1 from public.watches w where o.gtin=w.query or lower(o.model)=lower(w.query) or strpos(lower(o.name),lower(w.query))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',w.query));
 get diagnostics n=row_count;
 delete from public.active_searches where last_searched<now()-interval '4 months' and not exists(select 1 from public.watches w where lower(trim(w.query))=active_searches.query);
 return n;
end $$;
revoke all on function public.suggest_products_v1(text),public.touch_search_v1(text),public.prune_searches_v1() from public,anon,authenticated;
grant execute on function public.suggest_products_v1(text),public.touch_search_v1(text) to authenticated;
grant execute on function public.prune_searches_v1() to service_role;
commit;
notify pgrst,'reload schema';

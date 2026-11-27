begin;
create table if not exists public.catalog_store_products (
 host text not null references public.managed_stores(host) on delete cascade,
 url text not null, name text not null, gtin text,
 search_key text generated always as (public.catalog_key_v1(name)) stored,
 last_seen timestamptz not null default now(), primary key(host,url,name)
);
create index if not exists catalog_store_products_search on public.catalog_store_products using gin(search_key extensions.gin_trgm_ops);
create index if not exists catalog_store_products_gtin on public.catalog_store_products(gtin);
create table if not exists public.search_store_checks (
 query text not null references public.active_searches(query) on delete cascade,
 host text not null references public.managed_stores(host) on delete cascade,
 checked timestamptz, next_check timestamptz not null default now(),
 status text not null default 'pending', offers integer not null default 0, detail text,
 primary key(query,host)
);
create index if not exists search_store_checks_due on public.search_store_checks(query,next_check);
alter table public.catalog_store_products enable row level security;
alter table public.search_store_checks enable row level security;
revoke all on public.catalog_store_products,public.search_store_checks from public,anon,authenticated;
grant all on public.catalog_store_products,public.search_store_checks to service_role;
create or replace function public.index_store_products_v1(h text,items jsonb) returns integer language plpgsql security definer set search_path='' as $fn$
declare n integer;
begin
 if jsonb_typeof(items) is distinct from 'array' or jsonb_array_length(items)>100 then raise exception 'Invalid batch';end if;
 if pg_database_size(current_database())>=350000000 then return 0;end if;
 insert into public.catalog_store_products(host,url,name,gtin)
 select distinct on(r->>'src',r->>'n') h,r->>'src',r->>'n',public.valid_gtin_v1(r->>'g')
 from jsonb_array_elements(items) r
 where length(r->>'n') between 2 and 500 and length(r->>'src')<=1500 and strpos(r->>'src','https://'||h||'/')=1
 on conflict(host,url,name) do update set last_seen=now(),gtin=coalesce(excluded.gtin,catalog_store_products.gtin);
 get diagnostics n=row_count;return n;
end $fn$;
revoke all on function public.index_store_products_v1(text,jsonb) from public,anon,authenticated;
grant execute on function public.index_store_products_v1(text,jsonb) to service_role;
create or replace function public.store_search_status_v1(q text) returns jsonb language sql stable security definer set search_path='' as $fn$
select case when public.is_member() then jsonb_build_object('stores',coalesce((select jsonb_agg(jsonb_build_object('host',s.host,'status',s.status,'offers',s.offers,'detail',s.detail,'checked',s.checked) order by s.offers desc,s.host) from public.search_store_checks s where s.query=lower(regexp_replace(trim(q),'[[:space:]]+',' ','g'))),'[]'::jsonb)) else null end
$fn$;
create or replace function public.refresh_search_v1(q text) returns void language plpgsql security definer set search_path='' as $fn$
declare k text;
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501';end if;
 k:=lower(regexp_replace(trim(q),'[[:space:]]+',' ','g'));
 perform public.touch_search_v1(q);
 update public.active_searches set next_check=now() where query=k;
 update public.search_store_checks set next_check=now() where query=k;
end $fn$;
revoke all on function public.store_search_status_v1(text),public.refresh_search_v1(text) from public,anon;
grant execute on function public.store_search_status_v1(text),public.refresh_search_v1(text) to authenticated;
create or replace function public.schema_health_v1() returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare missing text[]; v integer; t text;
begin
 if coalesce(auth.role(),'') <> 'service_role' and not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select coalesce(max(version),0) into v from public.schema_migrations;
 select coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['members','offers','coupons','price_history','watches','crawl_dispatches','crawl_pages','crawl_reports','store_candidates','managed_stores','store_assortment','active_searches','search_offer_links','catalog_products','catalog_aliases','catalog_store_products','search_store_checks']) x where to_regclass('public.'||x) is null;
 select missing||coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['search_offers_v1(text,integer)','touch_search_v1(text)','prune_searches_v1()','learn_catalog_v1(text,text,text)','learn_catalog_batch_v1(jsonb)','catalog_capacity_v1()','record_assortment_v1(text,jsonb)','configure_store_v1(text,text,boolean,text,text)','browse_models_v1(text)','suggest_products_v1(text)','category_offers_v1(text)','search_progress_v1(text)','admin_metrics_v1()','index_store_products_v1(text,jsonb)','store_search_status_v1(text)','refresh_search_v1(text)','crawl_quota_status_v1()','reserve_crawl_v2(boolean)']) x where to_regprocedure('public.'||x) is null;
 foreach t in array array['adapter','vat_status','currency_hint','feed_path','delivery_evidence','delivery_checked','search_path','paused_until','enabled'] loop
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='managed_stores' and column_name=t) then missing:=array_append(missing,'managed_stores.'||t);end if;
 end loop;
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112704 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;


insert into public.schema_migrations(version) values(2026112704) on conflict do nothing;
commit;
notify pgrst,'reload schema';

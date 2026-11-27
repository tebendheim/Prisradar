begin;
alter table public.offers add column if not exists price_kind text not null default 'exact' check(price_kind in ('exact','from'));
alter table public.price_history add column if not exists price_kind text not null default 'exact' check(price_kind in ('exact','from'));
-- Preserve legacy row IDs and histories; do not delete conflicting old rows.
update public.offers o set price_kind='from', name=regexp_replace(o.name,' [(]fra-pris[)]$','') where o.name like '% (fra-pris)' and not exists(select 1 from public.offers x where x.url=o.url and x.name=regexp_replace(o.name,' [(]fra-pris[)]$',''));
update public.offers set price_kind='from' where name like '% (fra-pris)' or availability='AggregatePrice';
create or replace function public.record_price() returns trigger language plpgsql set search_path='' as $$ begin if TG_OP='INSERT' then insert into public.price_history(offer_id,price,price_kind) values(new.id,new.price,new.price_kind); elsif old.price is distinct from new.price or old.price_kind is distinct from new.price_kind then insert into public.price_history(offer_id,price,price_kind) values(new.id,new.price,new.price_kind); end if; return new; end $$;
create or replace function public.search_offers_v2(q text,max_results integer default 100)
returns table(id bigint,name text,host text,url text,gtin text,model text,price numeric,shipping numeric,total_price numeric,availability text,checked timestamptz,price_kind text)
language sql stable security invoker set search_path='' as $$
select o.id,o.name,o.host,o.url,o.gtin,o.model,o.price,o.shipping,o.price+o.shipping,o.availability,o.checked,o.price_kind
from public.offers o where (select public.is_member()) and length(trim(q)) between 1 and 200
and (case when public.valid_gtin_v1(trim(q)) is not null then public.valid_gtin_v1(o.gtin)=public.valid_gtin_v1(trim(q)) else lower(o.model)=lower(trim(q)) or strpos(lower(o.name),lower(trim(q)))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',q) end)
order by case when o.availability in ('OutOfStock','SoldOut','Discontinued') then 1 else 0 end,case when o.price_kind='from' then 1 else 0 end,o.price+o.shipping asc nulls last,o.price,o.id limit least(100,greatest(1,coalesce(max_results,100)))
$$;
revoke all on function public.search_offers_v2(text,integer) from public,anon;
grant execute on function public.search_offers_v2(text,integer) to authenticated;
create or replace function public.store_quality_v1() returns jsonb language sql stable security definer set search_path='' as $$
select case when exists(select 1 from public.members where user_id=auth.uid() and role='admin') then coalesce(jsonb_agg(to_jsonb(s) order by s.host,s.detail),'[]'::jsonb) else null end from (select host,detail,count(*) runs,sum(offers) offers,count(*) filter(where offers>0) successful_runs from public.crawl_reports where created>now()-interval '7 days' group by host,detail) s
$$;
revoke all on function public.store_quality_v1() from public,anon;
grant execute on function public.store_quality_v1() to authenticated;
create or replace function public.schema_health_v1() returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare missing text[]; v integer; t text;
begin
 if coalesce(auth.role(),'') <> 'service_role' and not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select coalesce(max(version),0) into v from public.schema_migrations;
 select coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['members','offers','coupons','price_history','watches','crawl_dispatches','crawl_pages','crawl_reports','store_candidates','managed_stores','store_assortment','active_searches','search_offer_links','catalog_products','catalog_aliases','catalog_store_products','search_store_checks']) x where to_regclass('public.'||x) is null;
 select missing||coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['search_offers_v1(text,integer)','touch_search_v1(text)','prune_searches_v1()','learn_catalog_v1(text,text,text)','learn_catalog_batch_v1(jsonb)','catalog_capacity_v1()','record_assortment_v1(text,jsonb)','configure_store_v1(text,text,boolean,text,text)','browse_models_v1(text)','suggest_products_v1(text)','category_offers_v1(text)','search_progress_v1(text)','admin_metrics_v1()','search_offers_v2(text,integer)','store_quality_v1()','index_store_products_v1(text,jsonb)','store_search_status_v1(text)','refresh_search_v1(text)','crawl_quota_status_v1()','reserve_crawl_v2(boolean)']) x where to_regprocedure('public.'||x) is null;
 foreach t in array array['adapter','vat_status','currency_hint','feed_path','delivery_evidence','delivery_checked','search_path','paused_until','enabled'] loop
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='managed_stores' and column_name=t) then missing:=array_append(missing,'managed_stores.'||t);end if;
 end loop;
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='offers' and column_name='price_kind') then missing:=array_append(missing,'offers.price_kind');end if;
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112705 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;



insert into public.schema_migrations(version) values(2026112705) on conflict do nothing;
commit;
notify pgrst,'reload schema';

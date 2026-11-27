begin;
alter table public.offers add column if not exists brand text;
alter table public.offers add column if not exists mpn text;
alter table public.offers add column if not exists review_required boolean not null default false;
alter table public.offers add column if not exists pending_price numeric;
alter table public.offers add column if not exists pending_checked timestamptz;
create or replace function public.guard_price_jump() returns trigger language plpgsql set search_path='' as $$
begin
 if old.price_kind=new.price_kind and old.price>0 and (new.price<old.price*0.4 or new.price>old.price*1.6) then
  new.pending_price:=new.price; new.pending_checked:=new.checked; new.review_required:=true;
  new.price:=old.price;new.checked:=old.checked;new.shipping:=old.shipping;new.availability:=old.availability;
 elsif new.price is distinct from old.price or new.checked>old.checked then
  new.review_required:=false;new.pending_price:=null;new.pending_checked:=null;
 end if;
 return new;
end $$;
drop trigger if exists guard_price_jump on public.offers;
create trigger guard_price_jump before update on public.offers for each row execute function public.guard_price_jump();
create or replace function public.search_offers_v3(q text,max_results integer default 100)
returns table(id bigint,name text,host text,url text,gtin text,model text,price numeric,shipping numeric,total_price numeric,availability text,checked timestamptz,price_kind text,brand text,mpn text,review_required boolean,stale boolean)
language sql stable security invoker set search_path='' as $$
with seed as (
 select o.id,public.valid_gtin_v1(o.gtin) g from public.offers o
 where (select public.is_member()) and length(trim(q)) between 1 and 200
 and (case when public.valid_gtin_v1(trim(q)) is not null then public.valid_gtin_v1(o.gtin)=public.valid_gtin_v1(trim(q)) else lower(o.model)=lower(trim(q)) or strpos(lower(o.name),lower(trim(q)))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',q) end)
)
select o.id,o.name,o.host,o.url,o.gtin,o.model,o.price,o.shipping,o.price+o.shipping,o.availability,o.checked,o.price_kind,o.brand,o.mpn,o.review_required,o.checked<now()-interval '7 days'
from public.offers o where (select public.is_member()) and (exists(select 1 from seed s where s.id=o.id) or public.valid_gtin_v1(o.gtin) in (select g from seed where g is not null))
order by o.review_required, o.checked<now()-interval '7 days',case when o.availability in ('OutOfStock','SoldOut','Discontinued') then 1 else 0 end,case when o.price_kind='from' then 1 else 0 end,o.price+o.shipping asc nulls last,o.price,o.id limit least(100,greatest(1,coalesce(max_results,100)))
$$;
revoke all on function public.search_offers_v3(text,integer) from public,anon;
grant execute on function public.search_offers_v3(text,integer) to authenticated;
create or replace function public.schema_health_v1() returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare missing text[]; v integer; t text;
begin
 if coalesce(auth.role(),'') <> 'service_role' and not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select coalesce(max(version),0) into v from public.schema_migrations;
 select coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['members','offers','coupons','price_history','watches','crawl_dispatches','crawl_pages','crawl_reports','store_candidates','managed_stores','store_assortment','active_searches','search_offer_links','catalog_products','catalog_aliases','catalog_store_products','search_store_checks']) x where to_regclass('public.'||x) is null;
 select missing||coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['search_offers_v1(text,integer)','touch_search_v1(text)','prune_searches_v1()','learn_catalog_v1(text,text,text)','learn_catalog_batch_v1(jsonb)','catalog_capacity_v1()','record_assortment_v1(text,jsonb)','configure_store_v1(text,text,boolean,text,text)','browse_models_v1(text)','suggest_products_v1(text)','category_offers_v1(text)','search_progress_v1(text)','admin_metrics_v1()','search_offers_v2(text,integer)','search_offers_v3(text,integer)','store_quality_v1()','index_store_products_v1(text,jsonb)','store_search_status_v1(text)','refresh_search_v1(text)','crawl_quota_status_v1()','reserve_crawl_v2(boolean)']) x where to_regprocedure('public.'||x) is null;
 foreach t in array array['adapter','vat_status','currency_hint','feed_path','delivery_evidence','delivery_checked','search_path','paused_until','enabled'] loop
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='managed_stores' and column_name=t) then missing:=array_append(missing,'managed_stores.'||t);end if;
 end loop;
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='offers' and column_name='price_kind') then missing:=array_append(missing,'offers.price_kind');end if;
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112706 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;




insert into public.schema_migrations(version) values(2026112706) on conflict do nothing;
commit;
notify pgrst,'reload schema';

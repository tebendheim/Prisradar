begin;
create or replace function public.guard_price_jump() returns trigger language plpgsql set search_path='' as $$
begin
 if old.price_kind=new.price_kind and old.pending_price is not null and abs(new.price-old.pending_price)<0.01 and new.checked>=old.pending_checked+interval '1 hour' then
  new.review_required:=false;new.pending_price:=null;new.pending_checked:=null;return new;
 end if;
 if old.price_kind=new.price_kind and old.price>0 and (new.price<old.price*0.4 or new.price>old.price*1.6) then
  new.pending_price:=new.price; new.pending_checked:=case when old.pending_price is not null and abs(new.price-old.pending_price)<0.01 then old.pending_checked else new.checked end; new.review_required:=true;
  new.price:=old.price;new.checked:=old.checked;new.shipping:=old.shipping;new.availability:=old.availability;
 elsif new.price is distinct from old.price or new.checked>old.checked then
  new.review_required:=false;new.pending_price:=null;new.pending_checked:=null;
 end if;
 return new;
end $$;

alter table public.offers add column if not exists member_prices jsonb not null default '[]'::jsonb;
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
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112707 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;





insert into public.schema_migrations(version) values(2026112707) on conflict do nothing;
commit;
notify pgrst,'reload schema';

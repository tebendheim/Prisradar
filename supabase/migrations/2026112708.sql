-- actions-budget: manual_runs_per_30d=10 minutes_per_run=8
-- Manual crawl limits sized for a private repo (2000 Actions min/month):
-- scheduled jobs up to 1674 min + 10 manual runs x 8 min = 1754 min.
-- Limits: 3 per 24h normal, 5 per 24h with extra, max 10 per 30 days, 1 minute between runs.
begin;

create or replace function public.crawl_quota_status_v1() returns jsonb
language plpgsql security definer set search_path='' as $$
declare daily int; monthly int; last_start timestamptz; day_next timestamptz; month_next timestamptz;
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select count(*) filter(where requested_at>now()-interval '24 hours'),count(*),max(requested_at) into daily,monthly,last_start from public.crawl_dispatches where requested_at>now()-interval '30 days';
 select requested_at+interval '24 hours' into day_next from public.crawl_dispatches where requested_at>now()-interval '24 hours' order by requested_at desc offset 4 limit 1;
 select requested_at+interval '30 days' into month_next from public.crawl_dispatches where requested_at>now()-interval '30 days' order by requested_at desc offset 9 limit 1;
 return jsonb_build_object('used_day',daily,'used_30d',monthly,'normal_remaining',greatest(0,least(3-daily,10-monthly)),'extra_remaining',greatest(0,least(5-greatest(daily,3),10-greatest(monthly,monthly+greatest(0,3-daily)))),'total_remaining',greatest(0,least(5-daily,10-monthly)),'next_start',greatest(now(),last_start+interval '1 minute',day_next,month_next),'estimated_max_minutes_30d',monthly*8,'manual_cap',10);
end $$;

create or replace function public.reserve_crawl_v2(extra boolean default false) returns boolean
language plpgsql security definer set search_path='' as $$
declare daily int; monthly int;
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 perform pg_catalog.pg_advisory_xact_lock(812340021);
 select count(*) filter(where requested_at>now()-interval '24 hours'),count(*) into daily,monthly from public.crawl_dispatches where requested_at>now()-interval '30 days';
 if daily >= (case when extra is true then 5 else 3 end) or monthly>=10 or exists(select 1 from public.crawl_dispatches where requested_at>now()-interval '1 minute') then return false;end if;
 insert into public.crawl_dispatches(user_id) values(auth.uid());return true;
end $$;

revoke all on function public.crawl_quota_status_v1(),public.reserve_crawl_v2(boolean) from public,anon;
grant execute on function public.crawl_quota_status_v1(),public.reserve_crawl_v2(boolean) to authenticated;

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
 foreach t in array array['price_kind','brand','mpn','review_required','pending_price','pending_checked','member_prices'] loop
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='offers' and column_name=t) then missing:=array_append(missing,'offers.'||t);end if;
 end loop;
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112708 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;

insert into public.schema_migrations(version) values(2026112708) on conflict do nothing;
commit;
notify pgrst,'reload schema';

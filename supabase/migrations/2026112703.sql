begin;
alter table public.managed_stores add column if not exists adapter text not null default 'generic';
alter table public.managed_stores add column if not exists vat_status text not null default 'unknown';
alter table public.managed_stores add column if not exists currency_hint text not null default 'unknown';
alter table public.store_candidates add column if not exists probe_checked timestamptz;
alter table public.store_candidates add column if not exists probe_next timestamptz not null default now();
alter table public.store_candidates add column if not exists probe_result text;
create index if not exists store_candidates_probe_due on public.store_candidates(probe_next,probe_checked);
create or replace function public.configure_store_v1(h text,p text,active boolean,feed text,evidence text) returns void language plpgsql security definer set search_path='' as $fn$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501';end if;
 h:=lower(trim(h));p:=nullif(trim(p),'');feed:=nullif(trim(feed),'');evidence:=nullif(trim(evidence),'');
 if h is null or length(h)>150 or h !~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?([.][a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' or h !~ '[.][a-z]{2,24}$' then raise exception 'Invalid store hostname';end if;
 if p is not null and (length(p)>300 or left(p,1)<>'/' or left(p,2)='//' or strpos(p,'{q}')=0 or strpos(p,chr(92))>0 or p ~ '[[:cntrl:]]') then raise exception 'Invalid search path';end if;
 if feed is not null and (length(feed)>1000 or left(feed,1)<>'/' or left(feed,2)='//' or strpos(feed,chr(92))>0 or feed ~ '[[:cntrl:]]') then raise exception 'Invalid feed path';end if;
 if evidence is not null and length(evidence)>1000 then raise exception 'Evidence too long';end if;
 if not exists(select 1 from public.managed_stores where host=h) and (select count(*) from public.managed_stores)>=500 then raise exception 'Store limit';end if;
 insert into public.managed_stores(host,search_path,enabled,feed_path,delivery_evidence,delivery_checked) values(h,p,coalesce(active,false),feed,evidence,case when evidence is not null then now() end)
 on conflict(host) do update set search_path=excluded.search_path,enabled=excluded.enabled,feed_path=excluded.feed_path,delivery_evidence=coalesce(excluded.delivery_evidence,managed_stores.delivery_evidence),delivery_checked=coalesce(excluded.delivery_checked,managed_stores.delivery_checked);
end $fn$;

create or replace function public.schema_health_v1() returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare missing text[]; v integer; t text;
begin
 if coalesce(auth.role(),'') <> 'service_role' and not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select coalesce(max(version),0) into v from public.schema_migrations;
 select coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['members','offers','coupons','price_history','watches','crawl_dispatches','crawl_pages','crawl_reports','store_candidates','managed_stores','store_assortment','active_searches','search_offer_links','catalog_products','catalog_aliases']) x where to_regclass('public.'||x) is null;
 select missing||coalesce(array_agg(x),array[]::text[]) into missing from unnest(array['search_offers_v1(text,integer)','touch_search_v1(text)','prune_searches_v1()','learn_catalog_v1(text,text,text)','learn_catalog_batch_v1(jsonb)','catalog_capacity_v1()','record_assortment_v1(text,jsonb)','configure_store_v1(text,text,boolean,text,text)','browse_models_v1(text)','suggest_products_v1(text)','category_offers_v1(text)','search_progress_v1(text)','admin_metrics_v1()','crawl_quota_status_v1()','reserve_crawl_v2(boolean)']) x where to_regprocedure('public.'||x) is null;
 foreach t in array array['adapter','vat_status','currency_hint','feed_path','delivery_evidence','delivery_checked','search_path','paused_until','enabled'] loop
 if not exists(select 1 from information_schema.columns where table_schema='public' and table_name='managed_stores' and column_name=t) then missing:=array_append(missing,'managed_stores.'||t);end if;
 end loop;
 return jsonb_build_object('version',v,'missing',missing,'ready',v>=2026112703 and cardinality(missing)=0);
end $fn$;
revoke all on function public.schema_health_v1() from public,anon,authenticated;
grant execute on function public.schema_health_v1() to authenticated,service_role;

insert into public.schema_migrations(version) values(2026112703) on conflict do nothing;
commit;
notify pgrst,'reload schema';

begin;
create or replace function public.admin_metrics_v1() returns jsonb language plpgsql stable security definer set search_path='' as $fn$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501';end if;
 return jsonb_build_object('products',(select count(*) from public.catalog_products),'offers',(select count(*) from public.offers),'pages',(select count(*) from public.crawl_pages),'stores',(select count(*) from public.managed_stores where enabled),'candidates',(select count(*) from public.store_candidates c where not exists(select 1 from public.managed_stores s where s.host=c.host)),'coupons',(select count(*) from public.coupons));
end $fn$;
revoke all on function public.admin_metrics_v1() from public,anon;
grant execute on function public.admin_metrics_v1() to authenticated;
insert into public.schema_migrations(version) values(2026112702) on conflict do nothing;
commit;
notify pgrst,'reload schema';

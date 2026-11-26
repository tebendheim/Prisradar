begin;
create or replace function public.catalog_capacity_v1() returns jsonb language sql stable security definer set search_path='' as $fn$
select jsonb_build_object('bytes',pg_database_size(current_database()),'allowed',pg_database_size(current_database())<350000000)
$fn$;
revoke all on function public.catalog_capacity_v1() from public,anon,authenticated;
grant execute on function public.catalog_capacity_v1() to service_role;
commit;
notify pgrst,'reload schema';

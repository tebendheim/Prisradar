begin;
create or replace function public.learn_catalog_batch_v1(items jsonb) returns integer language plpgsql security definer set search_path='' as $fn$
declare r jsonb; n integer:=0;
begin
 if jsonb_typeof(items) is distinct from 'array' or jsonb_array_length(items)>100 then raise exception 'Invalid batch';end if;
 if pg_database_size(current_database())>=350000000 then return 0;end if;
 for r in select value from jsonb_array_elements(items) loop
  perform public.learn_catalog_v1(r->>'n',r->>'src',r->>'g');n:=n+1;
 end loop;
 return n;
end $fn$;
revoke all on function public.learn_catalog_batch_v1(jsonb) from public,anon,authenticated;
grant execute on function public.learn_catalog_batch_v1(jsonb) to service_role;
commit;
notify pgrst,'reload schema';

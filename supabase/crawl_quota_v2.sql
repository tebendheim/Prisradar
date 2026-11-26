begin;
create or replace function public.reserve_crawl_v1() returns boolean
language plpgsql security definer set search_path='' as $$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 perform pg_catalog.pg_advisory_xact_lock(812340021);
 if exists(select 1 from public.crawl_dispatches where requested_at > now()-interval '1 minute') or
 (select count(*) from public.crawl_dispatches where requested_at > now()-interval '24 hours')>=10 or (select count(*) from public.crawl_dispatches where requested_at > now()-interval '30 days')>=120 then return false; end if;
 insert into public.crawl_dispatches(user_id) values(auth.uid());
 return true;
end $$;
revoke all on function public.reserve_crawl_v1() from public,anon;
grant execute on function public.reserve_crawl_v1() to authenticated;
commit;

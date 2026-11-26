begin;
create or replace function public.crawl_quota_status_v1() returns jsonb
language plpgsql security definer set search_path='' as $$
declare daily int; monthly int; last_start timestamptz; day_next timestamptz; month_next timestamptz;
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 select count(*) filter(where requested_at>now()-interval '24 hours'),count(*),max(requested_at) into daily,monthly,last_start from public.crawl_dispatches where requested_at>now()-interval '30 days';
 select requested_at+interval '24 hours' into day_next from public.crawl_dispatches where requested_at>now()-interval '24 hours' order by requested_at desc offset 19 limit 1;
 select requested_at+interval '30 days' into month_next from public.crawl_dispatches where requested_at>now()-interval '30 days' order by requested_at desc offset 119 limit 1;
 return jsonb_build_object('used_day',daily,'used_30d',monthly,'normal_remaining',greatest(0,least(10-daily,120-monthly)),'extra_remaining',greatest(0,least(20-greatest(daily,10),120-greatest(monthly,monthly+greatest(0,10-daily)))),'total_remaining',greatest(0,least(20-daily,120-monthly)),'next_start',greatest(now(),last_start+interval '1 minute',day_next,month_next),'estimated_max_minutes_30d',monthly*8,'manual_cap',120);
end $$;
create or replace function public.reserve_crawl_v2(extra boolean default false) returns boolean
language plpgsql security definer set search_path='' as $$
declare daily int; monthly int;
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 perform pg_catalog.pg_advisory_xact_lock(812340021);
 select count(*) filter(where requested_at>now()-interval '24 hours'),count(*) into daily,monthly from public.crawl_dispatches where requested_at>now()-interval '30 days';
 if daily>=case when extra is true then 20 else 10 end or monthly>=120 or exists(select 1 from public.crawl_dispatches where requested_at>now()-interval '1 minute') then return false;end if;
 insert into public.crawl_dispatches(user_id) values(auth.uid());return true;
end $$;
create or replace function public.reserve_crawl_v1() returns boolean language sql security invoker set search_path='' as $$ select public.reserve_crawl_v2(false) $$;
revoke all on function public.crawl_quota_status_v1(),public.reserve_crawl_v2(boolean),public.reserve_crawl_v1() from public,anon;
grant execute on function public.crawl_quota_status_v1(),public.reserve_crawl_v2(boolean),public.reserve_crawl_v1() to authenticated;
commit;

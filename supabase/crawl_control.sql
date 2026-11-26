begin;
create table if not exists public.crawl_dispatches (id bigint generated always as identity primary key, requested_at timestamptz not null default now(), user_id uuid not null references auth.users(id));
alter table public.crawl_dispatches enable row level security;
revoke all on public.crawl_dispatches from public,anon,authenticated;
create or replace function public.reserve_crawl_v1() returns boolean
language plpgsql security definer set search_path='' as $$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501'; end if;
 perform pg_catalog.pg_advisory_xact_lock(812340021);
 if exists(select 1 from public.crawl_dispatches where requested_at > now()-interval '15 minutes') or
 (select count(*) from public.crawl_dispatches where requested_at > now()-interval '24 hours')>=3 then return false; end if;
 insert into public.crawl_dispatches(user_id) values(auth.uid());
 return true;
end $$;
revoke all on function public.reserve_crawl_v1() from public,anon;
grant execute on function public.reserve_crawl_v1() to authenticated;
commit;

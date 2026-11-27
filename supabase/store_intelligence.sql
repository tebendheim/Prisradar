begin;
alter table public.managed_stores add column if not exists feed_path text;
alter table public.managed_stores add column if not exists delivery_evidence text;
alter table public.managed_stores add column if not exists delivery_checked timestamptz;
create table if not exists public.store_assortment(host text not null references public.managed_stores(host) on delete cascade, category text not null, samples bigint not null default 0, updated timestamptz not null default now(), primary key(host,category));
alter table public.store_assortment enable row level security;
revoke all on public.store_assortment from public,anon,authenticated;
grant all on public.store_assortment to service_role;
create or replace function public.record_assortment_v1(h text,counts jsonb) returns void language plpgsql security definer set search_path='' as $fn$
begin
 insert into public.store_assortment(host,category,samples) select h,key,least(1000,greatest(0,value::bigint)) from jsonb_each_text(counts) where key in ('electronics','sport','home','fashion','beauty','building','furniture') on conflict(host,category) do update set samples=least(1000000,store_assortment.samples+excluded.samples),updated=now();
end $fn$;
revoke all on function public.record_assortment_v1(text,jsonb) from public,anon,authenticated;
grant execute on function public.record_assortment_v1(text,jsonb) to service_role;
create or replace function public.configure_store_v1(h text,p text,active boolean,feed text,evidence text) returns void language plpgsql security definer set search_path='' as $fn$
begin
 if not exists(select 1 from public.members where user_id=auth.uid() and role='admin') then raise exception 'Admin required' using errcode='42501';end if;
 h:=lower(trim(h));p:=nullif(trim(p),'');feed:=nullif(trim(feed),'');evidence:=nullif(trim(evidence),'');
 if h is null or length(h)>150 or h !~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?([.][a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' or h !~ '[.][a-z]{2,24}$' then raise exception 'Invalid store hostname';end if;
 if p is not null and (length(p)>300 or left(p,1)<>'/' or left(p,2)='//' or strpos(p,'{q}')=0 or strpos(p,chr(92))>0 or p ~ '[[:cntrl:]]') then raise exception 'Invalid search path';end if;
 if feed is not null and (length(feed)>1000 or left(feed,1)<>'/' or left(feed,2)='//' or strpos(feed,chr(92))>0 or feed ~ '[[:cntrl:]]') then raise exception 'Invalid feed path';end if;
 if evidence is not null and length(evidence)>1000 then raise exception 'Evidence too long';end if;
 if not exists(select 1 from public.managed_stores where host=h) and (select count(*) from public.managed_stores)>=500 then raise exception 'Store limit';end if;
 if coalesce(active,false) and not exists(select 1 from public.managed_stores where host=h and enabled) and evidence is null then raise exception 'Confirm Norway delivery before enabling';end if;
 insert into public.managed_stores(host,search_path,enabled,feed_path,delivery_evidence,delivery_checked) values(h,p,coalesce(active,false),feed,evidence,case when evidence is not null then now() end)
 on conflict(host) do update set search_path=excluded.search_path,enabled=excluded.enabled,feed_path=excluded.feed_path,delivery_evidence=coalesce(excluded.delivery_evidence,managed_stores.delivery_evidence),delivery_checked=coalesce(excluded.delivery_checked,managed_stores.delivery_checked);
end $fn$;
revoke all on function public.configure_store_v1(text,text,boolean,text,text) from public,anon;
grant execute on function public.configure_store_v1(text,text,boolean,text,text) to authenticated;
commit;
notify pgrst,'reload schema';

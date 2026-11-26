-- Apply AFTER schema.sql. Versioned API, invoker security preserves RLS.
begin;
create or replace function public.search_offers_v1(q text, max_results integer default 30)
returns table(id bigint,name text,host text,url text,gtin text,model text,price numeric,shipping numeric,total_price numeric,availability text,checked timestamptz)
language sql stable security invoker set search_path='' as $$
select o.id,o.name,o.host,o.url,o.gtin,o.model,o.price,o.shipping,o.price+o.shipping,o.availability,o.checked
from public.offers o
where (select public.is_member()) and length(trim(q)) between 1 and 200
and (o.gtin=trim(q) or lower(o.model)=lower(trim(q)) or strpos(lower(o.name),lower(trim(q)))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',q))
order by (o.gtin=trim(q)) desc nulls last, (lower(o.model)=lower(trim(q))) desc nulls last,
case when o.availability in ('OutOfStock','SoldOut','Discontinued') then 1 else 0 end,
o.price+o.shipping asc nulls last,o.price asc,o.id
limit least(100,greatest(1,coalesce(max_results,30)))
$$;
create or replace function public.offer_history_v1(offer bigint)
returns table(price numeric,checked timestamptz)
language sql stable security invoker set search_path='' as $$
select h.price,h.checked from public.price_history h where (select public.is_member()) and h.offer_id=offer order by h.checked desc limit 365
$$;
create or replace function public.store_coupons_v1(store_host text)
returns table(code text,source text,context text,status text,checked timestamptz,expires timestamptz)
language sql stable security invoker set search_path='' as $$
select c.code,c.source,c.context,c.status,c.checked,c.expires from public.coupons c
where (select public.is_member()) and c.host=store_host and c.status <> 'rejected' and (c.expires is null or c.expires>now())
order by case c.status when 'tested' then 0 when 'documented' then 1 else 2 end,c.checked desc limit 100
$$;
revoke all on function public.search_offers_v1(text,integer),public.offer_history_v1(bigint),public.store_coupons_v1(text) from public,anon;
grant execute on function public.search_offers_v1(text,integer),public.offer_history_v1(bigint),public.store_coupons_v1(text) to authenticated;
commit;

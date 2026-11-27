begin;
create or replace function public.display_model_v1(n text) returns text language sql immutable set search_path='' as $fn$
select case when lower(n) ~ '^(apple )?airpods pro 3([ .]|$)' and lower(n) !~ '(etui alene|case only|deksel|reservedel|replacement|ear tips|ørepropper alene|tilbehør)' then 'Apple AirPods Pro 3'
when lower(n) ~ '^(apple )?airpods pro 2([ .]|$)' and lower(n) !~ '(deksel|reservedel|replacement|case only|etui alene)' then 'Apple AirPods Pro 2'
else trim(n) end
$fn$;
create or replace function public.browse_models_v1(q text) returns table(name text,source text) language sql stable security definer set search_path='' as $fn$
with input as (select public.catalog_key_v1(q) k), hits as (
select p.identity_key,public.display_model_v1(p.name) label,p.source,
max(case when a.search_key=i.k then 4 when strpos(a.search_key,i.k)>0 then 3 when i.k in ('hodetelefoner','hodetelefon','headphones') and a.search_key ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)' then 2 else extensions.word_similarity(i.k,a.search_key) end) score
from public.catalog_products p join public.catalog_aliases a using(identity_key) cross join input i
where (select public.is_member()) and length(i.k) between 2 and 160 and (strpos(a.search_key,i.k)>0 or (i.k in ('hodetelefoner','hodetelefon','headphones') and a.search_key ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)') or (length(i.k)>=4 and a.search_key operator(extensions.%>) i.k))
group by p.identity_key,p.name,p.source
), grouped as (select distinct on(label) label,source,score from hits order by label,score desc,source)
select label,source from grouped order by score desc,length(label),label limit 100
$fn$;
create or replace function public.suggest_products_v1(q text) returns table(name text,source text) language sql stable security definer set search_path='' as $fn$
select * from public.browse_models_v1(q) limit 12
$fn$;
revoke all on function public.browse_models_v1(text),public.display_model_v1(text) from public,anon;
grant execute on function public.browse_models_v1(text),public.display_model_v1(text) to authenticated,service_role;
create or replace function public.category_offers_v1(q text) returns table(id bigint,name text,host text,url text,gtin text,model text,price numeric,shipping numeric,total_price numeric,availability text,checked timestamptz)
language sql stable security invoker set search_path='' as $fn$
select o.id,o.name,o.host,o.url,o.gtin,o.model,o.price,o.shipping,o.price+o.shipping,o.availability,o.checked
from public.offers o where (select public.is_member()) and length(trim(q)) between 2 and 160
and (strpos(lower(o.name),lower(trim(q)))>0 or to_tsvector('simple',o.name) @@ plainto_tsquery('simple',q)
or (lower(trim(q)) in ('hodetelefoner','hodetelefon','headphones') and lower(o.name) ~ '(airpods|headphones|hodetelefon|headset|earbuds|ørepropper)'))
order by o.checked desc,o.price limit 200
$fn$;
revoke all on function public.category_offers_v1(text) from public,anon;
grant execute on function public.category_offers_v1(text) to authenticated;
commit;
notify pgrst,'reload schema';

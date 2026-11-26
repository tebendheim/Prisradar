-- Read-only audit; no actual user rows, passwords, tokens or query text.
select jsonb_build_object(
 'tables',(select jsonb_agg(jsonb_build_object('name',c.relname,'rls',c.relrowsecurity,'bytes',pg_total_relation_size(c.oid),'estimated_rows',c.reltuples)) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('r','p')),
 'columns',(select jsonb_agg(to_jsonb(c)) from information_schema.columns c where table_schema='public'),
 'constraints',(select jsonb_agg(jsonb_build_object('table',c.conrelid::regclass::text,'name',c.conname,'definition',pg_get_constraintdef(c.oid))) from pg_constraint c join pg_namespace n on n.oid=c.connamespace where n.nspname='public'),
 'indexes',(select jsonb_agg(to_jsonb(i)) from pg_indexes i where schemaname='public'),
 'policies',(select jsonb_agg(to_jsonb(p)) from pg_policies p where schemaname='public'),
 'functions',(select jsonb_agg(jsonb_build_object('name',p.proname,'arguments',pg_get_function_identity_arguments(p.oid),'security_definer',p.prosecdef,'config',p.proconfig,'acl',p.proacl,'definition',pg_get_functiondef(p.oid))) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prokind='f' and not exists(select 1 from pg_depend d where d.classid='pg_proc'::regclass and d.objid=p.oid and d.deptype='e')),
 'grants',(select jsonb_agg(to_jsonb(g)) from information_schema.role_table_grants g where table_schema='public'),
 'triggers',(select jsonb_agg(to_jsonb(t)) from information_schema.triggers t where trigger_schema='public'),
 'database_bytes',pg_database_size(current_database()),
 'extensions',(select jsonb_agg(extname) from pg_extension)
) as audit;

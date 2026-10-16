-- STUBS para testar a migração do fluxo v3 num Postgres LOCAL DE TESTE (nunca produção).
-- Reproduz só o mínimo das tabelas que a migração referencia (events, evidencias, execucoes, api_execucoes) e um
-- objeto pré-existente em app_private, para provar que a migração não interfere no que já existe.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema if not exists app_private;
create or replace function app_private.is_master() returns boolean language sql stable as $$ select false $$;
create table public.events (id uuid primary key default gen_random_uuid(), empresa_id uuid not null, titulo text, pre_release text);
create table public.evidencias (id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id), url text);
create table public.execucoes (id uuid primary key default gen_random_uuid(), empresa_id uuid);
create table public.api_execucoes (id uuid primary key default gen_random_uuid(), event_id uuid, empresa_id uuid, execucao_id uuid,
  operacao text, status text, metadata jsonb default '{}'::jsonb, created_at timestamptz default clock_timestamp());
grant usage on schema public to anon, authenticated, service_role;
grant select on public.events to authenticated, service_role;

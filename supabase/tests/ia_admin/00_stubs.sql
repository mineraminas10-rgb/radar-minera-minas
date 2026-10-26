-- STUBS para testar 20261017_ia_assistida_leitura_admin.sql num Postgres LOCAL DE TESTE (nunca produção).
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
-- auth.uid() como no Supabase: lê o "sub" do JWT; aqui simulado por um GUC
create schema if not exists auth;
create or replace function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema auth to anon, authenticated;
create type public.role_t as enum ('master','admin','cliente');
create table public.usuarios_perfil (id uuid primary key, role public.role_t not null, nome text, ativo boolean default true);
create table public.usuario_empresas (usuario_id uuid, empresa_id uuid, ativo boolean default true);
create table public.events (id uuid primary key default gen_random_uuid(), empresa_id uuid not null, titulo_fato text);
create table public.api_execucoes (id uuid primary key default gen_random_uuid(), event_id uuid, empresa_id uuid, operacao text, status text,
  modelo text, custo_estimado_usd numeric, versao_prompt text, input_tokens int, total_tokens int, request_id_provider text,
  data_inicio timestamptz default now(), erro text, motivo_bloqueio text, resposta_texto text, metadata jsonb);
-- como em produção: tabela sem acesso direto para authenticated além do que o RLS permitir (aqui: nenhum grant => nada)
alter table public.api_execucoes enable row level security;
grant usage on schema public to anon, authenticated, service_role;
create schema t;
create table t.res (n serial, nome text, ok boolean, detalhe text);
create function t.chk(p_nome text, p_ok boolean, p_det text default null) returns void language sql as $$ insert into t.res(nome, ok, detalhe) values (p_nome, coalesce(p_ok,false), p_det) $$;
create function t.falha(p_sql text) returns text language plpgsql as $$ begin execute p_sql; return null; exception when others then return sqlerrm; end $$;
grant usage on schema t to anon, authenticated;
grant insert on t.res to anon, authenticated;
grant usage on sequence t.res_n_seq to anon, authenticated;

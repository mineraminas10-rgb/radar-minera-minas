-- STUBS para testar 20261016 + 20261017 + 20261019 num Postgres LOCAL DE TESTE (nunca produção).
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema if not exists auth;
create or replace function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema auth to anon, authenticated, service_role;
create schema if not exists app_private;
create type public.role_t as enum ('master','admin','cliente');
create type public.status_editorial_t as enum ('novo','em_apuracao','liberado_para_pre_release','pronto_para_publicar','publicado','arquivado','descartado');
create table public.usuarios_perfil (id uuid primary key, role public.role_t not null, nome text, ativo boolean default true);
create table public.usuario_empresas (usuario_id uuid, empresa_id uuid, ativo boolean default true);
create table public.events (id uuid primary key default gen_random_uuid(), empresa_id uuid not null, titulo_fato text,
  status_editorial public.status_editorial_t not null default 'em_apuracao', revisao_humana text default 'Pendente', pre_release text,
  url_oficial text, data_evento date, data_publicacao timestamptz, created_at timestamptz not null default '2026-09-01T00:00:00Z');
create table public.event_scores (id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id),
  vigente boolean default true, estagio text, score_bruto numeric, score_normalizado numeric, score_relevancia numeric,
  versao_score text, componentes jsonb, prioridade text, created_at timestamptz not null default now());
create table public.evidencias (id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id), trecho_literal text);
create table public.documentos (id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id), url text);
create table public.api_execucoes (id uuid primary key default gen_random_uuid(), event_id uuid, empresa_id uuid, operacao text, status text,
  data_inicio timestamptz default now(), erro text, motivo_bloqueio text, resposta_texto text, metadata jsonb);
grant usage on schema public to anon, authenticated, service_role;
grant select on public.events, public.event_scores, public.evidencias, public.documentos to authenticated, service_role;
create schema t;
create table t.res (n serial, nome text, ok boolean, detalhe text);
create function t.chk(p_nome text, p_ok boolean, p_det text default null) returns void language sql as $$ insert into t.res(nome, ok, detalhe) values (p_nome, coalesce(p_ok,false), p_det) $$;
create function t.falha(p_sql text) returns text language plpgsql as $$ begin execute p_sql; return null; exception when others then return sqlerrm; end $$;
grant usage on schema t to anon, authenticated;
grant insert on t.res to anon, authenticated;
grant usage on sequence t.res_n_seq to anon, authenticated;

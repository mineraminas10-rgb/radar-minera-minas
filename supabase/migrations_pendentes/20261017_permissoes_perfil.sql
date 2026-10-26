-- =====================================================================================
-- PERMISSÕES POR PERFIL NO BANCO   (NÃO APLICADA)
-- Hoje a matriz "quem pode o quê" está escrita no index.html (PERMISSOES). Isto a leva para o banco:
--   * public.perfil_permissoes (role, acao, permitido) — a ÚNICA fonte da verdade;
--   * public.minhas_permissoes()  — a interface lê daqui ao entrar (não decide mais nada sozinha);
--   * public.tem_permissao(acao)  — as funções do servidor usam a mesma tabela.
-- ADITIVA e idempotente: cria 1 tabela, 2 funções e semeia a matriz ATUAL (mesmos valores que a interface já usa).
-- Re-aplicar NÃO sobrescreve ajustes feitos depois (insert ... on conflict do nothing).
-- NÃO altera usuarios_perfil, events, api_execucoes, RLS nem policies existentes. Não chama IA.
-- Para mudar uma permissão: update public.perfil_permissoes set permitido = ... where role = '...' and acao = '...';
--   (sem grant de escrita para a aplicação: só quem tem acesso ao banco — SQL Editor/migration — altera).
-- Reverter: 20261017_permissoes_perfil_rollback.sql
-- =====================================================================================

create table if not exists public.perfil_permissoes (
  role       text    not null,
  acao       text    not null,
  permitido  boolean not null default false,
  descricao  text,
  primary key (role, acao)
);

insert into public.perfil_permissoes (role, acao, permitido, descricao) values
  ('master','editorial',           true,  'Operar a fila editorial (status, pré-release, checklist)'),
  ('master','checklist_desmarcar', true,  'Desmarcar/apagar item do checklist'),
  ('master','carteiras_editar',    true,  'Criar/editar/excluir carteiras, pesos e fontes'),
  ('master','cliente_criar',       true,  'Botão "+ Novo cliente"'),
  ('master','admin_painel',        true,  'Menu ADMIN (empresas, usuários, API, consumo, auditoria)'),
  ('master','ia_assistida',        true,  'Ver a IA assistida no detalhe do evento'),
  ('master','ia_assistida_custo',  true,  'Ver modelo, custo e prompt da IA assistida'),
  ('master','todas_empresas',      true,  'Acessar todas as empresas, sem vínculo'),
  ('admin', 'editorial',           true,  'Operar a fila editorial (status, pré-release, checklist)'),
  ('admin', 'checklist_desmarcar', true,  'Desmarcar/apagar item do checklist'),
  ('admin', 'carteiras_editar',    true,  'Criar/editar/excluir carteiras, pesos e fontes'),
  ('admin', 'cliente_criar',       false, 'Botão "+ Novo cliente"'),
  ('admin', 'admin_painel',        false, 'Menu ADMIN (empresas, usuários, API, consumo, auditoria)'),
  ('admin', 'ia_assistida',        true,  'Ver a IA assistida no detalhe do evento'),
  ('admin', 'ia_assistida_custo',  false, 'Ver modelo, custo e prompt da IA assistida'),
  ('admin', 'todas_empresas',      false, 'Acessar todas as empresas, sem vínculo')
on conflict (role, acao) do nothing;

-- Permissão de UMA ação para o usuário logado (perfil ativo). Sem sessão ou sem perfil ativo: false.
create or replace function public.tem_permissao(p_acao text) returns boolean
language sql stable security definer set search_path = public, pg_catalog as $$
  select coalesce((
    select pp.permitido
      from public.usuarios_perfil u
      join public.perfil_permissoes pp on pp.role = u.role::text and pp.acao = p_acao
     where u.id = auth.uid() and coalesce(u.ativo, true)
  ), false)
$$;

-- Todas as permissões do usuário logado, como {"acao": true/false}. Sem sessão: erro. Sem perfil ativo: {}.
create or replace function public.minhas_permissoes() returns jsonb
language plpgsql stable security definer set search_path = public, pg_catalog as $$
begin
  if auth.uid() is null then
    raise exception 'minhas_permissoes: sessão obrigatória' using errcode = 'insufficient_privilege';
  end if;
  return coalesce((
    select jsonb_object_agg(pp.acao, pp.permitido)
      from public.usuarios_perfil u
      join public.perfil_permissoes pp on pp.role = u.role::text
     where u.id = auth.uid() and coalesce(u.ativo, true)
  ), '{}'::jsonb);
end $$;

-- Acesso: a tabela é legível (não é segredo), mas ninguém da aplicação escreve nela.
alter table public.perfil_permissoes enable row level security;
revoke all on public.perfil_permissoes from public, anon, authenticated;
grant select on public.perfil_permissoes to authenticated, service_role;
drop policy if exists perfil_permissoes_leitura on public.perfil_permissoes;
create policy perfil_permissoes_leitura on public.perfil_permissoes for select to authenticated using (true);

revoke all on function public.tem_permissao(text), public.minhas_permissoes() from public, anon;
grant execute on function public.tem_permissao(text), public.minhas_permissoes() to authenticated, service_role;

-- Hardening seguro sem quebrar o frontend anon atual.
-- 1) Tabelas que o frontend somente le: habilita RLS e permite SELECT,
--    mas bloqueia escrita anon/authenticated. Coletores via service_role continuam funcionando.
do $$
declare t text;
begin
  foreach t in array array[
    'event_scores','evidencias','documentos',
    'm8_acidentes_detalhe','m9a_movimentacao_estado','carteira_scores'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke insert, update, delete, truncate, references, trigger on table public.%I from anon, authenticated', t);
    execute format('drop policy if exists leitura_publica_temporaria on public.%I', t);
    execute format('create policy leitura_publica_temporaria on public.%I for select to anon, authenticated using (true)', t);
  end loop;
end $$;

-- 2) Remove privilegios DDL-like desnecessarios das tabelas que ainda precisam
--    de escrita anon pelo frontend atual.
revoke truncate, references, trigger on table
  public.events,
  public.checklist_editorial,
  public.carteiras,
  public.carteira_pesos,
  public.carteira_fontes
from anon, authenticated;

-- 3) A funcao administrativa de auto-RLS nao deve ser chamavel pela API publica.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

-- 4) Fixa search_path das funcoes sinalizadas pelo advisor.
alter function public.set_updated_at() set search_path = public, pg_catalog;
alter function public.recalcular_carteiras() set search_path = public, pg_catalog;
alter function public.seed_checklist_carteira_do_legado(uuid, integer) set search_path = public, pg_catalog;
alter function public.trg_bloqueia_publicacao_sem_revisao_humana() set search_path = public, pg_catalog;
alter function public.trg_valida_transicao_estado_processual() set search_path = public, pg_catalog;
alter function public.contexto_interno_evento(uuid) set search_path = public, pg_catalog;
alter function public.trg_valida_carteira_mesma_empresa_fonte() set search_path = public, pg_catalog;
alter function public.trg_regra_evento_carteira_herda_e_valida() set search_path = public, pg_catalog;
alter function public.trg_evento_carteira_herda_e_valida() set search_path = public, pg_catalog;
alter function public.clonar_checklist_carteira(uuid, uuid) set search_path = public, pg_catalog;
alter function public.clonar_carteira_config(uuid, uuid, text) set search_path = public, pg_catalog;
alter function public.clonar_regra_evento_config(uuid, uuid, text) set search_path = public, pg_catalog;

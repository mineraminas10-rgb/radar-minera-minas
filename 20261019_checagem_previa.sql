-- SOMENTE LEITURA. Rode ANTES da 20261019: confere se as colunas que as novas funções leem existem no banco real.
-- Esperado: 0 linhas em "faltando". Qualquer linha = me avise, não aplique a migração.
with esperado(tabela, coluna) as (values
  ('events','id'),('events','empresa_id'),('events','status_editorial'),('events','revisao_humana'),('events','pre_release'),
  ('events','url_oficial'),('events','data_evento'),('events','data_publicacao'),('events','created_at'),
  ('event_scores','event_id'),('event_scores','vigente'),('event_scores','estagio'),('event_scores','score_bruto'),
  ('event_scores','score_normalizado'),('event_scores','score_relevancia'),('event_scores','versao_score'),
  ('event_scores','componentes'),('event_scores','prioridade'),('event_scores','created_at'),
  ('evidencias','event_id'),('evidencias','trecho_literal'),('documentos','event_id'),
  ('api_execucoes','event_id'),('api_execucoes','operacao'),('api_execucoes','status'),('api_execucoes','data_inicio'),('api_execucoes','resposta_texto'),
  ('usuario_empresas','usuario_id'),('usuario_empresas','empresa_id'),('usuario_empresas','ativo'))
select 'faltando' as situacao, e.tabela, e.coluna
  from esperado e
  left join information_schema.columns c on c.table_schema = 'public' and c.table_name = e.tabela and c.column_name = e.coluna
 where c.column_name is null
union all
select 'funcao_ausente', 'public', f from (values ('tem_permissao'), ('minhas_permissoes')) v(f)
 where not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = v.f)
union all
select 'ja_aplicada', 'public', 'fila_parametros' where to_regclass('public.fila_parametros') is not null
union all
select 'precisa_20261016_antes', 'public', 'fila_decisao_score' where to_regprocedure('public.fila_decisao_score(uuid)') is null;

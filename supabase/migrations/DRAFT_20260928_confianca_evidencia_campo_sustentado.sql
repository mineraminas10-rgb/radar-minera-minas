-- ============================================================================
-- DRAFT — revisão e execução pela Rapha no Supabase SQL Editor, como as
-- demais migrações deste projeto. Não aplicado em produção por este
-- assistente (nunca recebi a connection string de produção — não é acesso
-- que este assistente tem, por desenho).
--
-- Etapa 1 de 5 da implementação aprovada em 28/09/2026 (Escopo v2.8 +
-- Carta M6 + Carta de Calibração M8/M9A — opção "arquitetura primeiro").
-- Cobre exatamente as 3 alterações aditivas aprovadas, nada além delas:
-- nenhuma tabela nova, nenhum enum novo, nenhuma coluna NOT NULL, nenhuma
-- alteração em coluna existente.
--
-- Confirmado antes desta migration, na réplica local que espelha o estado
-- de produção já validado nesta conversa (11 migrações base + patches de
-- multi-tenant/M8-M9A + as 5 DRAFTs de 24/09 já aplicadas por você):
--
--   select 'event_scores.confianca_evidencial' as alvo,
--     exists(select 1 from information_schema.columns
--            where table_schema='public' and table_name='event_scores'
--              and column_name='confianca_evidencial') as existe
--   union all
--   select 'eventos_relacionados.evidencia_id',
--     exists(select 1 from information_schema.columns
--            where table_schema='public' and table_name='eventos_relacionados'
--              and column_name='evidencia_id')
--   union all
--   select 'evidencias.campo_sustentado',
--     exists(select 1 from information_schema.columns
--            where table_schema='public' and table_name='evidencias'
--              and column_name='campo_sustentado');
--
--   Resultado: as 3 linhas vieram `existe = false`. Rode a mesma consulta
--   no Supabase antes de aplicar esta migration, pra confirmar que nada
--   mudou em produção entre a auditoria (28/09) e agora — se alguma vier
--   `true`, PARE e me avise antes de continuar (pode ser sinal de que
--   alguém já aplicou algo parecido, ou de drift de novo).
--
-- Reversibilidade: as 3 colunas são aditivas e nullable — não alteram
-- nenhuma linha existente, não quebram nenhum SELECT/INSERT/UPDATE que já
-- funciona hoje (o Postgres ignora coluna nova em INSERT sem ela listada).
-- Rollback (não faço isso automaticamente, é só documentação de como
-- desfazer se um dia for preciso):
--
--   alter table event_scores drop column if exists confianca_evidencial;
--   alter table eventos_relacionados drop column if exists evidencia_id;
--   alter table evidencias drop column if exists campo_sustentado;
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- 1) event_scores.confianca_evidencial
--
-- Onde mora e por quê: em event_scores (não em events), porque é "memória
-- de cálculo" daquela rodada específica de score — mesmo padrão já usado
-- por piso_aplicado/teto_aplicado, que vivem na mesma tabela. Escala 0–1,
-- mesmo domínio de evidencias.confianca (numeric(3,2)), para poder ser
-- calculada como agregação das evidências daquele evento sem conversão.
--
-- NULL é o valor esperado até existir uma regra objetiva e reproduzível de
-- cálculo — não preencho com heurística arriscada aqui, isso é trabalho da
-- Etapa 2 (pipeline), e mesmo lá a orientação explícita é nunca assumir
-- 1.0 só porque existe trecho literal.
-- ----------------------------------------------------------------------------
alter table event_scores add column confianca_evidencial numeric(3,2);

comment on column event_scores.confianca_evidencial is
  'Confiança evidencial agregada desta rodada de score (0–1), separada de score/prioridade/completude '
  '(Carta de Calibração M8/M9A, campo de normalização #6). NULL até existir regra objetiva e reproduzível '
  'de cálculo — nunca preencher com 1.0 automático só por existir trecho literal (decisão de 28/09/2026).';

-- ----------------------------------------------------------------------------
-- 2) eventos_relacionados.evidencia_id
--
-- Vínculo sem fusão (Escopo v2.8) precisa de prova rastreável, não só de
-- um critério em texto livre — mesmo padrão já usado em
-- timeline_processual.evidencia_id (que já existe e já referencia
-- evidencias(id) do mesmo jeito).
-- ----------------------------------------------------------------------------
alter table eventos_relacionados add column evidencia_id uuid references evidencias(id);

comment on column eventos_relacionados.evidencia_id is
  'Evidência que sustenta este vínculo (opcional — nem todo critério de relação nasce de uma evidência '
  'documental, ex.: proximidade temporal pura). Vínculo continua sem fusão editorial por desenho; esta '
  'coluna só torna o "porquê" auditável quando existe prova documental por trás do critério.';

-- ----------------------------------------------------------------------------
-- 3) evidencias.campo_sustentado
--
-- Hoje o "campo sustentado" (qual campo do evento esta evidência comprova)
-- é um workaround dentro de resumo_extraido (comentário já existente no
-- código dos dois coletores, db_writer.py, admitindo isso). Esta coluna dá
-- um lugar próprio, sem mexer em resumo_extraido (que continua livre para
-- o resumo em si, sem sobrecarga de responsabilidade).
-- ----------------------------------------------------------------------------
alter table evidencias add column campo_sustentado text;

comment on column evidencias.campo_sustentado is
  'Nome do campo do evento que esta evidência sustenta (ex.: "titulo_fato", "data_evento", '
  '"municipio") — separado do resumo em texto livre de resumo_extraido. Nullable: evidências '
  'já gravadas antes desta coluna existir continuam válidas, só sem essa granularidade.';

commit;

-- ----------------------------------------------------------------------------
-- Verificação (rodar depois de aplicar):
--
--   select column_name, is_nullable, data_type
--   from information_schema.columns
--   where (table_name = 'event_scores' and column_name = 'confianca_evidencial')
--      or (table_name = 'eventos_relacionados' and column_name = 'evidencia_id')
--      or (table_name = 'evidencias' and column_name = 'campo_sustentado');
--   -- esperado: 3 linhas, todas is_nullable = 'YES'.
--
--   -- confirma que nada existente quebrou (contagens devem bater com o
--   -- que já existia antes desta migration):
--   select count(*) from event_scores;
--   select count(*) from eventos_relacionados;
--   select count(*) from evidencias;
-- ----------------------------------------------------------------------------

-- ============================================================================
-- Testado em réplica local (radar_draft_test) em 28/09/2026: aplicação
-- limpa sobre a cadeia completa (11 migrações base + patches de
-- multi-tenant/M8-M9A + as 5 DRAFTs de 24/09), confirmado por \d nas 3
-- tabelas que as colunas existem, são nullable, e que as constraints e
-- dados existentes (inclusive as constraints de checklist_editorial que
-- dependem de evidencias, e as FKs de timeline_processual/m4_obrigacoes
-- que também referenciam evidencias) continuam intactos.
-- ============================================================================

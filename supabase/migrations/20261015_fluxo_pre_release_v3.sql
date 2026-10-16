-- =====================================================================================
-- MIGRAÇÃO PENDENTE (NÃO APLICADA) — Fluxo do pré-release enriquecido (desenho v3)
-- Só aplicar depois de aprovação expressa da Raphaela. Revisar, rodar no SQL Editor (selecionando TODO o texto).
--
-- O QUE É: 6 tabelas NOVAS, funções e uma view. Estritamente ADITIVA:
--   * não altera events, evidencias, checklist_*, api_execucoes, execucoes, event_scores nem qualquer tabela existente;
--   * não cria gatilho em tabela existente; não escreve em events.pre_release; não chama IA; não agenda nada.
-- FEATURE FLAG: nasce DESLIGADA (pre_release_parametros.parametros->>'fluxo_ativo' = false). Com a flag desligada, todo
--   gatilho abaixo recusa qualquer escrita ('fluxo_v3_desligado'). Para ligar/desligar: public.pre_release_definir_fluxo_ativo().
-- DEPENDÊNCIAS (já existem em produção): public.events, public.evidencias, public.api_execucoes, public.execucoes,
--   schema app_private. NÃO depende da migração CRIT pendente (a seleção é gravada, não calculada, aqui).
-- Rollback: 20261015_fluxo_pre_release_v3_rollback.sql
-- =====================================================================================

create schema if not exists app_private;

-- ---------------------------------------------------------------------------------
-- 1) Parâmetros versionados (padrão de criticidade_parametros): nova versão = nova linha.
--    Guarda a flag, o teto da seleção, o vocabulário e os templates (itens críticos e classe de impacto: PROPOSTA a validar).
-- ---------------------------------------------------------------------------------
create table if not exists public.pre_release_parametros (
  versao_parametros text primary key,
  parametros        jsonb not null,
  vigente           boolean not null default false,
  observacao        text,
  criado_em         timestamptz not null default now()
);
create unique index if not exists uq_pre_release_parametros_vigente on public.pre_release_parametros ((true)) where vigente;

insert into public.pre_release_parametros (versao_parametros, parametros, vigente, observacao)
select 'PRE-RELEASE-PARAMS-V1', $json${
 "fluxo_ativo": false,
 "teto_selecao": 20,
 "estados_matriz": ["confirmado","nao_confirmado","nao_localizado","nao_aplicavel","requer_apuracao_humana",
                    "aguardando_contraditorio","fonte_indisponivel","divergencia_entre_fontes"],
 "classes_impacto": ["FATO_PRINCIPAL","ATRIBUICAO","GRAVIDADE","PERIFERICA"],
 "templates": {
  "core": [
   {"codigo":"core.fato_novo","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"core.empresa","critico":true,"classe_impacto":"ATRIBUICAO"},
   {"codigo":"core.orgao_fonte","critico":true,"classe_impacto":"FATO_PRINCIPAL","fonte_primaria":true},
   {"codigo":"core.data_ato","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"core.url_documento","critico":true,"classe_impacto":"FATO_PRINCIPAL","fonte_primaria":true},
   {"codigo":"core.ultima_atualizacao","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"core.contraditorio_processual","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"core.contato_jornalistico_atual","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"core.antecedente","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"core.proximo_marco","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"core.delta","critico":false,"classe_impacto":"PERIFERICA"}
  ],
  "M6_outorgas": [
   {"codigo":"m6.ato","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m6.empresa_projeto","critico":true,"classe_impacto":"ATRIBUICAO"},
   {"codigo":"m6.municipio","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m6.corpo_hidrico","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m6.modo_uso","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m6.vazao","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m6.validade","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m6.tempo","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m6.consequencia_operacional","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m6.ato_anterior","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m6.lacunas","critico":false,"classe_impacto":"PERIFERICA"}
  ],
  "M7_reunioes": [
   {"codigo":"m7.condicionante","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m7.pedido","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m7.resultado_individual","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m7.texto_vigente","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m7.texto_anterior","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m7.fundamento_tecnico","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m7.efeito_pratico","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m7.proximo_marco","critico":false,"classe_impacto":"PERIFERICA"}
  ],
  "M8_acidentes_ambientais": [
   {"codigo":"m8.ocorrencia","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m8.vinculo_minerario","critico":true,"classe_impacto":"ATRIBUICAO"},
   {"codigo":"m8.produto_material","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m8.volume","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m8.curso_dagua","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m8.vitimas","critico":true,"classe_impacto":"GRAVIDADE"},
   {"codigo":"m8.impacto_externo","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m8.risco_estrutura","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m8.risco_abastecimento","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m8.medidas_adotadas","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m8.intervalo","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m8.incertezas","critico":false,"classe_impacto":"PERIFERICA"}
  ],
  "M9A_anm_movimentacoes": [
   {"codigo":"m9a.ato_minerario","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.processo","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.titular","critico":true,"classe_impacto":"ATRIBUICAO"},
   {"codigo":"m9a.municipios","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.fase","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.efeito_juridico","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.situacao_processual","critico":true,"classe_impacto":"FATO_PRINCIPAL"},
   {"codigo":"m9a.substancia","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m9a.area","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m9a.atos_relacionados","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m9a.contexto_espacial","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m9a.consequencia_operacional","critico":false,"classe_impacto":"PERIFERICA"},
   {"codigo":"m9a.contraditorio","critico":false,"classe_impacto":"PERIFERICA"}
  ]
 }
}$json$::jsonb, true,
 'Versão inicial. fluxo_ativo = false (flag DESLIGADA). Itens críticos e classes de impacto são proposta a validar.'
where not exists (select 1 from public.pre_release_parametros);

-- ---------------------------------------------------------------------------------
-- 2) Flag e utilitários
-- ---------------------------------------------------------------------------------
create or replace function app_private.fluxo_ativo() returns boolean
language sql stable security definer set search_path = public, pg_catalog as $$
  select coalesce((select (p.parametros->>'fluxo_ativo')::boolean from public.pre_release_parametros p where p.vigente limit 1), false)
$$;

create or replace function app_private.fluxo_exige_ativo() returns void
language plpgsql stable security definer set search_path = public, pg_catalog as $$
begin
  if not app_private.fluxo_ativo() then
    raise exception 'fluxo_v3_desligado' using errcode = '55000';
  end if;
end $$;

-- imutabilidade: nenhuma linha de registro é alterada ou apagada
create or replace function app_private.fluxo_imutavel() returns trigger
language plpgsql as $$
begin
  raise exception 'registro_imutavel: % em % nao e permitido', tg_op, tg_table_name using errcode = '55000';
end $$;

create or replace function app_private.fluxo_parametros_guarda() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'registro_imutavel: DELETE em pre_release_parametros nao e permitido' using errcode = '55000';
  end if;
  -- só a coluna "vigente" pode mudar; o conteúdo de uma versão nunca é reescrito
  if new.versao_parametros is distinct from old.versao_parametros or new.parametros is distinct from old.parametros
     or new.criado_em is distinct from old.criado_em or new.observacao is distinct from old.observacao then
    raise exception 'registro_imutavel: so a coluna vigente pode mudar; nova versao = nova linha' using errcode = '55000';
  end if;
  return new;
end $$;

drop trigger if exists trg_pre_release_parametros_guarda on public.pre_release_parametros;
create trigger trg_pre_release_parametros_guarda before update or delete on public.pre_release_parametros
  for each row execute function app_private.fluxo_parametros_guarda();

-- liga/desliga a flag criando UMA NOVA VERSÃO de parâmetros (auditável); só o service_role / SQL Editor chama
create or replace function public.pre_release_definir_fluxo_ativo(p_ativo boolean, p_motivo text) returns text
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_atual record; v_nova text;
begin
  if coalesce(trim(p_motivo), '') = '' then raise exception 'motivo_obrigatorio'; end if;
  select * into v_atual from public.pre_release_parametros where vigente limit 1;
  if not found then raise exception 'sem_parametros_vigentes'; end if;
  v_nova := 'PRE-RELEASE-PARAMS-' || to_char(clock_timestamp() at time zone 'utc', 'YYYYMMDDHH24MISSMS');
  update public.pre_release_parametros set vigente = false where versao_parametros = v_atual.versao_parametros;
  insert into public.pre_release_parametros (versao_parametros, parametros, vigente, observacao)
  values (v_nova, jsonb_set(v_atual.parametros, '{fluxo_ativo}', to_jsonb(p_ativo)), true,
          'fluxo_ativo=' || p_ativo::text || ' | ' || p_motivo || ' | base ' || v_atual.versao_parametros);
  return v_nova;
end $$;

-- ---------------------------------------------------------------------------------
-- 3) selecao_lotes — ranking CONGELADO de cada execução do coletor (teto 20, não meta)
-- ---------------------------------------------------------------------------------
create table if not exists public.selecao_lotes (
  id                uuid primary key default gen_random_uuid(),
  execucao_id       uuid references public.execucoes(id),
  versao_regra      text not null,
  versao_parametros text,
  teto              int  not null default 20 check (teto between 1 and 20),
  selecionados      int  not null default 0,
  itens             jsonb not null default '[]'::jsonb,   -- [{ordem,event_id,id_evento,modulo,criticidade,prioridade,pontuacao,grupo,motivo}]
  fora_da_selecao   jsonb not null default '[]'::jsonb,   -- somente leitura: quem ficou de fora e por quê
  hash_ranking      text,
  criado_em         timestamptz not null default clock_timestamp(),
  constraint chk_selecao_itens_lista check (jsonb_typeof(itens) = 'array' and jsonb_typeof(fora_da_selecao) = 'array'),
  constraint chk_selecao_dentro_do_teto check (jsonb_array_length(itens) <= teto)
);

create or replace function app_private.selecao_lote_antes_insert() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
begin
  perform app_private.fluxo_exige_ativo();
  new.selecionados := jsonb_array_length(new.itens);
  new.hash_ranking := encode(sha256(convert_to(new.itens::text, 'UTF8')), 'hex');
  return new;
end $$;
drop trigger if exists trg_selecao_lote_antes_insert on public.selecao_lotes;
create trigger trg_selecao_lote_antes_insert before insert on public.selecao_lotes
  for each row execute function app_private.selecao_lote_antes_insert();

-- ---------------------------------------------------------------------------------
-- 4) monitoramento_verificacoes — verificação dos casos já monitorados + delta (sem mudança = nenhuma data muda)
-- ---------------------------------------------------------------------------------
create table if not exists public.monitoramento_verificacoes (
  id                      uuid primary key default gen_random_uuid(),
  event_id                uuid not null references public.events(id),
  empresa_id              uuid not null,
  execucao_id             uuid references public.execucoes(id),
  resultado               text not null check (resultado in ('sem_mudanca', 'mudanca_material')),
  impressao_material      text,
  impressao_anterior      text,
  delta                   jsonb,    -- {campos:[{campo,antes,depois}], evidencias_novas:[...], tipo_mudanca, gatilhos_completa:[...]}
  modo_sugerido           text check (modo_sugerido in ('delta', 'completa')),
  data_real_atualizacao   date,
  data_real_origem        text check (data_real_origem in ('ato', 'documento', 'observada')),
  criado_em               timestamptz not null default clock_timestamp(),
  constraint chk_verif_sem_mudanca_vazia check (
    resultado <> 'sem_mudanca' or (delta is null and data_real_atualizacao is null and data_real_origem is null)),
  constraint chk_verif_mudanca_completa check (
    resultado <> 'mudanca_material' or (delta is not null and data_real_atualizacao is not null and data_real_origem is not null))
);
create index if not exists ix_monitoramento_verificacoes_evento on public.monitoramento_verificacoes (event_id, criado_em desc);

create or replace function app_private.monitoramento_antes_insert() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_emp uuid;
begin
  perform app_private.fluxo_exige_ativo();
  select empresa_id into v_emp from public.events where id = new.event_id;
  if not found then raise exception 'evento_inexistente'; end if;
  new.empresa_id := v_emp;
  return new;
end $$;
drop trigger if exists trg_monitoramento_antes_insert on public.monitoramento_verificacoes;
create trigger trg_monitoramento_antes_insert before insert on public.monitoramento_verificacoes
  for each row execute function app_private.monitoramento_antes_insert();

-- ---------------------------------------------------------------------------------
-- 5) dossie_versoes — dossiê fechado e imutável (afirmações, evidências vinculadas, matriz, hash)
--    Reaproveita: ia_dossie_evento() (base), evidencias, checklist_editorial (a matriz parte do checklist de 12 perguntas).
-- ---------------------------------------------------------------------------------
create table if not exists public.dossie_versoes (
  id                uuid primary key default gen_random_uuid(),
  event_id          uuid not null references public.events(id),
  empresa_id        uuid not null,
  versao            int  not null,
  dossie_anterior_id uuid references public.dossie_versoes(id),
  modo_analise      text not null check (modo_analise in ('completa', 'delta')),
  execucao_ia_id    uuid references public.api_execucoes(id),   -- a análise revisada
  base              jsonb not null,                              -- saída de ia_dossie_evento
  afirmacoes        jsonb not null default '[]'::jsonb,          -- [{id,campo,texto,status,evidencias:[{ev,evidencia_id}],hierarquia_fonte}]
  matriz            jsonb not null default '[]'::jsonb,          -- [{codigo,pergunta_numero,estado,critico,classe_impacto,fonte_primaria,evidencia_ids,observacao,risco_reputacional,justificativa_sem_risco}]
  alertas           jsonb not null default '{}'::jsonb,          -- {chaves_conflitantes,duplicidade_nao_resolvida,pedido_ato_ambiguo}
  delta             jsonb,
  contexto_anterior jsonb,
  hash              text not null,
  criado_por        uuid,
  criado_em         timestamptz not null default clock_timestamp(),
  unique (event_id, versao)
);
create index if not exists ix_dossie_versoes_evento on public.dossie_versoes (event_id, versao desc);

create or replace function app_private.fluxo_validar_matriz(p_event uuid, p_matriz jsonb) returns void
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare it jsonb; est text; cls text; eid text;
  v_est text[] := array['confirmado','nao_confirmado','nao_localizado','nao_aplicavel','requer_apuracao_humana',
                        'aguardando_contraditorio','fonte_indisponivel','divergencia_entre_fontes'];
  v_cls text[] := array['FATO_PRINCIPAL','ATRIBUICAO','GRAVIDADE','PERIFERICA'];
begin
  if p_matriz is null or jsonb_typeof(p_matriz) <> 'array' then raise exception 'matriz_invalida: precisa ser uma lista'; end if;
  for it in select * from jsonb_array_elements(p_matriz) loop
    if coalesce(trim(it->>'codigo'), '') = '' then raise exception 'matriz_invalida: item sem codigo'; end if;
    est := it->>'estado'; cls := it->>'classe_impacto';
    if est is null or not (est = any (v_est)) then raise exception 'matriz_invalida: estado % em %', est, it->>'codigo'; end if;
    if cls is null or not (cls = any (v_cls)) then raise exception 'matriz_invalida: classe_impacto % em %', cls, it->>'codigo'; end if;
    if coalesce((it->>'critico')::boolean, false) and cls = 'PERIFERICA' then
      raise exception 'matriz_invalida: item critico % nao pode ser PERIFERICA', it->>'codigo';
    end if;
    if est = 'confirmado' and coalesce(jsonb_array_length(it->'evidencia_ids'), 0) = 0 then
      raise exception 'matriz_invalida: % confirmado exige evidencia', it->>'codigo';
    end if;
    if est = 'nao_localizado' and trim(coalesce(it->>'observacao', '')) = '' then
      raise exception 'matriz_invalida: % nao_localizado exige observacao', it->>'codigo';
    end if;
    if est = 'aguardando_contraditorio' and (it->>'risco_reputacional') = 'false'
       and trim(coalesce(it->>'justificativa_sem_risco', '')) = '' then
      raise exception 'matriz_invalida: % sem risco reputacional exige justificativa escrita', it->>'codigo';
    end if;
    for eid in select jsonb_array_elements_text(coalesce(it->'evidencia_ids', '[]'::jsonb)) loop
      if not exists (select 1 from public.evidencias v where v.id = eid::uuid and v.event_id = p_event) then
        raise exception 'matriz_invalida: evidencia % nao pertence ao evento', eid;
      end if;
    end loop;
  end loop;
end $$;

create or replace function app_private.fluxo_validar_afirmacoes(p_event uuid, p_afirmacoes jsonb) returns void
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare it jsonb; ev jsonb; v_st text; n int;
  v_est text[] := array['confirmado','nao_confirmado','nao_localizado','nao_aplicavel','requer_apuracao_humana',
                        'aguardando_contraditorio','fonte_indisponivel','divergencia_entre_fontes'];
begin
  if p_afirmacoes is null or jsonb_typeof(p_afirmacoes) <> 'array' then raise exception 'afirmacoes_invalidas: precisa ser uma lista'; end if;
  for it in select * from jsonb_array_elements(p_afirmacoes) loop
    if coalesce(trim(it->>'id'), '') = '' or coalesce(trim(it->>'texto'), '') = '' then
      raise exception 'afirmacoes_invalidas: afirmacao sem id ou texto';
    end if;
    v_st := it->>'status';
    if v_st is null or not (v_st = any (v_est)) then raise exception 'afirmacoes_invalidas: status % em %', v_st, it->>'id'; end if;
    n := 0;
    for ev in select * from jsonb_array_elements(coalesce(it->'evidencias', '[]'::jsonb)) loop
      if not exists (select 1 from public.evidencias v where v.id = (ev->>'evidencia_id')::uuid and v.event_id = p_event) then
        raise exception 'afirmacoes_invalidas: evidencia % nao pertence ao evento', ev->>'evidencia_id';
      end if;
      n := n + 1;
    end loop;
    if v_st = 'confirmado' and n = 0 then raise exception 'afirmacoes_invalidas: % confirmada sem evidencia', it->>'id'; end if;
  end loop;
end $$;

create or replace function app_private.dossie_antes_insert() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_emp uuid; v_hash text; v_ant record;
begin
  perform app_private.fluxo_exige_ativo();
  select empresa_id into v_emp from public.events where id = new.event_id;
  if not found then raise exception 'evento_inexistente'; end if;
  new.empresa_id := v_emp;
  perform pg_advisory_xact_lock(hashtextextended('dossie|' || new.event_id::text, 0));
  select id, versao into v_ant from public.dossie_versoes where event_id = new.event_id order by versao desc limit 1;
  new.versao := coalesce(v_ant.versao, 0) + 1;
  new.dossie_anterior_id := v_ant.id;
  perform app_private.fluxo_validar_matriz(new.event_id, new.matriz);
  perform app_private.fluxo_validar_afirmacoes(new.event_id, new.afirmacoes);
  if new.execucao_ia_id is not null and not exists (
       select 1 from public.api_execucoes a where a.id = new.execucao_ia_id and a.event_id = new.event_id) then
    raise exception 'dossie_invalido: execucao de IA nao pertence ao evento';
  end if;
  v_hash := encode(sha256(convert_to(jsonb_build_object('modo', new.modo_analise, 'base', new.base, 'afirmacoes', new.afirmacoes,
              'matriz', new.matriz, 'alertas', new.alertas, 'delta', coalesce(new.delta, 'null'::jsonb),
              'contexto', coalesce(new.contexto_anterior, 'null'::jsonb))::text, 'UTF8')), 'hex');
  if new.hash is not null and new.hash <> '' and new.hash <> v_hash then raise exception 'dossie_invalido: hash informado difere do calculado'; end if;
  new.hash := v_hash;
  return new;
end $$;
drop trigger if exists trg_dossie_antes_insert on public.dossie_versoes;
create trigger trg_dossie_antes_insert before insert on public.dossie_versoes
  for each row execute function app_private.dossie_antes_insert();

-- ---------------------------------------------------------------------------------
-- 6) fluxo_transicoes — o ÚNICO escritor de estado (registro append-only; revisões, liberações e apurações são linhas daqui)
--    Reaproveita a ideia de auditoria; não duplica public.auditoria (essa continua para ações administrativas gerais).
-- ---------------------------------------------------------------------------------
create table if not exists public.fluxo_transicoes (
  id                    uuid primary key default gen_random_uuid(),
  seq                   bigint generated always as identity,
  event_id              uuid not null references public.events(id),
  empresa_id            uuid not null,
  de                    text not null,
  acao                  text not null,
  para                  text not null,
  usuario_id            uuid,
  motivo                text,
  payload               jsonb not null default '{}'::jsonb,
  dossie_versao_id      uuid references public.dossie_versoes(id),
  pre_release_versao_id uuid,
  created_at            timestamptz not null default clock_timestamp(),
  constraint chk_fluxo_estados check (
    de in ('SEM_FLUXO','MONITORADO','REVISAO_SELECAO','PRONTO_PARA_IA','IA_LIBERADA','IA_EXECUTADA','REVISAO_ANALISE_IA',
           'PRE_RELEASE_LIBERADO','PRE_RELEASE_GERADO','REVISAO_FINAL','APROVADO_PARA_PUBLICACAO','DEVOLVIDO_PARA_AJUSTE',
           'PUBLICADO','DESCARTADO','ATUALIZADO','REVISAO_MUDANCA')
    and para in ('MONITORADO','REVISAO_SELECAO','PRONTO_PARA_IA','IA_LIBERADA','IA_EXECUTADA','REVISAO_ANALISE_IA',
           'PRE_RELEASE_LIBERADO','PRE_RELEASE_GERADO','REVISAO_FINAL','APROVADO_PARA_PUBLICACAO','DEVOLVIDO_PARA_AJUSTE',
           'PUBLICADO','DESCARTADO','ATUALIZADO','REVISAO_MUDANCA'))
);
create unique index if not exists uq_fluxo_transicoes_seq on public.fluxo_transicoes (seq);
create index if not exists ix_fluxo_transicoes_evento on public.fluxo_transicoes (event_id, seq desc);

-- ---------------------------------------------------------------------------------
-- 7) pre_release_versoes — o artefato: imutável, uma linha por versão, sempre NÃO PUBLICADO, presa a UMA liberação
-- ---------------------------------------------------------------------------------
create table if not exists public.pre_release_versoes (
  id                 uuid primary key default gen_random_uuid(),
  event_id           uuid not null references public.events(id),
  empresa_id         uuid not null,
  versao             int  not null,
  versao_anterior_id uuid references public.pre_release_versoes(id),
  dossie_versao_id   uuid not null references public.dossie_versoes(id),
  hash_dossie        text not null,
  liberacao_id       uuid not null unique references public.fluxo_transicoes(id),   -- uma liberação = no máximo uma versão
  execucao_api_id    uuid not null references public.api_execucoes(id),             -- chamada paga (operacao = 'pre_release')
  modo_analise       text not null check (modo_analise in ('completa', 'delta')),
  texto              jsonb not null,                                                -- {secoes:[...], hipoteses:[...], contraditorio_processual:..., contato_jornalistico_atual:..., ...}
  texto_hash         text,
  validacao          jsonb not null default '{}'::jsonb,                            -- {regras:[...], bloqueantes:[...], alertas:[...]}
  status_validacao   text not null default 'aprovada' check (status_validacao in ('aprovada', 'reprovada')),
  publicacao_estado  text not null default 'NAO_PUBLICADO' check (publicacao_estado = 'NAO_PUBLICADO'),
  prompt_versao      text,
  modelo             text,
  gerado_por         uuid,
  created_at         timestamptz not null default clock_timestamp(),
  unique (event_id, versao)
);
create index if not exists ix_pre_release_versoes_evento on public.pre_release_versoes (event_id, versao desc);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'fk_fluxo_transicoes_pre_release_versao') then
    alter table public.fluxo_transicoes
      add constraint fk_fluxo_transicoes_pre_release_versao foreign key (pre_release_versao_id)
      references public.pre_release_versoes(id);
  end if;
end $$;

-- ---------------------------------------------------------------------------------
-- 8) Regras de bloqueio (código, sem IA): G1–G4 impedem liberar/gerar; B1–B5 impedem aprovar/publicar
-- ---------------------------------------------------------------------------------
create or replace function public.fluxo_bloqueios_geracao(p_dossie uuid, p_rev jsonb) returns jsonb
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare d record; r jsonb := '[]'::jsonb;
begin
  select matriz, alertas into d from public.dossie_versoes where id = p_dossie;
  if not found then raise exception 'dossie_inexistente'; end if;
  p_rev := coalesce(p_rev, '{}'::jsonb);
  -- G1 fonte primária não localizada ou ilegível
  if (p_rev->>'fonte_primaria') is distinct from 'localizada_e_legivel'
     or exists (select 1 from jsonb_array_elements(d.matriz) i
                 where coalesce((i->>'fonte_primaria')::boolean, false) and (i->>'estado') is distinct from 'confirmado') then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'G1', 'motivo', 'fonte primaria nao localizada ou ilegivel'));
  end if;
  -- G2 identidade incerta do evento
  if (p_rev->>'identidade_evento') is distinct from 'confirmada' or coalesce((d.alertas->>'chaves_conflitantes')::boolean, false) then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'G2', 'motivo', 'identidade do evento incerta'));
  end if;
  -- G3 dúvida entre pedido e ato efetivado
  if not (coalesce(p_rev->>'natureza_ato', '') = any (array['pedido', 'ato_efetivado', 'nao_se_aplica']))
     or coalesce((d.alertas->>'pedido_ato_ambiguo')::boolean, false) then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'G3', 'motivo', 'duvida entre pedido e ato efetivado'));
  end if;
  -- G4 risco de duplicidade
  if (p_rev->>'duplicidade') is distinct from 'nao' or coalesce((d.alertas->>'duplicidade_nao_resolvida')::boolean, false) then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'G4', 'motivo', 'risco de duplicidade'));
  end if;
  return r;
end $$;

create or replace function public.fluxo_pendencias_publicacao(p_versao uuid) returns jsonb
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare v record; d record; lib jsonb; r jsonb := '[]'::jsonb; g jsonb; it jsonb; est text; cls text;
begin
  select * into v from public.pre_release_versoes where id = p_versao;
  if not found then raise exception 'versao_inexistente'; end if;
  select * into d from public.dossie_versoes where id = v.dossie_versao_id;
  select t.payload into lib from public.fluxo_transicoes t where t.id = v.liberacao_id;
  -- B1 qualquer regra de bloqueio da geração ainda ativa
  g := public.fluxo_bloqueios_geracao(v.dossie_versao_id, lib);
  if jsonb_array_length(g) > 0 then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'B1', 'detalhe', g));
  end if;
  -- B2 lacuna de classe bloqueante (e aguardando_contraditorio com risco reputacional ou sem avaliação de risco)
  for it in select * from jsonb_array_elements(d.matriz) loop
    est := it->>'estado'; cls := it->>'classe_impacto';
    if est not in ('confirmado', 'nao_aplicavel') and cls <> 'PERIFERICA' then
      r := r || jsonb_build_array(jsonb_build_object('regra', 'B2', 'codigo', it->>'codigo', 'estado', est, 'classe_impacto', cls));
    elsif est = 'aguardando_contraditorio' and coalesce((it->>'risco_reputacional')::boolean, true) then
      r := r || jsonb_build_array(jsonb_build_object('regra', 'B2', 'codigo', it->>'codigo', 'estado', est, 'motivo', 'risco reputacional'));
    end if;
  end loop;
  -- B3 validação com trava bloqueante
  if v.status_validacao = 'reprovada' then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'B3', 'detalhe', v.validacao->'bloqueantes'));
  end if;
  -- B4 dossiê ou versão não é mais a vigente
  if exists (select 1 from public.dossie_versoes x where x.event_id = v.event_id and x.versao > d.versao)
     or exists (select 1 from public.pre_release_versoes x where x.event_id = v.event_id and x.versao > v.versao) then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'B4', 'motivo', 'dossie ou versao nao e mais a vigente'));
  end if;
  -- B5 mudança material do caso depois da geração
  if exists (select 1 from public.monitoramento_verificacoes m
              where m.event_id = v.event_id and m.resultado = 'mudanca_material' and m.criado_em > v.created_at)
     or public.fluxo_estado(v.event_id) in ('ATUALIZADO', 'REVISAO_MUDANCA') then
    r := r || jsonb_build_array(jsonb_build_object('regra', 'B5', 'motivo', 'mudanca material depois da geracao'));
  end if;
  return r;
end $$;

-- ---------------------------------------------------------------------------------
-- 9) Máquina de estados (a ÚNICA tabela de transições permitidas) e o gatilho que a impõe
-- ---------------------------------------------------------------------------------
create or replace function public.fluxo_estado(p_event uuid) returns text
language sql stable security definer set search_path = public, pg_catalog as $$
  select coalesce((select t.para from public.fluxo_transicoes t where t.event_id = p_event order by t.seq desc limit 1), 'SEM_FLUXO');
$$;

create or replace function app_private.fluxo_regras() returns table (acao text, de text, para text)
language sql immutable as $$
  select * from (values
    ('COLETOR_SELECIONAR',        'SEM_FLUXO',                 'REVISAO_SELECAO'),
    ('INCLUIR_MANUAL',            'SEM_FLUXO',                 'REVISAO_SELECAO'),
    ('COLETOR_ATUALIZAR',         'SEM_FLUXO',                 'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'MONITORADO',                'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'IA_LIBERADA',               'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'IA_EXECUTADA',              'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'REVISAO_ANALISE_IA',        'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'PRE_RELEASE_LIBERADO',      'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'PRE_RELEASE_GERADO',        'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'REVISAO_FINAL',             'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'DEVOLVIDO_PARA_AJUSTE',     'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'APROVADO_PARA_PUBLICACAO',  'ATUALIZADO'),
    ('COLETOR_ATUALIZAR',         'PUBLICADO',                 'ATUALIZADO'),
    ('APROVAR_PARA_IA',           'REVISAO_SELECAO',           'PRONTO_PARA_IA'),
    ('MONITORAR_SELECAO',         'REVISAO_SELECAO',           'MONITORADO'),
    ('DESCARTAR',                 'REVISAO_SELECAO',           'DESCARTADO'),
    ('LIBERAR_IA',                'PRONTO_PARA_IA',            'IA_LIBERADA'),
    ('RETIRAR_LIBERACAO_IA',      'IA_LIBERADA',               'PRONTO_PARA_IA'),
    ('EXECUTAR_IA',               'IA_LIBERADA',               'IA_EXECUTADA'),
    ('ABRIR_REVISAO_ANALISE',     'IA_EXECUTADA',              'REVISAO_ANALISE_IA'),
    ('APURACAO_REGISTRADA',       'REVISAO_ANALISE_IA',        'REVISAO_ANALISE_IA'),
    ('LIBERAR_PRE_RELEASE',       'REVISAO_ANALISE_IA',        'PRE_RELEASE_LIBERADO'),
    ('DEVOLVER_ANALISE',          'REVISAO_ANALISE_IA',        'DEVOLVIDO_PARA_AJUSTE'),
    ('DESCARTAR_OU_MONITORAR',    'REVISAO_ANALISE_IA',        'DESCARTADO'),
    ('DESCARTAR_OU_MONITORAR',    'REVISAO_ANALISE_IA',        'MONITORADO'),
    ('RETIRAR_LIBERACAO_PRE_RELEASE', 'PRE_RELEASE_LIBERADO',  'REVISAO_ANALISE_IA'),
    ('GERAR_PRE_RELEASE',         'PRE_RELEASE_LIBERADO',      'PRE_RELEASE_GERADO'),
    ('ABRIR_REVISAO_FINAL',       'PRE_RELEASE_GERADO',        'REVISAO_FINAL'),
    ('DEVOLVER_REPROVADA',        'PRE_RELEASE_GERADO',        'DEVOLVIDO_PARA_AJUSTE'),
    ('APROVAR',                   'REVISAO_FINAL',             'APROVADO_PARA_PUBLICACAO'),
    ('DEVOLVER_FINAL',            'REVISAO_FINAL',             'DEVOLVIDO_PARA_AJUSTE'),
    ('PUBLICAR',                  'APROVADO_PARA_PUBLICACAO',  'PUBLICADO'),
    ('REVOGAR_APROVACAO',         'APROVADO_PARA_PUBLICACAO',  'DEVOLVIDO_PARA_AJUSTE'),
    ('REABRIR',                   'DEVOLVIDO_PARA_AJUSTE',     'REVISAO_ANALISE_IA'),
    ('REABRIR_NOVA_ANALISE',      'DEVOLVIDO_PARA_AJUSTE',     'PRONTO_PARA_IA'),
    ('ABRIR_REVISAO_MUDANCA',     'ATUALIZADO',                'REVISAO_MUDANCA'),
    ('APROVAR_NOVA_ANALISE',      'REVISAO_MUDANCA',           'PRONTO_PARA_IA'),
    ('MANTER_MONITORADO',         'REVISAO_MUDANCA',           'MONITORADO'),
    ('DESCARTAR',                 'REVISAO_MUDANCA',           'DESCARTADO'),
    ('REABRIR_DESCARTADO',        'DESCARTADO',                'REVISAO_SELECAO')
  ) v(acao, de, para)
$$;

create or replace function app_private.fluxo_transicao_antes_insert() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
declare
  ev record; v_atual text; v_ult record; d record; pv record; lote record; v_g jsonb; v_pend jsonb;
  v_lote uuid; v_n int; v_uuid uuid; v_dossie uuid; v_ex uuid; v_ex_rec record;
begin
  perform app_private.fluxo_exige_ativo();
  select id, empresa_id into ev from public.events where id = new.event_id;
  if not found then raise exception 'evento_inexistente'; end if;
  new.empresa_id := ev.empresa_id;
  perform pg_advisory_xact_lock(hashtextextended('fluxo|' || new.event_id::text, 0));

  v_atual := public.fluxo_estado(new.event_id);
  if new.de is distinct from v_atual then
    raise exception 'estado_divergente: o caso esta em %, nao em %', v_atual, new.de;
  end if;
  if not exists (select 1 from app_private.fluxo_regras() r where r.acao = new.acao and r.de = new.de and r.para = new.para) then
    raise exception 'transicao_proibida: % de % para %', new.acao, new.de, new.para;
  end if;
  if new.acao not like 'COLETOR\_%' and new.usuario_id is null then raise exception 'usuario_obrigatorio'; end if;
  if new.acao in ('DESCARTAR','DEVOLVER_ANALISE','DESCARTAR_OU_MONITORAR','DEVOLVER_REPROVADA','DEVOLVER_FINAL','REVOGAR_APROVACAO',
                  'MANTER_MONITORADO','REABRIR_DESCARTADO','INCLUIR_MANUAL')
     and trim(coalesce(new.motivo, '')) = '' then
    raise exception 'motivo_obrigatorio: %', new.acao;
  end if;

  if new.dossie_versao_id is null and new.payload ? 'dossie_versao_id' then
    new.dossie_versao_id := (new.payload->>'dossie_versao_id')::uuid;
  end if;
  if new.pre_release_versao_id is null and new.payload ? 'pre_release_versao_id' then
    new.pre_release_versao_id := (new.payload->>'pre_release_versao_id')::uuid;
  end if;

  -- ---- seleção (teto da rodada; ranking congelado) ----
  if new.acao in ('COLETOR_SELECIONAR', 'INCLUIR_MANUAL') then
    v_lote := (new.payload->>'lote_id')::uuid;
    select * into lote from public.selecao_lotes where id = v_lote;
    if not found then raise exception 'lote_inexistente'; end if;
    if new.acao = 'COLETOR_SELECIONAR' and not exists (
         select 1 from jsonb_array_elements(lote.itens) i where (i->>'event_id') = new.event_id::text) then
      raise exception 'caso_fora_do_ranking_do_lote';
    end if;
    if new.acao = 'INCLUIR_MANUAL' and coalesce(new.payload->>'origem', '') <> 'SELECAO_MANUAL' then
      raise exception 'inclusao_manual_exige_origem_SELECAO_MANUAL';
    end if;
    -- teto por rodada: ranking do lote + inclusões manuais nunca passam de teto
    select count(*) into v_n from public.fluxo_transicoes t
     where t.acao = 'INCLUIR_MANUAL' and t.payload->>'lote_id' = v_lote::text;
    if new.acao = 'INCLUIR_MANUAL' and (jsonb_array_length(lote.itens) + v_n) >= lote.teto then
      raise exception 'teto_da_rodada_atingido: lote % tem teto %', v_lote, lote.teto;
    end if;
  end if;

  -- ---- execução da IA ----
  if new.acao = 'EXECUTAR_IA' then
    v_ex := (new.payload->>'execucao_ia_id')::uuid;
    select event_id, operacao, status into v_ex_rec from public.api_execucoes where id = v_ex;
    if not found or v_ex_rec.event_id is distinct from new.event_id or v_ex_rec.operacao <> 'analise_editorial' or v_ex_rec.status <> 'sucesso' then
      raise exception 'execucao_ia_invalida: precisa ser uma analise_editorial com sucesso deste evento';
    end if;
  end if;

  -- ---- abrir a revisão da análise: dossiê montado e preso à execução ----
  if new.acao = 'ABRIR_REVISAO_ANALISE' then
    select * into d from public.dossie_versoes where id = new.dossie_versao_id;
    if not found or d.event_id <> new.event_id then raise exception 'dossie_invalido_para_a_revisao'; end if;
    select (t.payload->>'execucao_ia_id')::uuid into v_ex from public.fluxo_transicoes t
     where t.event_id = new.event_id and t.acao = 'EXECUTAR_IA' order by t.seq desc limit 1;
    if d.execucao_ia_id is distinct from v_ex then raise exception 'dossie_nao_pertence_a_ultima_execucao_de_ia'; end if;
  end if;

  if new.acao = 'REABRIR' then
    if not exists (select 1 from public.fluxo_transicoes t where t.event_id = new.event_id and t.para = 'DEVOLVIDO_PARA_AJUSTE'
                      and t.seq = (select max(seq) from public.fluxo_transicoes where event_id = new.event_id)
                      and t.payload->>'origem_devolucao' = 'FINAL') then
      raise exception 'reabrir_sem_nova_ia_so_para_devolucao_de_origem_FINAL';
    end if;
  end if;

  if new.acao in ('DEVOLVER_ANALISE') and coalesce(new.payload->>'ajuste_pedido', '') = '' then
    raise exception 'ajuste_pedido_obrigatorio';
  end if;
  if new.acao in ('DEVOLVER_ANALISE', 'DEVOLVER_REPROVADA', 'DEVOLVER_FINAL', 'REVOGAR_APROVACAO')
     and coalesce(new.payload->>'origem_devolucao', '') not in ('ANALISE', 'FINAL') then
    raise exception 'origem_devolucao_obrigatoria (ANALISE ou FINAL)';
  end if;
  if new.acao = 'DEVOLVER_ANALISE' and new.payload->>'origem_devolucao' <> 'ANALISE' then raise exception 'origem_devolucao_incoerente'; end if;
  if new.acao in ('DEVOLVER_REPROVADA', 'DEVOLVER_FINAL', 'REVOGAR_APROVACAO') and new.payload->>'origem_devolucao' <> 'FINAL' then
    raise exception 'origem_devolucao_incoerente';
  end if;

  if new.acao = 'DESCARTAR_OU_MONITORAR' and new.para not in ('DESCARTADO', 'MONITORADO') then raise exception 'destino_invalido'; end if;

  -- ---- apuração humana: fecha item da matriz com fonte e justificativa (exige novo dossiê antes de liberar) ----
  if new.acao = 'APURACAO_REGISTRADA' then
    if coalesce(trim(new.payload->>'item'), '') = '' or coalesce(trim(new.payload->>'fonte'), '') = ''
       or coalesce(trim(new.payload->>'justificativa'), '') = '' then
      raise exception 'apuracao_exige_item_fonte_e_justificativa';
    end if;
  end if;

  -- ---- LIBERAR o pré-release (só autoriza) ----
  if new.acao = 'LIBERAR_PRE_RELEASE' then
    select * into d from public.dossie_versoes where id = new.dossie_versao_id;
    if not found or d.event_id <> new.event_id then raise exception 'liberacao_exige_dossie_do_caso'; end if;
    if d.hash is distinct from (new.payload->>'hash_dossie') then raise exception 'liberacao_hash_dossie_diverge'; end if;
    if d.versao <> (select max(versao) from public.dossie_versoes where event_id = new.event_id) then
      raise exception 'liberacao_exige_o_dossie_mais_recente';
    end if;
    if exists (select 1 from public.fluxo_transicoes a where a.event_id = new.event_id and a.acao = 'APURACAO_REGISTRADA' and a.created_at > d.criado_em) then
      raise exception 'liberacao_exige_novo_dossie_depois_da_apuracao';
    end if;
    if (new.payload->>'conferencia') is distinct from 'true' then raise exception 'conferencia_obrigatoria'; end if;
    if d.modo_analise = 'delta' and coalesce((new.payload->>'contradiz_analise_anterior')::boolean, false) then
      raise exception 'contradiz_analise_anterior: a analise delta contradiz a anterior; so e possivel devolver para analise completa ou descartar';
    end if;
    v_g := public.fluxo_bloqueios_geracao(new.dossie_versao_id, new.payload);
    if jsonb_array_length(v_g) > 0 then
      raise exception 'geracao_bloqueada: %', (select string_agg(x->>'regra', ',') from jsonb_array_elements(v_g) x);
    end if;
  end if;

  -- ---- GERAR: precisa de uma versão presa à liberação que é a ÚLTIMA transição do caso ----
  if new.acao = 'GERAR_PRE_RELEASE' then
    select * into pv from public.pre_release_versoes where id = new.pre_release_versao_id;
    if not found or pv.event_id <> new.event_id then raise exception 'geracao_exige_versao_do_caso'; end if;
    select id, para into v_ult from public.fluxo_transicoes where event_id = new.event_id order by seq desc limit 1;
    if v_ult.para <> 'PRE_RELEASE_LIBERADO' or pv.liberacao_id <> v_ult.id then raise exception 'geracao_sem_liberacao_valida'; end if;
    new.dossie_versao_id := pv.dossie_versao_id;
  end if;

  -- ---- revisão final ----
  if new.acao = 'ABRIR_REVISAO_FINAL' then
    select * into pv from public.pre_release_versoes where id = new.pre_release_versao_id;
    if not found or pv.event_id <> new.event_id then raise exception 'revisao_final_exige_versao_do_caso'; end if;
    if pv.versao <> (select max(versao) from public.pre_release_versoes where event_id = new.event_id) then raise exception 'revisao_final_exige_a_versao_mais_recente'; end if;
    if pv.status_validacao <> 'aprovada' then raise exception 'versao_reprovada_na_validacao_nao_vai_a_revisao_final'; end if;
  end if;

  -- ---- aprovar: nenhuma pendência bloqueadora de publicação ----
  if new.acao = 'APROVAR' then
    select * into pv from public.pre_release_versoes where id = new.pre_release_versao_id;
    if not found or pv.event_id <> new.event_id then raise exception 'aprovacao_exige_versao_do_caso'; end if;
    if (new.payload->>'conferencia_final') is distinct from 'true' then raise exception 'conferencia_final_obrigatoria'; end if;
    if (new.payload->>'hash_pre_release') is distinct from pv.texto_hash then raise exception 'aprovacao_hash_pre_release_diverge'; end if;
    v_pend := public.fluxo_pendencias_publicacao(pv.id);
    if jsonb_array_length(v_pend) > 0 then
      raise exception 'publicacao_bloqueada: %', (select string_agg(distinct x->>'regra', ',') from jsonb_array_elements(v_pend) x);
    end if;
  end if;

  -- ---- publicar: ação separada, regras reaplicadas, confirmação própria ----
  if new.acao = 'PUBLICAR' then
    select (t.payload->>'pre_release_versao_id')::uuid into v_uuid from public.fluxo_transicoes t
     where t.event_id = new.event_id and t.acao = 'APROVAR' order by t.seq desc limit 1;
    if v_uuid is null or new.pre_release_versao_id is distinct from v_uuid then raise exception 'publicar_exige_a_versao_aprovada'; end if;
    if (new.payload->>'confirmacao') is distinct from 'true' then raise exception 'confirmacao_de_publicacao_obrigatoria'; end if;
    v_pend := public.fluxo_pendencias_publicacao(v_uuid);
    if jsonb_array_length(v_pend) > 0 then
      raise exception 'publicacao_bloqueada: %', (select string_agg(distinct x->>'regra', ',') from jsonb_array_elements(v_pend) x);
    end if;
  end if;

  -- ---- mudança de caso: modo da nova análise e devolução ao ciclo ----
  if new.acao = 'APROVAR_NOVA_ANALISE' and coalesce(new.payload->>'modo_analise', '') not in ('delta', 'completa') then
    raise exception 'modo_analise_obrigatorio (delta ou completa)';
  end if;
  return new;
end $$;

drop trigger if exists trg_fluxo_transicao_antes_insert on public.fluxo_transicoes;
create trigger trg_fluxo_transicao_antes_insert before insert on public.fluxo_transicoes
  for each row execute function app_private.fluxo_transicao_antes_insert();

-- guarda da versão do pré-release: só entra com liberação válida e não consumida, hash igual, sem bloqueio de geração
create or replace function app_private.pre_release_antes_insert() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
declare ev record; d record; v_ult record; v_ant record; g jsonb; v_hash text;
begin
  perform app_private.fluxo_exige_ativo();
  select id, empresa_id into ev from public.events where id = new.event_id;
  if not found then raise exception 'evento_inexistente'; end if;
  new.empresa_id := ev.empresa_id;
  perform pg_advisory_xact_lock(hashtextextended('fluxo|' || new.event_id::text, 0));

  select id, para, payload, dossie_versao_id into v_ult from public.fluxo_transicoes where event_id = new.event_id order by seq desc limit 1;
  if v_ult.id is null or v_ult.para <> 'PRE_RELEASE_LIBERADO' or v_ult.id <> new.liberacao_id then
    raise exception 'geracao_sem_liberacao_valida';
  end if;
  select * into d from public.dossie_versoes where id = new.dossie_versao_id;
  if not found or d.event_id <> new.event_id or v_ult.dossie_versao_id is distinct from new.dossie_versao_id then
    raise exception 'versao_exige_o_dossie_liberado';
  end if;
  if d.hash <> (v_ult.payload->>'hash_dossie') then raise exception 'liberacao_hash_dossie_diverge'; end if;
  new.hash_dossie := d.hash;
  new.modo_analise := d.modo_analise;
  g := public.fluxo_bloqueios_geracao(new.dossie_versao_id, v_ult.payload);
  if jsonb_array_length(g) > 0 then
    raise exception 'geracao_bloqueada: %', (select string_agg(x->>'regra', ',') from jsonb_array_elements(g) x);
  end if;
  if not exists (select 1 from public.api_execucoes a where a.id = new.execucao_api_id and a.event_id = new.event_id and a.operacao = 'pre_release') then
    raise exception 'execucao_api_invalida: precisa ser uma chamada pre_release deste evento';
  end if;
  if new.texto is null or jsonb_typeof(new.texto) <> 'object' or jsonb_typeof(new.texto->'secoes') is distinct from 'array' then
    raise exception 'texto_invalido: precisa de {secoes:[...]}';
  end if;
  select id, versao into v_ant from public.pre_release_versoes where event_id = new.event_id order by versao desc limit 1;
  new.versao := coalesce(v_ant.versao, 0) + 1;
  new.versao_anterior_id := v_ant.id;
  new.texto_hash := encode(sha256(convert_to(new.texto::text, 'UTF8')), 'hex');
  new.status_validacao := case when coalesce(jsonb_array_length(new.validacao->'bloqueantes'), 0) > 0 then 'reprovada' else 'aprovada' end;
  new.publicacao_estado := 'NAO_PUBLICADO';
  return new;
end $$;
drop trigger if exists trg_pre_release_antes_insert on public.pre_release_versoes;
create trigger trg_pre_release_antes_insert before insert on public.pre_release_versoes
  for each row execute function app_private.pre_release_antes_insert();

-- imutabilidade das tabelas de registro
do $$
declare t text;
begin
  foreach t in array array['fluxo_transicoes', 'dossie_versoes', 'pre_release_versoes', 'selecao_lotes', 'monitoramento_verificacoes']
  loop
    execute format('drop trigger if exists trg_%s_imutavel on public.%I', t, t);
    execute format('create trigger trg_%s_imutavel before update or delete on public.%I for each row execute function app_private.fluxo_imutavel()', t, t);
    execute format('drop trigger if exists trg_%s_sem_truncate on public.%I', t, t);
    execute format('create trigger trg_%s_sem_truncate before truncate on public.%I for each statement execute function app_private.fluxo_imutavel()', t, t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------------
-- 10) RPCs do servidor (só service_role): registrar transição e gerar pré-release de forma atômica
-- ---------------------------------------------------------------------------------
create or replace function public.fluxo_registrar(p_event uuid, p_acao text, p_para text, p_usuario uuid, p_motivo text, p_payload jsonb)
returns uuid
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_id uuid;
begin
  insert into public.fluxo_transicoes (event_id, empresa_id, de, acao, para, usuario_id, motivo, payload)
  values (p_event, '00000000-0000-0000-0000-000000000000', public.fluxo_estado(p_event), p_acao, p_para, p_usuario, p_motivo,
          coalesce(p_payload, '{}'::jsonb))
  returning id into v_id;
  return v_id;
end $$;

create or replace function public.fluxo_gerar_pre_release(
  p_event uuid, p_usuario uuid, p_dossie uuid, p_execucao_api uuid, p_texto jsonb, p_validacao jsonb,
  p_prompt_versao text, p_modelo text) returns jsonb
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_lib uuid; v_ver uuid; v_tr uuid; v_status text;
begin
  select t.id into v_lib from public.fluxo_transicoes t where t.event_id = p_event order by t.seq desc limit 1;
  insert into public.pre_release_versoes (event_id, empresa_id, versao, dossie_versao_id, hash_dossie, liberacao_id, execucao_api_id,
                                           modo_analise, texto, validacao, prompt_versao, modelo, gerado_por)
  values (p_event, '00000000-0000-0000-0000-000000000000', 0, p_dossie, '', v_lib, p_execucao_api,
          'completa', p_texto, coalesce(p_validacao, '{}'::jsonb), p_prompt_versao, p_modelo, p_usuario)
  returning id, status_validacao into v_ver, v_status;
  insert into public.fluxo_transicoes (event_id, empresa_id, de, acao, para, usuario_id, payload, pre_release_versao_id)
  values (p_event, '00000000-0000-0000-0000-000000000000', 'PRE_RELEASE_LIBERADO', 'GERAR_PRE_RELEASE', 'PRE_RELEASE_GERADO',
          p_usuario, jsonb_build_object('pre_release_versao_id', v_ver), v_ver)
  returning id into v_tr;
  return jsonb_build_object('pre_release_versao_id', v_ver, 'transicao_id', v_tr, 'status_validacao', v_status);
end $$;

-- ---------------------------------------------------------------------------------
-- 11) Leitura segura para o editor: só estado e data (sem payload, motivo nem texto)
-- ---------------------------------------------------------------------------------
create or replace view public.v_caso_fluxo_estado with (security_invoker = true) as
select distinct on (t.event_id) t.event_id, t.para as estado, t.acao as ultima_acao, t.created_at as desde
  from public.fluxo_transicoes t
 order by t.event_id, t.seq desc;

create or replace view public.v_caso_ultima_atualizacao with (security_invoker = true) as
select m.event_id, max(m.data_real_atualizacao) as ultima_atualizacao
  from public.monitoramento_verificacoes m
 where m.resultado = 'mudanca_material'
 group by m.event_id;

-- ---------------------------------------------------------------------------------
-- 12) RLS e grants: nada para anon; service_role grava (sem update/delete); authenticated só lê colunas seguras
-- ---------------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['pre_release_parametros', 'selecao_lotes', 'monitoramento_verificacoes', 'dossie_versoes',
                           'fluxo_transicoes', 'pre_release_versoes']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from public, anon, authenticated', t);
  end loop;
end $$;

grant select, insert on public.selecao_lotes, public.monitoramento_verificacoes, public.dossie_versoes,
                        public.fluxo_transicoes, public.pre_release_versoes to service_role;
grant select, insert, update (vigente) on public.pre_release_parametros to service_role;

drop policy if exists fluxo_transicoes_leitura_segura on public.fluxo_transicoes;
create policy fluxo_transicoes_leitura_segura on public.fluxo_transicoes
  for select to authenticated using (exists (select 1 from public.events e where e.id = fluxo_transicoes.event_id));
drop policy if exists monitoramento_leitura_segura on public.monitoramento_verificacoes;
create policy monitoramento_leitura_segura on public.monitoramento_verificacoes
  for select to authenticated using (exists (select 1 from public.events e where e.id = monitoramento_verificacoes.event_id));

grant select (id, seq, event_id, empresa_id, de, acao, para, created_at) on public.fluxo_transicoes to authenticated;
grant select (id, event_id, empresa_id, resultado, data_real_atualizacao, data_real_origem, criado_em) on public.monitoramento_verificacoes to authenticated;
grant select on public.v_caso_fluxo_estado, public.v_caso_ultima_atualizacao to authenticated, service_role;

revoke all on function public.fluxo_estado(uuid) from public, anon, authenticated;
revoke all on function public.fluxo_bloqueios_geracao(uuid, jsonb) from public, anon, authenticated;
revoke all on function public.fluxo_pendencias_publicacao(uuid) from public, anon, authenticated;
revoke all on function public.fluxo_registrar(uuid, text, text, uuid, text, jsonb) from public, anon, authenticated;
revoke all on function public.fluxo_gerar_pre_release(uuid, uuid, uuid, uuid, jsonb, jsonb, text, text) from public, anon, authenticated;
revoke all on function public.pre_release_definir_fluxo_ativo(boolean, text) from public, anon, authenticated;
grant execute on function public.fluxo_estado(uuid) to service_role;
grant execute on function public.fluxo_bloqueios_geracao(uuid, jsonb) to service_role;
grant execute on function public.fluxo_pendencias_publicacao(uuid) to service_role;
grant execute on function public.fluxo_registrar(uuid, text, text, uuid, text, jsonb) to service_role;
grant execute on function public.fluxo_gerar_pre_release(uuid, uuid, uuid, uuid, jsonb, jsonb, text, text) to service_role;
grant execute on function public.pre_release_definir_fluxo_ativo(boolean, text) to service_role;
-- só as funções NOVAS de app_private (nunca "all functions in schema": isso tocaria funções que já existem em produção)
revoke all on function app_private.fluxo_ativo() from public, anon, authenticated;
revoke all on function app_private.fluxo_exige_ativo() from public, anon, authenticated;
revoke all on function app_private.fluxo_imutavel() from public, anon, authenticated;
revoke all on function app_private.fluxo_parametros_guarda() from public, anon, authenticated;
revoke all on function app_private.selecao_lote_antes_insert() from public, anon, authenticated;
revoke all on function app_private.monitoramento_antes_insert() from public, anon, authenticated;
revoke all on function app_private.fluxo_validar_matriz(uuid, jsonb) from public, anon, authenticated;
revoke all on function app_private.fluxo_validar_afirmacoes(uuid, jsonb) from public, anon, authenticated;
revoke all on function app_private.dossie_antes_insert() from public, anon, authenticated;
revoke all on function app_private.fluxo_regras() from public, anon, authenticated;
revoke all on function app_private.fluxo_transicao_antes_insert() from public, anon, authenticated;
revoke all on function app_private.pre_release_antes_insert() from public, anon, authenticated;

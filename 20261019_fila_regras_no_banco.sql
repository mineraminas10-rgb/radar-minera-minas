-- =====================================================================================
-- FILA EDITORIAL — TODAS AS REGRAS NO BANCO + APLICAR O RASCUNHO DA IA COMO PRÉ-RELEASE   (NÃO APLICADA)
-- Motivo: as regras (prioridade A/B/C/D, ineditismo, atualidade, ordem da fila, bloqueios, elegibilidade) estavam escritas no
-- index.html. Aqui elas passam a viver SÓ no banco; a interface apenas exibe o que estas funções devolvem.
--   * public.fila_parametros          — limiares versionados (corte 40, B=60, A=80, janela 90 dias, níveis de gatilho forte,
--                                       rótulos e textos). Mudar regra = nova linha vigente, nunca editar o index.
--   * public.fila_item(event)         — um evento completo: score decisório, situação, criticidade, ineditismo, atualidade,
--                                       prioridade editorial A/B/C/D + motivo, bloqueios de avanço.
--   * public.fila_editorial(empresa)  — a fila inteira, já ORDENADA (campo "ordem").
--   * public.fila_bloqueios_*         — o que impede avançar (a mesma função alimenta a interface E a trava do banco).
--   * public.fila_pode_gerar_pre_release(event) — o banco diz se a IA pode gerar pré-release para o evento (o servidor consulta).
--   * public.fila_rascunho_pre_release / fila_aplicar_rascunho_pre_release — o rascunho que a IA já gerou (api_execucoes)
--     passa a poder virar events.pre_release, SOMENTE por clique de um usuário com permissão 'editorial'.
-- NADA roda sozinho: não chama IA, não gera pré-release, não publica, não agenda, não apaga nem reescreve dado existente.
-- NÃO altera event_scores.prioridade (histórico CRIT). Só LÊ events/event_scores/evidencias/documentos; a ÚNICA escrita em
--   tabela existente é events.pre_release, dentro de fila_aplicar_rascunho_pre_release (por clique, com log append-only).
-- DEPENDE de: 20261016_fila_editorial_travas.sql (fila_decisao_score, trigger) e 20261017_permissoes_perfil.sql (tem_permissao).
-- Redefine (create or replace) public.fila_decisao_score e app_private.fila_guarda_avanco para lerem os parâmetros/bloqueios
--   daqui — mesma saída. Reverter: 20261019_fila_regras_no_banco_rollback.sql (restaura as versões da 20261016).
-- =====================================================================================

create schema if not exists app_private;

-- 1) Parâmetros versionados (nova versão = nova linha; só uma vigente) -----------------------------------------------
create table if not exists public.fila_parametros (
  versao_parametros text primary key,
  parametros        jsonb not null,
  vigente           boolean not null default false,
  observacao        text,
  criado_em         timestamptz not null default now()
);
create unique index if not exists uq_fila_parametros_vigente on public.fila_parametros ((true)) where vigente;

insert into public.fila_parametros (versao_parametros, parametros, vigente, observacao)
select 'FILA-PARAMS-V1', $json${
 "score_corte": 40,
 "score_b": 60,
 "score_a": 80,
 "janela_atualidade_dias": 90,
 "evidencia_minima": 2,
 "exige_score_para_publicar": false,
 "bloqueia_ia_sem_score": true,
 "prioridades_sem_pre_release": ["D"],
 "niveis_gatilho_forte": ["CRITICO","ALTA","POTENCIAL_CRITICO_PENDENTE_EVIDENCIA","POTENCIAL_ALTA_PENDENTE_EVIDENCIA"],
 "status_com_trava_editorial": ["pronto_para_publicar","publicado","arquivado","descartado"],
 "rank_criticidade": {"CRITICO":6,"POTENCIAL_CRITICO_PENDENTE_EVIDENCIA":5,"ALTA":4,"POTENCIAL_ALTA_PENDENTE_EVIDENCIA":3,"MEDIA":2,"BAIXA":1,"ROTINA":0},
 "rank_prioridade": {"A":4,"B":3,"C":2,"PENDENTE":1,"D":0},
 "rotulos": {"A":"IMEDIATA","B":"ALTA","C":"AVALIAR","D":"BAIXA/FORA","PENDENTE":"PENDENTE"},
 "textos_motivo": {
  "ATUALIZACAO_MATERIAL_CRITICA":"atualização material de impacto crítico",
  "CRITICIDADE_CRITICO":"fato crítico ainda com urgência editorial",
  "SCORE_80_COM_GATILHO_E_EVIDENCIA":"score ≥ 80 com gatilho relevante e evidência suficiente",
  "ATUALIZACAO_MATERIAL_RELEVANTE":"atualização material relevante",
  "FORA_DA_SELECAO":"score decisório < 40, fora da seleção",
  "CRITICIDADE_BAIXA_OU_ROTINA":"criticidade baixa ou de rotina",
  "SCORE_BAIXO_COM_GATILHO_FORTE":"score baixo, mantido por gatilho forte",
  "PENDENTE_DE_SCORE":"sem score: prioridade não rebaixada, aguardando score",
  "SCORE_PROVISORIO":"score provisório: não rebaixa nem eleva, aguardando score homologado",
  "CRITICIDADE_ALTA_COM_SCORE":"criticidade alta com score ≥ 40",
  "SCORE_60_ELEGIVEL_E_ATUAL":"score ≥ 60 em caso elegível e atual",
  "CRITICIDADE_MEDIA_COM_SCORE":"criticidade média com score ≥ 40",
  "SCORE_40_A_59_OU_SEM_ATUALIDADE":"score ≥ 40 sem urgência adicional",
  "SCORE_DECISORIO_MENOR_40":"score decisório < 40",
  "JA_PUBLICADO_SEM_NOVIDADE":"já publicado, sem atualização material"
 }
}$json$::jsonb, true,
 'Valores = regras que a interface já mostrava (index.html). prioridades_sem_pre_release=["D"] é DECISÃO NOVA: a IA não gera pré-release para prioridade D; trocar por [] libera.'
where not exists (select 1 from public.fila_parametros where versao_parametros = 'FILA-PARAMS-V1')
  and not exists (select 1 from public.fila_parametros where vigente);

create or replace function public.fila_parametros_vigentes() returns jsonb
language sql stable security definer set search_path = public, pg_catalog as $$
  select coalesce((select p.parametros from public.fila_parametros p where p.vigente limit 1), '{}'::jsonb)
$$;

-- converte texto em timestamptz sem quebrar (data inválida => null)
create or replace function public.fila_ts_seguro(p text) returns timestamptz
language plpgsql stable set search_path = public, pg_catalog as $$
begin
  if p is null or btrim(p) = '' then return null; end if;
  return p::timestamptz;
exception when others then return null;
end $$;

-- 2) Decisão de score (mesma saída da 20261016; agora lê corte, gatilhos fortes e status com trava dos parâmetros) ------
create or replace function public.fila_decisao_score(p_event_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare
  prm jsonb := public.fila_parametros_vigentes();
  corte numeric := coalesce((prm ->> 'score_corte')::numeric, 40);
  fortes text[] := array(select jsonb_array_elements_text(coalesce(prm -> 'niveis_gatilho_forte',
                     '["CRITICO","ALTA","POTENCIAL_CRITICO_PENDENTE_EVIDENCIA","POTENCIAL_ALTA_PENDENTE_EVIDENCIA"]'::jsonb)));
  trava  text[] := array(select jsonb_array_elements_text(coalesce(prm -> 'status_com_trava_editorial',
                     '["pronto_para_publicar","publicado","arquivado","descartado"]'::jsonb)));
  ev record; sc record; calc numeric; v numeric; decisorio boolean := false; estagio text; motivo text := 'PENDENTE_DE_SCORE';
  crit text; sit text; regra text; mot text;
begin
  select id, status_editorial::text as st into ev from public.events where id = p_event_id;
  if not found then return null; end if;
  select s.score_relevancia, s.score_normalizado, s.score_bruto, s.estagio, s.versao_score, s.componentes into sc
    from public.event_scores s where s.event_id = p_event_id order by s.vigente desc nulls last, s.created_at desc nulls last limit 1;
  if found then
    estagio := sc.estagio; crit := sc.componentes ->> 'criticidade';
    calc := coalesce(sc.score_normalizado, sc.score_bruto);
    if sc.score_relevancia is not null then
      v := sc.score_relevancia; decisorio := true; estagio := coalesce(estagio, 'editorial'); motivo := 'SCORE_RELEVANCIA_EDITORIAL';
    elsif calc is not null and sc.estagio = 'final' then
      v := calc; decisorio := true; estagio := 'final'; motivo := 'SCORE_FINAL_HOMOLOGADO';
    elsif calc is not null then
      v := calc; decisorio := false; estagio := coalesce(estagio, 'preliminar'); motivo := 'SCORE_PRELIMINAR_NAO_DECISORIO';
    end if;
  end if;

  if not decisorio then
    sit := case when v is null then 'PENDENTE_DE_SCORE' else 'SCORE_PROVISORIO' end;
  elsif v >= corte then sit := 'NA_SELECAO';
  elsif crit = any(fortes) then
    sit := 'SCORE_BAIXO_COM_GATILHO_FORTE'; regra := 'SCORE_MENOR_40'; mot := 'SCORE_BAIXO_COM_GATILHO_FORTE';
  elsif ev.st = any(trava) then
    sit := 'FORA_DA_SELECAO_MANTIDO_POR_TRAVA'; regra := 'SCORE_MENOR_40'; mot := 'TRAVA_EDITORIAL_JA_APLICADA';
  else
    sit := 'FORA_DA_SELECAO'; regra := 'SCORE_MENOR_40'; mot := 'DESCARTADO_POR_SCORE';
  end if;

  return jsonb_build_object('event_id', p_event_id, 'score_valor', v, 'score_decisorio', decisorio, 'score_estagio', estagio,
    'score_versao', sc.versao_score, 'score_motivo', motivo, 'criticidade', crit, 'situacao', sit, 'regra', regra, 'motivo', mot);
end $$;

-- 3) O que impede avançar (núcleo único: interface E trava do banco) -------------------------------------------------
create or replace function public.fila_bloqueios_core(p_pre_release text, p_status_atual text, p_revisao text, p_acao text,
                                                      p_decisao jsonb, p_comp jsonb) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare
  prm jsonb := public.fila_parametros_vigentes();
  r jsonb := '[]'::jsonb;
  corte text := coalesce(prm ->> 'score_corte', '40');
begin
  if coalesce(btrim(p_pre_release), '') = '' then r := r || to_jsonb('sem pré-release'::text); end if;
  if p_decisao ->> 'situacao' = 'FORA_DA_SELECAO' then
    r := r || to_jsonb(('score decisório < ' || corte || ' (fora da seleção)')::text);
  end if;
  if coalesce((prm ->> 'exige_score_para_publicar')::boolean, false) and (p_decisao ->> 'score_valor') is null then
    r := r || to_jsonb('PENDENTE_DE_SCORE'::text);
  end if;
  if jsonb_typeof(p_comp -> 'pendencias_bloqueantes') = 'array' and jsonb_array_length(p_comp -> 'pendencias_bloqueantes') > 0 then
    r := r || to_jsonb('pendência editorial bloqueante'::text);
  end if;
  if p_acao = 'publicado' then
    if p_status_atual is distinct from 'pronto_para_publicar' then r := r || to_jsonb('aprove antes (Pronto p/ publicar)'::text); end if;
    if p_revisao = 'Pendente' then r := r || to_jsonb('revisão humana pendente'::text); end if;
  end if;
  return r;
end $$;

create or replace function public.fila_bloqueios_publicacao(p_event_id uuid, p_acao text) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare ev record; comp jsonb;
begin
  select e.pre_release, e.status_editorial::text as st, e.revisao_humana into ev from public.events e where e.id = p_event_id;
  if not found then return null; end if;
  select s.componentes into comp from public.event_scores s where s.event_id = p_event_id
   order by s.vigente desc nulls last, s.created_at desc nulls last limit 1;
  return public.fila_bloqueios_core(ev.pre_release, ev.st, ev.revisao_humana, p_acao, public.fila_decisao_score(p_event_id), coalesce(comp, '{}'::jsonb));
end $$;

-- A IA pode gerar pré-release? (núcleo: usado por fila_item e por fila_pode_gerar_pre_release)
create or replace function public.fila_ia_core(p_sit text, p_cod text, p_mot text, p_prm jsonb) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare m jsonb := '[]'::jsonb;
begin
  if p_sit = 'FORA_DA_SELECAO' then m := m || to_jsonb('FORA_DA_SELECAO'::text); end if;
  if p_sit = 'PENDENTE_DE_SCORE' and coalesce((p_prm ->> 'bloqueia_ia_sem_score')::boolean, true) then m := m || to_jsonb('PENDENTE_DE_SCORE'::text); end if;
  if jsonb_typeof(p_prm -> 'prioridades_sem_pre_release') = 'array' and (p_prm -> 'prioridades_sem_pre_release') ? p_cod then
    m := m || to_jsonb(('PRIORIDADE_' || p_cod)::text);
  end if;
  return jsonb_build_object('pode', jsonb_array_length(m) = 0, 'motivos', m, 'prioridade', p_cod, 'motivo_prioridade', p_mot);
end $$;

-- 4) Um evento da fila, completo ---------------------------------------------------------------------------------------
create or replace function public.fila_item(p_event_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare
  prm jsonb := public.fila_parametros_vigentes();
  corte numeric := coalesce((prm ->> 'score_corte')::numeric, 40);
  lim_b numeric := coalesce((prm ->> 'score_b')::numeric, 60);
  lim_a numeric := coalesce((prm ->> 'score_a')::numeric, 80);
  janela numeric := coalesce((prm ->> 'janela_atualidade_dias')::numeric, 90);
  evid_min int := coalesce((prm ->> 'evidencia_minima')::int, 2);
  fortes text[] := array(select jsonb_array_elements_text(coalesce(prm -> 'niveis_gatilho_forte',
                     '["CRITICO","ALTA","POTENCIAL_CRITICO_PENDENTE_EVIDENCIA","POTENCIAL_ALTA_PENDENTE_EVIDENCIA"]'::jsonb)));
  agora timestamptz := coalesce(nullif(current_setting('radar.agora', true), '')::timestamptz, now());   -- gancho de TESTE
  ev record; d jsonb; comp jsonb;
  crit text; sit text; v_txt text; v_mat timestamptz; v_u timestamptz; atualizado boolean := false;
  qual int; inedito boolean; impacto text; v_s numeric; forte boolean; gat boolean; evsuf boolean; atual boolean; baixa boolean; preserv boolean;
  semnov boolean; japub boolean; compl text; dias numeric;
  cod text; mot text; avs text; txt text; base text;
begin
  select e.id, e.status_editorial::text as st, e.revisao_humana, e.pre_release, e.url_oficial,
         e.data_evento::text as dev, e.data_publicacao::text as dpub, e.created_at into ev
    from public.events e where e.id = p_event_id;
  if not found then return null; end if;
  d := public.fila_decisao_score(p_event_id);
  select s.componentes into comp from public.event_scores s where s.event_id = p_event_id
   order by s.vigente desc nulls last, s.created_at desc nulls last limit 1;
  comp := coalesce(comp, '{}'::jsonb);
  crit := d ->> 'criticidade'; sit := d ->> 'situacao';
  v_s := case when (d ->> 'score_decisorio')::boolean then (d ->> 'score_valor')::numeric else null end;

  -- data material: última atualização material > data do evento/ato > publicação > entrada
  v_txt := coalesce(nullif(comp ->> 'ultima_atualizacao_material', ''), nullif(ev.dev, ''), nullif(ev.dpub, ''), ev.created_at::text);
  v_mat := public.fila_ts_seguro(v_txt);
  v_u := public.fila_ts_seguro(comp ->> 'ultima_atualizacao_material');
  atualizado := v_u is not null and ev.created_at is not null and v_u > ev.created_at;

  select coalesce(sum(case when nullif(v.trecho_literal, '') is not null then 2 else 1 end), 0) into qual
    from public.evidencias v where v.event_id = p_event_id;
  qual := qual + (select count(*) from public.documentos x where x.event_id = p_event_id)::int
               + case when nullif(ev.url_oficial, '') is not null then 1 else 0 end;

  inedito := not (coalesce(ev.st = 'publicado', false) or coalesce(comp -> 'publicado_antes' = 'true'::jsonb, false)
                  or coalesce(comp -> 'ineditismo' = 'false'::jsonb, false));
  impacto := nullif(comp #>> '{atualizacao_material,impacto}', '');
  forte := coalesce(crit = any(fortes), false);
  gat := forte or coalesce(jsonb_typeof(comp -> 'reforcos') = 'array' and jsonb_array_length(comp -> 'reforcos') > 0, false);
  evsuf := case when jsonb_typeof(comp -> 'evidencia_suficiente') = 'boolean' then (comp ->> 'evidencia_suficiente')::boolean else qual >= evid_min end;
  dias := case when v_mat is null then null else extract(epoch from (agora - v_mat)) / 86400 end;
  atual := dias is not null and dias <= janela;
  baixa := coalesce(crit in ('BAIXA', 'ROTINA'), false);
  preserv := sit = 'SCORE_BAIXO_COM_GATILHO_FORTE';
  semnov := impacto is null and not atualizado;
  japub := (not inedito) and semnov;
  compl := case when (not atual) and semnov then 'fato antigo' else null end;

  if impacto = 'critico' then cod := 'A'; mot := 'ATUALIZACAO_MATERIAL_CRITICA';
  elsif japub then cod := 'D'; mot := 'JA_PUBLICADO_SEM_NOVIDADE';
  elsif crit = 'CRITICO' and not preserv then cod := 'A'; mot := 'CRITICIDADE_CRITICO';
  elsif v_s is not null and v_s >= lim_a and gat and evsuf then cod := 'A'; mot := 'SCORE_80_COM_GATILHO_E_EVIDENCIA';
  elsif impacto = 'relevante' then cod := 'B'; mot := 'ATUALIZACAO_MATERIAL_RELEVANTE';
  elsif sit in ('FORA_DA_SELECAO', 'FORA_DA_SELECAO_MANTIDO_POR_TRAVA') then cod := 'D'; mot := 'FORA_DA_SELECAO';
  elsif baixa then cod := 'D'; mot := 'CRITICIDADE_BAIXA_OU_ROTINA';
  elsif preserv then cod := 'C'; mot := 'SCORE_BAIXO_COM_GATILHO_FORTE'; avs := 'Score baixo, mantido por gatilho forte';
  elsif v_s is null then cod := 'PENDENTE'; mot := case when (d ->> 'score_valor') is null then 'PENDENTE_DE_SCORE' else 'SCORE_PROVISORIO' end;
  elsif crit = 'ALTA' and v_s >= corte then cod := 'B'; mot := 'CRITICIDADE_ALTA_COM_SCORE';
  elsif v_s >= lim_b and atual then cod := 'B'; mot := 'SCORE_60_ELEGIVEL_E_ATUAL';
  elsif v_s >= corte then cod := 'C'; mot := case when crit = 'MEDIA' then 'CRITICIDADE_MEDIA_COM_SCORE' else 'SCORE_40_A_59_OU_SEM_ATUALIDADE' end;
  else cod := 'D'; mot := 'SCORE_DECISORIO_MENOR_40';
  end if;

  base := coalesce(prm -> 'textos_motivo' ->> mot, mot);
  if mot = 'JA_PUBLICADO_SEM_NOVIDADE' then
    txt := concat_ws(', ', compl, 'já publicado', 'sem atualização material recente');
  else
    txt := base || case when compl is not null and inedito then ' · fato antigo, mas ainda inédito' else '' end;
  end if;
  if avs is null and compl is not null and inedito and cod in ('A', 'B', 'C') then avs := 'Fato antigo, mas ainda inédito'; end if;

  return jsonb_build_object(
    'event_id', p_event_id,
    'decisao', jsonb_build_object('score_valor', d -> 'score_valor', 'score_decisorio', d -> 'score_decisorio', 'score_estagio', d -> 'score_estagio',
                                  'score_versao', d -> 'score_versao', 'score_motivo', d -> 'score_motivo'),
    'situacao', jsonb_build_object('codigo', sit, 'foraDaSelecao', sit = 'FORA_DA_SELECAO', 'regra', d -> 'regra', 'motivo', d -> 'motivo'),
    'criticidade', crit,
    'atual', jsonb_build_object('material_ts', case when v_mat is null then 0 else (extract(epoch from v_mat) * 1000)::bigint end,
                                'material_texto', v_txt, 'atualizado', atualizado),
    'qualidade_evidencia', qual,
    'ineditismo', jsonb_build_object('inedito', inedito, 'texto', case when inedito then 'Inédito' else 'Já publicado' end),
    'prioridade_editorial', jsonb_build_object('codigo', cod, 'rotulo', coalesce(prm -> 'rotulos' ->> cod, cod), 'motivo', mot, 'texto', txt, 'aviso', avs),
    'rank', jsonb_build_object('prioridade', coalesce((prm -> 'rank_prioridade' ->> cod)::int, -1),
                               'criticidade', coalesce((prm -> 'rank_criticidade' ->> crit)::int, -1)),
    'bloqueios', jsonb_build_object(
        'pronto_para_publicar', public.fila_bloqueios_core(ev.pre_release, ev.st, ev.revisao_humana, 'pronto_para_publicar', d, comp),
        'publicado',            public.fila_bloqueios_core(ev.pre_release, ev.st, ev.revisao_humana, 'publicado', d, comp)),
    'ia', public.fila_ia_core(sit, cod, mot, prm),
    'regras_versao', coalesce((select p.versao_parametros from public.fila_parametros p where p.vigente limit 1), 'SEM_PARAMETROS')
  );
end $$;

-- 5) A fila inteira, já ordenada ---------------------------------------------------------------------------------------
-- Ordem: ATUALIZADO -> prioridade editorial -> criticidade -> data material (mais recente) -> inédito antes de já publicado
--        -> score decisório DESC (provisório/sem score não pontua) -> qualidade da evidência -> id. Cada critério só desempata o anterior.
create or replace function public.fila_editorial(p_empresa uuid) returns jsonb
language sql stable security invoker set search_path = public, pg_catalog as $$
  with itens as (
    select public.fila_item(e.id) as it from public.events e where e.empresa_id = p_empresa
  ), ord as (
    select it, row_number() over (order by
        (it -> 'atual' ->> 'atualizado')::boolean desc,
        (it -> 'rank' ->> 'prioridade')::int desc,
        (it -> 'rank' ->> 'criticidade')::int desc,
        (it -> 'atual' ->> 'material_ts')::bigint desc,
        (it -> 'ineditismo' ->> 'inedito')::boolean desc,
        coalesce((it -> 'decisao' ->> 'score_valor')::numeric * case when (it -> 'decisao' ->> 'score_decisorio')::boolean then 1 else null end, -1e18) desc,
        (it ->> 'qualidade_evidencia')::int desc,
        (it ->> 'event_id') desc) as ordem
      from itens where it is not null
  )
  select coalesce(jsonb_agg(it || jsonb_build_object('ordem', ordem) order by ordem), '[]'::jsonb) from ord
$$;

-- 6) A IA pode gerar pré-release para este evento? (o servidor consulta antes de qualquer chamada paga) ----------------
create or replace function public.fila_pode_gerar_pre_release(p_event_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare it jsonb := public.fila_item(p_event_id);
begin
  if it is null then return jsonb_build_object('pode', false, 'motivos', jsonb_build_array('EVENTO_NAO_ENCONTRADO')); end if;
  return it -> 'ia';
end $$;

-- 7) Rascunho da IA -> pré-release do evento (SÓ por clique; nada automático) --------------------------------------------
create or replace function public.fila_pode_editar_evento(p_event_id uuid) returns boolean
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare uid uuid := auth.uid(); emp uuid;
begin
  if uid is null or not public.tem_permissao('editorial') then return false; end if;
  if public.tem_permissao('todas_empresas') then return exists (select 1 from public.events e where e.id = p_event_id); end if;
  select e.empresa_id into emp from public.events e where e.id = p_event_id;
  return emp is not null and exists (select 1 from public.usuario_empresas ue
                                      where ue.usuario_id = uid and ue.empresa_id = emp and coalesce(ue.ativo, true));
end $$;

create table if not exists public.fila_pre_release_aplicacoes (
  id                  bigint generated always as identity primary key,
  event_id            uuid not null references public.events(id),
  empresa_id          uuid,
  execucao_id         uuid not null,
  usuario_id          uuid not null,
  pre_release_anterior text,
  pre_release_novo    text not null,
  substituiu          boolean not null default false,
  aplicado_em         timestamptz not null default clock_timestamp()
);
create index if not exists fila_pre_release_aplicacoes_event_idx on public.fila_pre_release_aplicacoes (event_id, id desc);
create or replace function app_private.fila_aplicacoes_imutavel() returns trigger language plpgsql set search_path = public, pg_catalog as $$
begin raise exception 'fila_pre_release_aplicacoes é append-only: % não é permitido', tg_op using errcode = 'insufficient_privilege'; end $$;
drop trigger if exists trg_fila_aplicacoes_imutavel on public.fila_pre_release_aplicacoes;
create trigger trg_fila_aplicacoes_imutavel before update or delete on public.fila_pre_release_aplicacoes
  for each row execute function app_private.fila_aplicacoes_imutavel();

-- Último rascunho de pré-release gerado pela IA para o evento (só leitura). Sem permissão 'editorial' sobre o evento: erro.
create or replace function public.fila_rascunho_pre_release(p_event_id uuid) returns jsonb
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare
  prm jsonb := public.fila_parametros_vigentes();
  trava text[] := array(select jsonb_array_elements_text(coalesce(prm -> 'status_com_trava_editorial',
                    '["pronto_para_publicar","publicado","arquivado","descartado"]'::jsonb)));
  a record; ev record; j jsonb; rasc text; bloqueio text; sit text;
begin
  if auth.uid() is null then raise exception 'fila_rascunho_pre_release: sessão obrigatória' using errcode = 'insufficient_privilege'; end if;
  if not public.fila_pode_editar_evento(p_event_id) then
    raise exception 'fila_rascunho_pre_release: sem permissão para este evento' using errcode = 'insufficient_privilege';
  end if;
  select e.pre_release, e.status_editorial::text as st into ev from public.events e where e.id = p_event_id;
  select x.id, x.data_inicio, x.resposta_texto into a from public.api_execucoes x
   where x.event_id = p_event_id and x.operacao = 'analise_editorial' and x.status = 'sucesso'
   order by x.data_inicio desc nulls last limit 1;
  if a.id is null then return jsonb_build_object('execucao_id', null, 'rascunho', null, 'motivo', 'SEM_ANALISE_CONCLUIDA'); end if;
  begin j := a.resposta_texto::jsonb; exception when others then j := null; end;
  rasc := nullif(btrim(j -> 'proposta_abordagem' ->> 'rascunho_pre_release'), '');
  sit := public.fila_decisao_score(p_event_id) ->> 'situacao';
  if ev.st = any(trava) then bloqueio := 'STATUS_JA_DECIDIDO';
  elsif sit = 'FORA_DA_SELECAO' then bloqueio := 'FORA_DA_SELECAO';
  elsif rasc is null then bloqueio := 'ANALISE_SEM_RASCUNHO'; end if;
  return jsonb_build_object('execucao_id', a.id, 'data', a.data_inicio, 'rascunho', rasc,
                            'pre_release_atual', ev.pre_release, 'ja_tem_pre_release', coalesce(btrim(ev.pre_release), '') <> '',
                            'bloqueio', bloqueio, 'pode_aplicar', bloqueio is null);
end $$;

create or replace function public.fila_aplicar_rascunho_pre_release(p_event_id uuid, p_execucao_id uuid, p_substituir boolean default false)
returns jsonb language plpgsql volatile security definer set search_path = public, pg_catalog as $$
declare r jsonb; emp uuid; ant text; uid uuid := auth.uid();
begin
  if uid is null then raise exception 'fila_aplicar_rascunho_pre_release: sessão obrigatória' using errcode = 'insufficient_privilege'; end if;
  r := public.fila_rascunho_pre_release(p_event_id);                       -- também confere a permissão
  if (r ->> 'execucao_id') is null or (r ->> 'rascunho') is null then
    raise exception 'pre_release_recusado: não há rascunho da IA para este evento' using errcode = 'check_violation';
  end if;
  if (r ->> 'execucao_id')::uuid is distinct from p_execucao_id then
    raise exception 'pre_release_recusado: existe análise mais recente; recarregue e confira o rascunho' using errcode = 'check_violation';
  end if;
  if (r ->> 'bloqueio') is not null then
    raise exception 'pre_release_recusado: %', r ->> 'bloqueio' using errcode = 'check_violation';
  end if;
  select e.pre_release, e.empresa_id into ant, emp from public.events e where e.id = p_event_id for update;
  if coalesce(btrim(ant), '') <> '' and not coalesce(p_substituir, false) then
    raise exception 'pre_release_recusado: o evento já tem pré-release; confirme a substituição' using errcode = 'check_violation';
  end if;
  update public.events set pre_release = r ->> 'rascunho' where id = p_event_id;
  insert into public.fila_pre_release_aplicacoes (event_id, empresa_id, execucao_id, usuario_id, pre_release_anterior, pre_release_novo, substituiu)
  values (p_event_id, emp, p_execucao_id, uid, ant, r ->> 'rascunho', coalesce(btrim(ant), '') <> '');
  return jsonb_build_object('ok', true, 'event_id', p_event_id, 'execucao_id', p_execucao_id, 'pre_release', r ->> 'rascunho');
end $$;

-- 8) Trava de avanço no banco: usa o MESMO núcleo de bloqueios que a interface mostra --------------------------------------
create or replace function app_private.fila_guarda_avanco() returns trigger language plpgsql set search_path = public, pg_catalog as $$
declare d jsonb; comp jsonb; b jsonb;
begin
  if new.status_editorial::text in ('pronto_para_publicar', 'publicado') and new.status_editorial is distinct from old.status_editorial then
    d := public.fila_decisao_score(new.id);
    select s.componentes into comp from public.event_scores s where s.event_id = new.id
     order by s.vigente desc nulls last, s.created_at desc nulls last limit 1;
    b := public.fila_bloqueios_core(new.pre_release, old.status_editorial::text, new.revisao_humana, new.status_editorial::text, d, coalesce(comp, '{}'::jsonb));
    if jsonb_array_length(b) > 0 then
      raise exception 'fila_travada: %', (select string_agg(x, '; ') from jsonb_array_elements_text(b) x) using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $$;

-- 9) Permissões ----------------------------------------------------------------------------------------------------------
alter table public.fila_parametros enable row level security;
revoke all on public.fila_parametros from public, anon, authenticated;
grant select on public.fila_parametros to authenticated, service_role;
drop policy if exists fila_parametros_leitura on public.fila_parametros;
create policy fila_parametros_leitura on public.fila_parametros for select to authenticated using (true);

alter table public.fila_pre_release_aplicacoes enable row level security;
revoke all on public.fila_pre_release_aplicacoes from public, anon, authenticated;
grant select on public.fila_pre_release_aplicacoes to authenticated, service_role;
drop policy if exists fila_aplicacoes_leitura on public.fila_pre_release_aplicacoes;
create policy fila_aplicacoes_leitura on public.fila_pre_release_aplicacoes for select to authenticated
  using (exists (select 1 from public.events e where e.id = fila_pre_release_aplicacoes.event_id));

revoke all on function public.fila_parametros_vigentes(), public.fila_ts_seguro(text),
  public.fila_bloqueios_core(text, text, text, text, jsonb, jsonb), public.fila_bloqueios_publicacao(uuid, text), public.fila_ia_core(text, text, text, jsonb), public.fila_item(uuid),
  public.fila_editorial(uuid), public.fila_pode_gerar_pre_release(uuid), public.fila_pode_editar_evento(uuid),
  public.fila_rascunho_pre_release(uuid), public.fila_aplicar_rascunho_pre_release(uuid, uuid, boolean) from public, anon;
grant execute on function public.fila_parametros_vigentes(), public.fila_ts_seguro(text),
  public.fila_bloqueios_core(text, text, text, text, jsonb, jsonb), public.fila_bloqueios_publicacao(uuid, text), public.fila_ia_core(text, text, text, jsonb), public.fila_item(uuid),
  public.fila_editorial(uuid), public.fila_pode_gerar_pre_release(uuid) to authenticated, service_role;
grant execute on function public.fila_pode_editar_evento(uuid), public.fila_rascunho_pre_release(uuid),
  public.fila_aplicar_rascunho_pre_release(uuid, uuid, boolean) to authenticated;
revoke all on function app_private.fila_aplicacoes_imutavel() from public, anon, authenticated;
revoke all on function app_private.fila_guarda_avanco() from public, anon, authenticated;

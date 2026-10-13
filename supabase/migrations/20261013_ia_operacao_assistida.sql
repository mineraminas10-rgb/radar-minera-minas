-- Operação assistida manual da IA (piloto 6 chamadas). Aditivo: não altera events, scores nem coletores.
-- 1) elegibilidade determinística por evento (espelha coletores/comum/pre_ia.py com os dados JÁ persistidos)
-- 2) dossiê do evento (única entrada enviada à IA; montada no servidor)
-- 3) totais da execução (execucoes.totais) recalculados de api_execucoes
-- 4) trava rígida: no máximo 6 chamadas reais por lote, 1 por evento, e analise_editorial exige lote

create or replace function public.ia_elegibilidade_evento(p_event_id uuid) returns jsonb
language plpgsql security definer set search_path = public, pg_catalog as $$
declare
  ev record;
  v_sc_estagio text; v_sc_rel int; v_sc_pri text; v_sc_ver text; v_det_found boolean := false;
  v_mod text; v_n int; v_flags jsonb := '{}'::jsonb; v_txt text; v_prev boolean; v_faixa text;
  v_regra text;
begin
  select id, empresa_id, carteira_id, execucao_criacao_id, modulo::text as modulo, status_editorial::text as status_editorial,
         revisao_humana, tipo_evento, id_evento into ev from public.events where id = p_event_id;
  if not found then
    return jsonb_build_object('encontrado', false, 'elegivel', false, 'flags', '{}'::jsonb);
  end if;
  v_mod := ev.modulo;
  select count(*) into v_n from public.evidencias where event_id = p_event_id and not coalesce(superseded, false);
  select s.estagio, s.score_relevancia, s.prioridade::text, s.versao_score into v_sc_estagio, v_sc_rel, v_sc_pri, v_sc_ver
    from public.event_scores s where s.event_id = p_event_id and coalesce(s.vigente, true)
    order by s.created_at desc limit 1;
  select exists(select 1 from public.api_execucoes a where a.event_id = p_event_id and a.operacao = 'analise_editorial' and a.status = 'sucesso') into v_prev;

  -- regras comuns
  if v_mod not in ('M6_outorgas', 'M8_acidentes_ambientais', 'M9A_anm_movimentacoes') then
    v_flags := v_flags || '{"fora_de_escopo": true}'::jsonb;
  end if;
  if ev.status_editorial = 'descartado' then
    v_flags := v_flags || '{"descartado_por_regra_deterministica": true}'::jsonb;
  elsif ev.status_editorial in ('publicado', 'pronto_para_publicar') then
    v_flags := v_flags || '{"fora_de_escopo": true}'::jsonb;   -- já passou do estágio em que a IA ajuda
  end if;
  if v_n = 0 then
    v_flags := v_flags || '{"bloqueado_por_falta_de_documento": true}'::jsonb;   -- IA não supre evidência ausente
  end if;

  -- regras por módulo
  if v_mod = 'M8_acidentes_ambientais' then
    v_regra := 'PRE_IA_M8_V1';
    select faixa_vinculo into v_faixa from public.m8_acidentes_detalhe where event_id = p_event_id limit 1;
    v_det_found := found;
    if not v_det_found then
      v_flags := v_flags || '{"bloqueado_por_falta_de_documento": true}'::jsonb;
    elsif v_faixa is null or v_faixa not in ('provavel', 'confirmado') then
      v_flags := v_flags || '{"descartado_por_regra_deterministica": true}'::jsonb;   -- flags_m8: contextual/descartado = zero IA
    end if;
  elsif v_mod = 'M9A_anm_movimentacoes' then
    v_regra := 'PRE_IA_M9A_V1';
    select coalesce(ev.tipo_evento, '') || ' ' || coalesce(string_agg(v.trecho_literal, ' '), '') into v_txt
      from public.evidencias v where v.event_id = p_event_id and not coalesce(v.superseded, false) and v.campo_sustentado = 'descricao_tipo_evento';
    v_txt := lower(translate(coalesce(v_txt, ''), 'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'));
    -- mesmas famílias de signals.py (MUDANCA_MATERIAL + AUTORIZACAO_EXTRACAO + AVANCO_PESQUISA_APROVADO)
    if v_txt !~ '(decaimento|caducidade|cessao|transferencia|penhora|indisponibilidade|interdicao|renuncia|concessao|guia de utilizacao|portaria de lavra|relatorio aprovado|reavaliacao aprovada)' then
      v_flags := v_flags || '{"descartado_por_regra_deterministica": true}'::jsonb;
    end if;
  else
    v_regra := 'PRE_IA_M6_V1';   -- M6: o coletor só deixa 'em_apuracao' o que passou no filtro de vínculo mineral
    if v_mod = 'M6_outorgas' and ev.status_editorial <> 'em_apuracao' then
      v_flags := v_flags || '{"descartado_por_regra_deterministica": true}'::jsonb;
    end if;
  end if;

  return jsonb_build_object(
    'encontrado', true, 'event_id', p_event_id, 'empresa_id', ev.empresa_id, 'carteira_id', ev.carteira_id,
    'execucao_criacao_id', ev.execucao_criacao_id, 'modulo', v_mod, 'id_evento', ev.id_evento,
    'status_editorial', ev.status_editorial, 'revisao_humana', ev.revisao_humana,
    'evidencias', v_n, 'flags', v_flags, 'elegivel', (v_flags = '{}'::jsonb), 'regra_pre_ia', v_regra,
    'faixa_vinculo', v_faixa, 'ia_sucesso_previo', v_prev,
    'score_antes', case when v_sc_estagio is null then null else jsonb_build_object(
        'estagio', v_sc_estagio, 'score_relevancia', v_sc_rel, 'prioridade', v_sc_pri, 'versao_score', v_sc_ver) end
  );
end $$;

create or replace function public.ia_dossie_evento(p_event_id uuid, p_max_evidencias int default 12) returns jsonb
language plpgsql security definer set search_path = public, pg_catalog as $$
declare ev record; ev_json jsonb;
begin
  select id, empresa_id, carteira_id, execucao_criacao_id, modulo::text as modulo, id_evento, tipo_evento, titulo_fato, resumo_factual,
         empresa, cnpj, municipio, atividade, decisao, processo, data_evento, data_publicacao, url_oficial, estrutura, instrumento,
         empreendimento, status_editorial::text as status_editorial, revisao_humana
    into ev from public.events where id = p_event_id;
  if not found then return null; end if;
  select coalesce(jsonb_agg(jsonb_build_object('n', r.rn, 'campo', r.campo_sustentado, 'tipo', r.tipo, 'trecho', r.trecho, 'pagina_secao', r.pagina_secao) order by r.rn), '[]'::jsonb)
    into ev_json
  from (
    select row_number() over (order by d.prio, d.created_at, d.id) as rn, d.campo_sustentado, d.tipo, left(d.trecho_literal, 700) as trecho, d.pagina_secao
    from (
      select distinct on (v.campo_sustentado, v.trecho_literal) v.id, v.created_at, v.campo_sustentado, v.tipo_afirmacao::text as tipo,
             v.trecho_literal, v.pagina_secao,
             case when v.campo_sustentado in ('verbo_decisorio_literal', 'evento_tipo', 'descricao_tipo_evento') then 0 else 1 end as prio
      from public.evidencias v
      where v.event_id = p_event_id and not coalesce(v.superseded, false) and v.trecho_literal is not null and length(trim(v.trecho_literal)) > 0
      order by v.campo_sustentado, v.trecho_literal, v.created_at
    ) d
    order by d.prio, d.created_at, d.id
    limit greatest(1, least(coalesce(p_max_evidencias, 12), 20))
  ) r;
  return jsonb_build_object(
    'event_id', ev.id, 'empresa_id', ev.empresa_id, 'carteira_id', ev.carteira_id, 'execucao_criacao_id', ev.execucao_criacao_id,
    'modulo', ev.modulo, 'id_evento', ev.id_evento,
    'evento', jsonb_build_object(
      'tipo_evento', ev.tipo_evento, 'titulo_fato', ev.titulo_fato, 'resumo_factual', ev.resumo_factual, 'empresa', ev.empresa, 'cnpj', ev.cnpj,
      'municipio', ev.municipio, 'atividade', ev.atividade, 'decisao', ev.decisao, 'processo', ev.processo, 'data_evento', ev.data_evento,
      'data_publicacao', ev.data_publicacao, 'url_oficial', ev.url_oficial, 'estrutura', ev.estrutura, 'instrumento', ev.instrumento,
      'empreendimento', ev.empreendimento),
    'evidencias', ev_json);
end $$;

create or replace function public.ia_totais_atualizar(p_execucao_id uuid) returns jsonb
language plpgsql security definer set search_path = public, pg_catalog as $$
declare t jsonb; r record; base int; novo jsonb;
begin
  select totais into t from public.execucoes where id = p_execucao_id for update;
  if not found then return null; end if;
  t := coalesce(t, '{}'::jsonb);
  select
    count(*) filter (where status in ('pendente', 'sucesso', 'erro')) as chamadas,
    coalesce(sum(total_tokens) filter (where status in ('sucesso', 'erro')), 0) as tokens,
    coalesce(sum(custo_estimado_usd) filter (where status in ('sucesso', 'erro')), 0) as custo,
    count(*) filter (where status like 'bloqueado%' or status = 'reutilizado') as evitadas,
    count(distinct event_id) filter (where status in ('pendente', 'sucesso', 'erro')) as enviados,
    count(distinct event_id) filter (where status = 'sucesso') as concluidos,
    count(distinct event_id) filter (where status = 'erro') as com_erro
    into r from public.api_execucoes where execucao_id = p_execucao_id and operacao = 'analise_editorial';
  -- a base do coletor é guardada UMA vez, para o recálculo ser idempotente
  if not (t ? 'chamadas_ia_evitadas_coletor') then
    t := t || jsonb_build_object('chamadas_ia_evitadas_coletor', coalesce((t->>'chamadas_ia_evitadas')::int, 0));
  end if;
  base := coalesce((t->>'chamadas_ia_evitadas_coletor')::int, 0);
  novo := jsonb_build_object(
    'chamadas_ia', r.chamadas, 'tokens_ia', r.tokens, 'chamadas_ia_evitadas', base + r.evitadas,
    'custo_ia_usd', r.custo, 'ia_casos_enviados', r.enviados, 'ia_casos_concluidos', r.concluidos, 'ia_casos_com_erro', r.com_erro,
    'ia_atualizado_em', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'));
  update public.execucoes set totais = t || novo, custo_estimado = r.custo where id = p_execucao_id;
  return t || novo;
end $$;

-- Trava rígida de custo: ≤ 6 chamadas reais por lote, 1 por evento; analise_editorial SEMPRE exige lote.
create or replace function app_private.limite_lote_api_execucao() returns trigger
language plpgsql security definer set search_path = public, pg_catalog as $$
declare v_lote text; v_lim int; v_n int;
begin
  if new.operacao = 'analise_editorial' and new.status in ('pendente', 'sucesso', 'erro') then
    v_lote := new.metadata->>'lote_id';
    if v_lote is null or length(v_lote) = 0 then raise exception 'analise_editorial_exige_lote' using errcode = '54000'; end if;
    perform pg_advisory_xact_lock(hashtextextended(new.empresa_id::text || '|' || v_lote, 0));
    v_lim := least(greatest(coalesce((new.metadata->>'limite_ia')::int, 0), 0), 6);
    select count(*) into v_n from public.api_execucoes a
      where a.empresa_id = new.empresa_id and a.metadata->>'lote_id' = v_lote and a.status in ('pendente', 'sucesso', 'erro');
    if v_n >= v_lim then raise exception 'limite_ia_do_lote_atingido' using errcode = '54000'; end if;
    if new.event_id is not null and exists (
      select 1 from public.api_execucoes a where a.empresa_id = new.empresa_id and a.metadata->>'lote_id' = v_lote
        and a.event_id = new.event_id and a.status in ('pendente', 'sucesso', 'erro')) then
      raise exception 'evento_ja_chamado_no_lote' using errcode = '54000';
    end if;
  end if;
  return new;
end $$;

drop trigger if exists trg_limite_lote_api_execucao on public.api_execucoes;
create trigger trg_limite_lote_api_execucao before insert on public.api_execucoes
  for each row execute function app_private.limite_lote_api_execucao();

-- as funções só rodam no servidor (service_role); o navegador não as enxerga
revoke all on function public.ia_elegibilidade_evento(uuid) from public, anon, authenticated;
revoke all on function public.ia_dossie_evento(uuid, int) from public, anon, authenticated;
revoke all on function public.ia_totais_atualizar(uuid) from public, anon, authenticated;
grant execute on function public.ia_elegibilidade_evento(uuid) to service_role;
grant execute on function public.ia_dossie_evento(uuid, int) to service_role;
grant execute on function public.ia_totais_atualizar(uuid) to service_role;

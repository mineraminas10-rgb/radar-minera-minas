-- Reverte 20261019_fila_regras_no_banco.sql: restaura fila_decisao_score e a guarda de avanço como estavam na 20261016
-- e remove o que a 20261019 criou. As regras voltam a existir só na interface (modo de transição do index.html).
-- Protege o registro append-only de pré-releases aplicados: só roda se estiver vazio, ou com
--   select set_config('radar.rollback_confirmado','sim',false);   (o registro é apagado junto — exporte antes se precisar).
do $$ begin
  if to_regclass('public.fila_pre_release_aplicacoes') is not null
     and exists (select 1 from public.fila_pre_release_aplicacoes)
     and coalesce(current_setting('radar.rollback_confirmado', true), '') <> 'sim' then
    raise exception 'rollback_recusado: fila_pre_release_aplicacoes tem registros; confirme com radar.rollback_confirmado=sim' using errcode = 'check_violation';
  end if;
end $$;

-- 1) restaura as funções da 20261016 (antes de remover os parâmetros de que a versão nova depende)
create or replace function public.fila_decisao_score(p_event_id uuid) returns jsonb
language plpgsql stable security invoker set search_path = public, pg_catalog as $$
declare
  ev record; sc record; calc numeric; v numeric; decisorio boolean := false; estagio text; motivo text := 'PENDENTE_DE_SCORE';
  crit text; sit text; regra text; mot text; corte constant numeric := 40;
begin
  select id, status_editorial::text as st into ev from public.events where id = p_event_id;
  if not found then return null; end if;
  select s.score_relevancia, s.score_normalizado, s.score_bruto, s.estagio, s.versao_score, s.componentes into sc
    from public.event_scores s where s.event_id = p_event_id order by s.vigente desc nulls last, s.id desc limit 1;
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
  elsif crit in ('CRITICO','ALTA','POTENCIAL_CRITICO_PENDENTE_EVIDENCIA','POTENCIAL_ALTA_PENDENTE_EVIDENCIA') then
    sit := 'SCORE_BAIXO_COM_GATILHO_FORTE'; regra := 'SCORE_MENOR_40'; mot := 'SCORE_BAIXO_COM_GATILHO_FORTE';
  elsif ev.st in ('pronto_para_publicar','publicado','arquivado','descartado') then
    sit := 'FORA_DA_SELECAO_MANTIDO_POR_TRAVA'; regra := 'SCORE_MENOR_40'; mot := 'TRAVA_EDITORIAL_JA_APLICADA';
  else
    sit := 'FORA_DA_SELECAO'; regra := 'SCORE_MENOR_40'; mot := 'DESCARTADO_POR_SCORE';
  end if;

  return jsonb_build_object('event_id', p_event_id, 'score_valor', v, 'score_decisorio', decisorio, 'score_estagio', estagio,
    'score_versao', sc.versao_score, 'score_motivo', motivo, 'criticidade', crit, 'situacao', sit, 'regra', regra, 'motivo', mot);
end $$;

create or replace function app_private.fila_guarda_avanco() returns trigger language plpgsql set search_path = public, pg_catalog as $$
declare d jsonb;
begin
  if new.status_editorial::text in ('pronto_para_publicar','publicado') and new.status_editorial is distinct from old.status_editorial then
    if coalesce(btrim(new.pre_release), '') = '' then
      raise exception 'fila_travada: não é possível ir para % sem pré-release', new.status_editorial using errcode = 'check_violation';
    end if;
    d := public.fila_decisao_score(new.id);
    if d ->> 'situacao' = 'FORA_DA_SELECAO' then
      raise exception 'fila_travada: score decisório % < 40 (fora da seleção, regra SCORE_MENOR_40)', d ->> 'score_valor' using errcode = 'check_violation';
    end if;
    if new.status_editorial::text = 'publicado' and old.status_editorial::text <> 'pronto_para_publicar' then
      raise exception 'fila_travada: aprove (pronto_para_publicar) antes de publicar' using errcode = 'check_violation';
    end if;
  end if;
  return new;
end $$;

-- 2) remove o que é novo
drop function if exists public.fila_aplicar_rascunho_pre_release(uuid, uuid, boolean);
drop function if exists public.fila_rascunho_pre_release(uuid);
drop function if exists public.fila_pode_editar_evento(uuid);
drop function if exists public.fila_pode_gerar_pre_release(uuid);
drop function if exists public.fila_editorial(uuid);
drop function if exists public.fila_item(uuid);
drop function if exists public.fila_ia_core(text, text, text, jsonb);
drop function if exists public.fila_bloqueios_publicacao(uuid, text);
drop function if exists public.fila_bloqueios_core(text, text, text, text, jsonb, jsonb);
drop table if exists public.fila_pre_release_aplicacoes;
drop function if exists app_private.fila_aplicacoes_imutavel();
drop function if exists public.fila_ts_seguro(text);
drop function if exists public.fila_parametros_vigentes();
drop table if exists public.fila_parametros;

-- =====================================================================================
-- FILA EDITORIAL — decisão de score, trava de avanço e registro de descartes   (NÃO APLICADA)
-- Espelha no banco a regra que a interface já mostra (index.html: decisaoScore / situacaoFila / bloqueiosPublicacao).
-- ADITIVA e idempotente. NADA aqui apaga, reescreve ou recalcula dado existente:
--   * não altera events, event_scores, evidencias, documentos nem histórico (só LÊ);
--   * não redefine nenhuma função existente (ia_elegibilidade_evento fica como está — ver fila_elegivel_para_ia abaixo);
--   * não chama IA, não gera pré-release, não publica nada.
-- ÚNICA interação com tabela existente: 1 trigger BEFORE UPDATE OF status_editorial em public.events (guarda de avanço).
--   Ele só BLOQUEIA uma transição para 'pronto_para_publicar'/'publicado'; nunca escreve em events.
-- Reverter: 20261016_fila_editorial_travas_rollback.sql
-- =====================================================================================

create schema if not exists app_private;

-- 1) Decisão de score de UM evento (mesma ordem da interface):
--    score_relevancia > score com estagio='final' > preliminar (só exibição) > nenhum (PENDENTE_DE_SCORE).
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

-- 2) Visão por evento (security_invoker: respeita o RLS de quem consulta)
create or replace view public.v_fila_decisao_score with (security_invoker = true) as
select e.id as event_id, e.empresa_id, e.status_editorial::text as status_editorial,
       d.d ->> 'criticidade' as criticidade, (d.d ->> 'score_valor')::numeric as score_valor,
       (d.d ->> 'score_decisorio')::boolean as score_decisorio, d.d ->> 'score_estagio' as score_estagio,
       d.d ->> 'score_versao' as score_versao, d.d ->> 'score_motivo' as score_motivo,
       d.d ->> 'situacao' as situacao, d.d ->> 'regra' as regra, d.d ->> 'motivo' as motivo
from public.events e cross join lateral (select public.fila_decisao_score(e.id) as d) d;

-- 3) Registro APPEND-ONLY dos descartes/preservações/pendências (nunca é apagado nem editado)
create table if not exists public.fila_decisoes_score_log (
  id             bigint generated always as identity primary key,
  empresa_id     uuid,
  event_id       uuid not null references public.events(id),
  situacao       text not null,          -- FORA_DA_SELECAO | SCORE_BAIXO_COM_GATILHO_FORTE | PENDENTE_DE_SCORE
  regra          text,                   -- SCORE_MENOR_40
  motivo         text,                   -- DESCARTADO_POR_SCORE | SCORE_BAIXO_COM_GATILHO_FORTE | PENDENTE_DE_SCORE
  score_valor    numeric,
  score_estagio  text,
  score_versao   text,
  criticidade    text,
  origem         text not null default 'sistema' check (origem in ('usuario','sistema')),
  evento         text not null default 'registro_manual',
  registrado_por uuid,
  registrado_em  timestamptz not null default clock_timestamp()
);
create index if not exists fila_decisoes_score_log_event_idx on public.fila_decisoes_score_log (event_id, id desc);

create or replace function app_private.fila_log_imutavel() returns trigger language plpgsql set search_path = public, pg_catalog as $$
begin raise exception 'fila_decisoes_score_log é append-only: % não é permitido', tg_op using errcode = 'insufficient_privilege'; end $$;
drop trigger if exists trg_fila_log_imutavel on public.fila_decisoes_score_log;
create trigger trg_fila_log_imutavel before update or delete on public.fila_decisoes_score_log
  for each row execute function app_private.fila_log_imutavel();

-- Registra (idempotente) as decisões que mudaram desde o último registro de cada evento. Rodada MANUAL — nada agenda isto.
create or replace function public.fila_registrar_decisoes_score(p_empresa uuid default null, p_origem text default 'sistema', p_evento text default 'registro_manual')
returns integer language plpgsql security definer set search_path = public, pg_catalog as $$
declare n integer;
begin
  insert into public.fila_decisoes_score_log (empresa_id, event_id, situacao, regra, motivo, score_valor, score_estagio, score_versao, criticidade, origem, evento, registrado_por)
  select v.empresa_id, v.event_id, v.situacao, v.regra, v.motivo, v.score_valor, v.score_estagio, v.score_versao, v.criticidade,
         case when p_origem = 'usuario' then 'usuario' else 'sistema' end, p_evento,
         nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
    from public.v_fila_decisao_score v
   where v.situacao in ('FORA_DA_SELECAO','SCORE_BAIXO_COM_GATILHO_FORTE','PENDENTE_DE_SCORE')
     and (p_empresa is null or v.empresa_id = p_empresa)
     and not exists (select 1 from public.fila_decisoes_score_log l
                      where l.event_id = v.event_id
                        and l.id = (select max(l2.id) from public.fila_decisoes_score_log l2 where l2.event_id = v.event_id)
                        and l.situacao = v.situacao
                        and l.score_valor is not distinct from v.score_valor
                        and l.score_versao is not distinct from v.score_versao
                        and l.score_estagio is not distinct from v.score_estagio);
  get diagnostics n = row_count;
  return n;
end $$;

-- 4) Elegibilidade para IA (consulta; NÃO substitui ia_elegibilidade_evento — quem seleciona candidatos pode combiná-las depois)
create or replace function public.fila_elegivel_para_ia(p_event_id uuid) returns boolean
language sql stable security invoker set search_path = public, pg_catalog as $$
  select coalesce((public.fila_decisao_score(p_event_id) ->> 'situacao') not in ('FORA_DA_SELECAO','PENDENTE_DE_SCORE'), false)
$$;

-- 5) Guarda de avanço no banco: a interface só reflete esta regra
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
drop trigger if exists trg_fila_guarda_avanco on public.events;
create trigger trg_fila_guarda_avanco before update of status_editorial on public.events
  for each row execute function app_private.fila_guarda_avanco();

-- 6) Permissões
alter table public.fila_decisoes_score_log enable row level security;
revoke all on public.fila_decisoes_score_log from public, anon, authenticated;
grant select, insert on public.fila_decisoes_score_log to service_role;
drop policy if exists fila_decisoes_leitura_segura on public.fila_decisoes_score_log;
create policy fila_decisoes_leitura_segura on public.fila_decisoes_score_log
  for select to authenticated using (exists (select 1 from public.events e where e.id = fila_decisoes_score_log.event_id));
grant select on public.fila_decisoes_score_log to authenticated;
grant select on public.v_fila_decisao_score to authenticated, service_role;
grant execute on function public.fila_decisao_score(uuid), public.fila_elegivel_para_ia(uuid) to authenticated, service_role;
revoke all on function public.fila_registrar_decisoes_score(uuid, text, text) from public, anon, authenticated;
grant execute on function public.fila_registrar_decisoes_score(uuid, text, text) to service_role;
revoke all on function app_private.fila_log_imutavel() from public, anon, authenticated;
revoke all on function app_private.fila_guarda_avanco() from public, anon, authenticated;

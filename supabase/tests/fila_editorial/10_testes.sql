\set ON_ERROR_STOP 0
create temp table ids(k text primary key, id uuid);
create function t.ev(k text, st text, pre text, sc jsonb default null) returns uuid language plpgsql as $$
declare i uuid;
begin
  insert into public.events(empresa_id, titulo_fato, status_editorial, pre_release) values ('00000000-0000-0000-0000-00000000000a', k, st::public.status_editorial_t, pre) returning id into i;
  if sc is not null then
    insert into public.event_scores(event_id, vigente, estagio, score_bruto, score_normalizado, score_relevancia, versao_score, componentes)
    values (i, true, sc->>'estagio', (sc->>'bruto')::numeric, (sc->>'norm')::numeric, (sc->>'rel')::numeric, 'v-teste', sc->'comp');
  end if;
  insert into ids values (k, i);
  return i;
end $$;
create function t.sit(k text) returns text language sql as $$ select public.fila_decisao_score((select id from ids where k=$1)) ->> 'situacao' $$;
create function t.dec(k text) returns jsonb language sql as $$ select public.fila_decisao_score((select id from ids where k=$1)) $$;

select t.ev('final35_media','em_apuracao',null,'{"estagio":"final","norm":35,"comp":{"criticidade":"MEDIA"}}');
select t.ev('final35_alta','em_apuracao',null,'{"estagio":"final","norm":35,"comp":{"criticidade":"ALTA"}}');
select t.ev('final35_critico','novo',null,'{"estagio":"final","norm":35,"comp":{"criticidade":"CRITICO"}}');
select t.ev('final35_potencial','novo',null,'{"estagio":"final","norm":35,"comp":{"criticidade":"POTENCIAL_CRITICO_PENDENTE_EVIDENCIA"}}');
select t.ev('prelim35','em_apuracao',null,'{"estagio":"preliminar","norm":35,"comp":{"criticidade":"MEDIA"}}');
select t.ev('semscore','em_apuracao',null);
select t.ev('score_sem_valores','em_apuracao',null,'{"estagio":"final","comp":{}}');
select t.ev('final85','em_apuracao','Texto pre','{"estagio":"final","norm":85,"comp":{"criticidade":"MEDIA"}}');
select t.ev('rel_vence','em_apuracao',null,'{"estagio":"preliminar","norm":10,"rel":70}');
select t.ev('rel_baixo','em_apuracao',null,'{"estagio":"preliminar","norm":90,"rel":20,"comp":{"criticidade":"BAIXA"}}');
select t.ev('final35_aprovado','pronto_para_publicar','Texto','{"estagio":"final","norm":35,"comp":{"criticidade":"MEDIA"}}');
select t.ev('final40','em_apuracao',null,'{"estagio":"final","norm":40,"comp":{"criticidade":"MEDIA"}}');
select t.ev('final39_9','em_apuracao',null,'{"estagio":"final","norm":39.9,"comp":{"criticidade":"MEDIA"}}');

select t.chk('A01 final 35 + MEDIA => FORA_DA_SELECAO', t.sit('final35_media') = 'FORA_DA_SELECAO', t.sit('final35_media'));
select t.chk('A02 regra/motivo registrados', t.dec('final35_media')->>'regra' = 'SCORE_MENOR_40' and t.dec('final35_media')->>'motivo' = 'DESCARTADO_POR_SCORE');
select t.chk('A03 final 35 + ALTA => permanece (gatilho forte)', t.sit('final35_alta') = 'SCORE_BAIXO_COM_GATILHO_FORTE');
select t.chk('A04 final 35 + CRITICO => permanece', t.sit('final35_critico') = 'SCORE_BAIXO_COM_GATILHO_FORTE');
select t.chk('A05 potencial crítico (pendente de evidência) => permanece', t.sit('final35_potencial') = 'SCORE_BAIXO_COM_GATILHO_FORTE');
select t.chk('A06 preliminar 35 => SCORE_PROVISORIO, não decisório, nunca descarta', t.sit('prelim35') = 'SCORE_PROVISORIO' and (t.dec('prelim35')->>'score_decisorio')::boolean is false and (t.dec('prelim35')->>'score_valor')::numeric = 35);
select t.chk('A07 sem score => PENDENTE_DE_SCORE', t.sit('semscore') = 'PENDENTE_DE_SCORE');
select t.chk('A08 linha de score sem valores => PENDENTE_DE_SCORE', t.sit('score_sem_valores') = 'PENDENTE_DE_SCORE');
select t.chk('A09 final 85 => NA_SELECAO e decisório', t.sit('final85') = 'NA_SELECAO' and (t.dec('final85')->>'score_decisorio')::boolean);
select t.chk('A10 score_relevancia vence qualquer score calculado e é decisório', (t.dec('rel_vence')->>'score_valor')::numeric = 70 and (t.dec('rel_vence')->>'score_decisorio')::boolean and t.sit('rel_vence') = 'NA_SELECAO');
select t.chk('A11 score_relevancia 20 (mesmo com calculado 90) => FORA_DA_SELECAO', t.sit('rel_baixo') = 'FORA_DA_SELECAO');
select t.chk('A12 já aprovado por humano => mantido por trava, não sai da fila', t.sit('final35_aprovado') = 'FORA_DA_SELECAO_MANTIDO_POR_TRAVA');
select t.chk('A13 limite: 40 fica, 39.9 sai', t.sit('final40') = 'NA_SELECAO' and t.sit('final39_9') = 'FORA_DA_SELECAO');
select t.chk('A14 evento inexistente => null', public.fila_decisao_score(gen_random_uuid()) is null);
select t.chk('A15 view traz a mesma situação da função', (select situacao from public.v_fila_decisao_score where event_id=(select id from ids where k='final35_media')) = 'FORA_DA_SELECAO');

-- elegibilidade para IA
select t.chk('B01 IA: fora da seleção não é elegível', public.fila_elegivel_para_ia((select id from ids where k='final35_media')) is false);
select t.chk('B02 IA: pendente de score não é elegível', public.fila_elegivel_para_ia((select id from ids where k='semscore')) is false);
select t.chk('B03 IA: provisório, gatilho forte e selecionado seguem elegíveis', public.fila_elegivel_para_ia((select id from ids where k='prelim35')) and public.fila_elegivel_para_ia((select id from ids where k='final35_alta')) and public.fila_elegivel_para_ia((select id from ids where k='final85')));

-- guarda de avanço (trigger)
select t.ev('sem_pre','em_apuracao',null,'{"estagio":"final","norm":70,"comp":{"criticidade":"MEDIA"}}');
select t.ev('pre_vazio','em_apuracao','   ','{"estagio":"final","norm":70,"comp":{"criticidade":"MEDIA"}}');
select t.ev('ok_pre','em_apuracao','Texto','{"estagio":"final","norm":70,"comp":{"criticidade":"MEDIA"}}');
select t.ev('fora_com_pre','em_apuracao','Texto','{"estagio":"final","norm":10,"comp":{"criticidade":"MEDIA"}}');
select t.ev('alta_baixo_com_pre','em_apuracao','Texto','{"estagio":"final","norm":10,"comp":{"criticidade":"ALTA"}}');
select t.ev('prelim_com_pre','em_apuracao','Texto','{"estagio":"preliminar","norm":10,"comp":{"criticidade":"MEDIA"}}');
select t.ev('ja_publicado','publicado',null);
select t.chk('C01 sem pré-release: pronto_para_publicar bloqueado', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''sem_pre''') like 'fila_travada%sem pré-release%');
select t.chk('C02 pré-release em branco: bloqueado', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''pre_vazio''') like 'fila_travada%');
select t.chk('C03 sem pré-release: publicado bloqueado', t.falha('update public.events set status_editorial=''publicado'' where titulo_fato=''sem_pre''') like 'fila_travada%');
select t.chk('C04 com pré-release: pronto_para_publicar liberado', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''ok_pre''') is null);
select t.chk('C05 publicado a partir de pronto: liberado (ação humana separada)', t.falha('update public.events set status_editorial=''publicado'' where titulo_fato=''ok_pre''') is null);
select t.chk('C06 publicar direto sem aprovar: bloqueado', (select t.falha('update public.events set status_editorial=''publicado'' where titulo_fato=''alta_baixo_com_pre''') like 'fila_travada%aprove%'));
select t.chk('C07 fora da seleção (score<40 sem gatilho): bloqueado mesmo com pré-release', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''fora_com_pre''') like 'fila_travada%score decisório%');
select t.chk('C08 score<40 com gatilho forte (ALTA): pode ser aprovado por humano', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''alta_baixo_com_pre''') is null);
select t.chk('C09 score provisório baixo não bloqueia', t.falha('update public.events set status_editorial=''pronto_para_publicar'' where titulo_fato=''prelim_com_pre''') is null);
select t.chk('C10 outras transições e outras colunas não são afetadas', t.falha('update public.events set status_editorial=''descartado'' where titulo_fato=''sem_pre''') is null and t.falha('update public.events set revisao_humana=''Revisado'' where titulo_fato=''semscore''') is null);
select t.chk('C11 evento já publicado: editar outros campos não dispara a guarda', t.falha('update public.events set titulo_fato=''ja_publicado'' where titulo_fato=''ja_publicado''') is null);
select t.chk('C12 mesma coluna sem mudar de valor não dispara a guarda', t.falha('update public.events set status_editorial=''publicado'' where titulo_fato=''ja_publicado''') is null);

-- registro de descartes
create temp table antes_log as select count(*) c from public.fila_decisoes_score_log;
create temp table r1 as select public.fila_registrar_decisoes_score(null, 'sistema', 'teste') n;
create temp table r2 as select public.fila_registrar_decisoes_score(null, 'sistema', 'teste') n;
select t.chk('D01 1ª rodada registra FORA/gatilho/pendente', (select n from r1) >= 9, (select n from r1)::text);
select t.chk('D02 2ª rodada é idempotente (0 novas)', (select n from r2) = 0);
select t.chk('D03 registro guarda score, versão, estágio, regra, data/hora, origem e evento', exists (select 1 from public.fila_decisoes_score_log l join ids i on i.id=l.event_id
  where i.k='final35_media' and l.situacao='FORA_DA_SELECAO' and l.regra='SCORE_MENOR_40' and l.motivo='DESCARTADO_POR_SCORE' and l.score_valor=35 and l.score_versao='v-teste' and l.score_estagio='final'
    and l.registrado_em is not null and l.origem='sistema' and l.evento='teste'));
select t.chk('D04 gatilho forte registrado como SCORE_BAIXO_COM_GATILHO_FORTE', exists (select 1 from public.fila_decisoes_score_log l join ids i on i.id=l.event_id where i.k='final35_alta' and l.situacao='SCORE_BAIXO_COM_GATILHO_FORTE'));
select t.chk('D05 pendente registrado; provisório e selecionado NÃO entram no registro', exists (select 1 from public.fila_decisoes_score_log l join ids i on i.id=l.event_id where i.k='semscore' and l.situacao='PENDENTE_DE_SCORE')
  and not exists (select 1 from public.fila_decisoes_score_log l join ids i on i.id=l.event_id where i.k in ('prelim35','final85')));
select t.chk('D06 registro é append-only (UPDATE bloqueado)', t.falha('update public.fila_decisoes_score_log set motivo=''x''') like '%append-only%');
select t.chk('D07 registro é append-only (DELETE bloqueado)', t.falha('delete from public.fila_decisoes_score_log') like '%append-only%');
update public.event_scores s set score_normalizado = 60 from ids i where i.id = s.event_id and i.k = 'final35_media';
create temp table r3 as select public.fila_registrar_decisoes_score(null, 'usuario', 'teste2') n;
select t.chk('D08 score mudou (35->60): sai da seleção "fora" sem apagar o registro anterior', (select count(*) from public.fila_decisoes_score_log l join ids i on i.id=l.event_id where i.k='final35_media') = 1 and t.sit('final35_media') = 'NA_SELECAO');
update public.event_scores s set score_normalizado = 20 from ids i where i.id = s.event_id and i.k = 'final35_media';
create temp table r4 as select public.fila_registrar_decisoes_score(null, 'usuario', 'teste3') n;
select t.chk('D09 volta a cair: novo registro (histórico preservado, origem usuario)', (select count(*) from public.fila_decisoes_score_log l join ids i on i.id=l.event_id where i.k='final35_media') = 2 and exists (select 1 from public.fila_decisoes_score_log l where l.origem='usuario' and l.evento='teste3'));

-- nada apagado: todos os eventos, scores e evidências continuam
select t.chk('E02 nenhuma função da migração escreve em events/event_scores (estático)', not exists (
  select 1 from pg_proc p where p.proname in ('fila_decisao_score','fila_elegivel_para_ia','fila_registrar_decisoes_score') and p.prosrc ~* '(update|delete|insert) +(into +)?(from +)?public\.(events|event_scores)'));

-- permissões
set role anon;
select t.chk('F01 anon não lê o registro', t.falha('select 1 from public.fila_decisoes_score_log') like '%permission denied%');
select t.chk('F02 anon não executa o registrador', t.falha('select public.fila_registrar_decisoes_score()') like '%permission denied%');
reset role;
set role authenticated;
select t.chk('F03 authenticated não executa o registrador', t.falha('select public.fila_registrar_decisoes_score()') like '%permission denied%');
select t.chk('F04 authenticated não insere no registro', t.falha('insert into public.fila_decisoes_score_log(event_id, situacao) select id, ''x'' from public.events limit 1') like '%permission denied%');
select t.chk('F05 authenticated lê a visão e a função de decisão', t.falha('select * from public.v_fila_decisao_score') is null and t.falha('select public.fila_decisao_score(gen_random_uuid())') is null);
reset role;

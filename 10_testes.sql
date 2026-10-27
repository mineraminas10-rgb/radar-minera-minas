\set ON_ERROR_STOP off
-- Usuários e vínculos
insert into public.usuarios_perfil(id, role, nome, ativo) values
 ('00000000-0000-0000-0000-00000000000a','master','M',true),
 ('00000000-0000-0000-0000-0000000000a1','admin','Admin empresa 1',true),
 ('00000000-0000-0000-0000-0000000000a2','admin','Admin empresa 2',true),
 ('00000000-0000-0000-0000-0000000000c1','cliente','Cliente',true);
insert into public.usuario_empresas values
 ('00000000-0000-0000-0000-0000000000a1','11111111-1111-1111-1111-111111111111',true),
 ('00000000-0000-0000-0000-0000000000a2','22222222-2222-2222-2222-222222222222',true),
 ('00000000-0000-0000-0000-0000000000c1','11111111-1111-1111-1111-111111111111',true);

-- Migrações (a 20261019 já foi aplicada 2x pelo script antes; aqui só garantimos a ordem de dependência)
-- Fábrica de eventos: n, empresa, status, data_evento, estágio, score, criticidade, componentes extras
create function t.mk(n int, emp text, st text, dev date, estagio text, sc numeric, crit text, extra jsonb default '{}') returns uuid language plpgsql as $$
declare id uuid := ('e0000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid;
begin
  insert into public.events(id, empresa_id, titulo_fato, status_editorial, data_evento) values (id, emp::uuid, 'E' || n, st::public.status_editorial_t, dev);
  if estagio is not null then
    insert into public.event_scores(event_id, vigente, estagio, score_normalizado, score_relevancia, versao_score, componentes, prioridade)
    values (id, true, estagio, sc, case when estagio = 'editorial' then sc end, 'V', jsonb_build_object('criticidade', crit) || extra, 'B');
  end if;
  return id;
end $$;
select set_config('radar.agora', '2026-10-20T00:00:00Z', false);
select t.mk(1,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',90,'CRITICO');
select t.mk(2,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',35,'ALTA');
select t.mk(3,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',35,'MEDIA');
select t.mk(4,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10',null,null,null);
select t.mk(5,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','preliminar',99,'MEDIA');
select t.mk(6,'11111111-1111-1111-1111-111111111111','em_apuracao','2025-10-10','final',70,'MEDIA');
select t.mk(7,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',70,'MEDIA');
select t.mk(8,'11111111-1111-1111-1111-111111111111','publicado','2026-10-10','final',90,'CRITICO');
select t.mk(9,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',50,'ALTA');
select t.mk(10,'22222222-2222-2222-2222-222222222222','em_apuracao','2026-10-10','final',90,'CRITICO');
select t.mk(11,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',50,'BAIXA');
select t.mk(12,'11111111-1111-1111-1111-111111111111','em_apuracao','2026-10-10','final',50,'MEDIA',
  '{"atualizacao_material":{"impacto":"critico"},"ultima_atualizacao_material":"2026-10-15T00:00:00Z"}');
insert into public.api_execucoes(event_id, empresa_id, operacao, status, data_inicio, resposta_texto) values
 ('e0000000-0000-0000-0000-000000000009','11111111-1111-1111-1111-111111111111','analise_editorial','sucesso', '2026-10-18T10:00:00Z',
  '{"proposta_abordagem":{"texto":"abordagem","rascunho_pre_release":"A empresa X teve a outorga Y publicada em 2026."}}'),
 ('e0000000-0000-0000-0000-000000000003','11111111-1111-1111-1111-111111111111','analise_editorial','sucesso', '2026-10-18T10:00:00Z',
  '{"proposta_abordagem":{"texto":"x","rascunho_pre_release":"rascunho de evento fora da seleção"}}'),
 ('e0000000-0000-0000-0000-000000000008','11111111-1111-1111-1111-111111111111','analise_editorial','sucesso', '2026-10-18T10:00:00Z',
  '{"proposta_abordagem":{"texto":"x","rascunho_pre_release":"rascunho de evento publicado"}}'),
 ('e0000000-0000-0000-0000-000000000010','22222222-2222-2222-2222-222222222222','analise_editorial','sucesso', '2026-10-18T10:00:00Z',
  '{"proposta_abordagem":{"texto":"x","rascunho_pre_release":"rascunho da empresa 2"}}'),
 ('e0000000-0000-0000-0000-000000000002','11111111-1111-1111-1111-111111111111','analise_editorial','sucesso', '2026-10-18T10:00:00Z',
  '{"proposta_abordagem":{"texto":"x","rascunho_pre_release":null}}');

create function t.q(p_uid text, p_sql text) returns jsonb language plpgsql security invoker as $$
declare r jsonb; begin perform set_config('request.jwt.claim.sub', p_uid, false); execute p_sql into r; return r; end $$;
create function t.como(p_uid text, p_sql text) returns text language plpgsql as $$
begin perform set_config('request.jwt.claim.sub', p_uid, false); return t.falha(p_sql); end $$;
create function t.ev(n int) returns uuid language sql as $$ select ('e0000000-0000-0000-0000-' || lpad(n::text, 12, '0'))::uuid $$;
create function t.pri(n int) returns text language sql as $$ select public.fila_item(t.ev(n)) -> 'prioridade_editorial' ->> 'codigo' $$;
create function t.mot(n int) returns text language sql as $$ select public.fila_item(t.ev(n)) -> 'prioridade_editorial' ->> 'motivo' $$;
grant execute on function t.q(text, text), t.como(text, text) to authenticated, anon;
grant execute on function t.ev(int) to authenticated, anon;
create temp table t_antes as select event_id, prioridade from public.event_scores;
create temp table t_antes_ev as select id, pre_release from public.events;
create temp table t_antes_api as select count(*) n from public.api_execucoes;

-- A) prioridade A/B/C/D no banco
select t.chk('A1 CRITICO 90 => A', t.pri(1) = 'A' and t.mot(1) = 'CRITICIDADE_CRITICO');
select t.chk('A2 ALTA 35 (gatilho forte) => C, nunca B/D', t.pri(2) = 'C' and t.mot(2) = 'SCORE_BAIXO_COM_GATILHO_FORTE'
  and public.fila_item(t.ev(2)) -> 'prioridade_editorial' ->> 'aviso' = 'Score baixo, mantido por gatilho forte');
select t.chk('A3 MEDIA 35 => D (fora da seleção)', t.pri(3) = 'D' and t.mot(3) = 'FORA_DA_SELECAO');
select t.chk('A4 sem score => PENDENTE', t.pri(4) = 'PENDENTE' and t.mot(4) = 'PENDENTE_DE_SCORE');
select t.chk('A5 MEDIA preliminar 99 => PENDENTE (provisório não eleva)', t.pri(5) = 'PENDENTE' and t.mot(5) = 'SCORE_PROVISORIO');
select t.chk('A6 MEDIA 70 antigo => C', t.pri(6) = 'C');
select t.chk('A7 MEDIA 70 atual => B', t.pri(7) = 'B' and t.mot(7) = 'SCORE_60_ELEGIVEL_E_ATUAL');
select t.chk('A8 já publicado sem novidade => D (mesmo CRITICO 90)', t.pri(8) = 'D' and t.mot(8) = 'JA_PUBLICADO_SEM_NOVIDADE');
select t.chk('A9 ALTA 50 => B', t.pri(9) = 'B');
select t.chk('A10 BAIXA 50 => D', t.pri(11) = 'D' and t.mot(11) = 'CRITICIDADE_BAIXA_OU_ROTINA');
select t.chk('A11 atualização material crítica => A, e item "atualizado"', t.pri(12) = 'A'
  and (public.fila_item(t.ev(12)) -> 'atual' ->> 'atualizado')::boolean);
select t.chk('A12 score não é a prioridade: mesmo score 90 dá A (e1) e D (e8)', t.pri(1) <> t.pri(8));
select t.chk('A13 event_scores.prioridade (histórico CRIT) intacta', not exists (
  select 1 from public.event_scores s join t_antes a on a.event_id = s.event_id and a.prioridade is distinct from s.prioridade));

-- B) fila ordenada
select t.chk('B1 fila da empresa 1 só traz eventos da empresa 1', (select count(*) from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x) = 11
  and not exists (select 1 from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x where x ->> 'event_id' = t.ev(10)::text));
select t.chk('B2 atualizado (e12) vem primeiro; "ordem" é 1..n sem buracos',
  (public.fila_editorial('11111111-1111-1111-1111-111111111111') -> 0 ->> 'event_id') = t.ev(12)::text
  and (select array_agg((x ->> 'ordem')::int order by (x ->> 'ordem')::int) = array(select generate_series(1, 11))
         from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x));
select t.chk('B3 depois do atualizado: A antes de B antes de C antes de PENDENTE antes de D', (
  select array_agg(x -> 'prioridade_editorial' ->> 'codigo' order by (x ->> 'ordem')::int)
    from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x) = array['A','A','B','B','C','C','PENDENTE','PENDENTE','D','D','D']);
select t.chk('B4 desempate por criticidade e score: e1 (CRITICO 90) antes de e12 não, e12 atualizado primeiro; e9 (ALTA) antes de e7 (MEDIA)',
  (select (x ->> 'ordem')::int from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x where x ->> 'event_id' = t.ev(9)::text)
  < (select (x ->> 'ordem')::int from jsonb_array_elements(public.fila_editorial('11111111-1111-1111-1111-111111111111')) x where x ->> 'event_id' = t.ev(7)::text));

-- C) bloqueios
select t.chk('C1 sem pré-release bloqueia pronto_para_publicar', public.fila_bloqueios_publicacao(t.ev(1), 'pronto_para_publicar') ? 'sem pré-release');
select t.chk('C2 fora da seleção bloqueia', public.fila_bloqueios_publicacao(t.ev(3), 'pronto_para_publicar') ? 'score decisório < 40 (fora da seleção)');
select t.chk('C3 publicado exige aprovação prévia e revisão humana', public.fila_bloqueios_publicacao(t.ev(1), 'publicado') ? 'aprove antes (Pronto p/ publicar)'
  and public.fila_bloqueios_publicacao(t.ev(1), 'publicado') ? 'revisão humana pendente');
select t.chk('C4 o item da fila já traz os bloqueios (a interface não calcula)', jsonb_array_length(public.fila_item(t.ev(1)) -> 'bloqueios' -> 'publicado') >= 3);

-- D) trava de avanço no banco usa o MESMO núcleo
select t.chk('D1 trava: ir para pronto_para_publicar sem pré-release',
  t.falha($$update public.events set status_editorial = 'pronto_para_publicar' where id = 'e0000000-0000-0000-0000-000000000001'$$) like 'fila_travada: sem pré-release%');
select t.chk('D2 trava: fora da seleção',
  t.falha($$update public.events set status_editorial = 'pronto_para_publicar', pre_release = 'x' where id = 'e0000000-0000-0000-0000-000000000003'$$) like '%fora da seleção%');
select t.chk('D3 trava: publicar sem aprovar antes + revisão pendente',
  t.falha($$update public.events set status_editorial = 'publicado', pre_release = 'x' where id = 'e0000000-0000-0000-0000-000000000001'$$) like '%aprove antes%revisão humana pendente%');
select t.chk('D4 passa quando cumpre as regras', t.falha($$update public.events set status_editorial = 'pronto_para_publicar', pre_release = 'texto' where id = 'e0000000-0000-0000-0000-000000000001'$$) is null);
select t.chk('D5 publicar ainda trava por revisão humana pendente', t.falha($$update public.events set status_editorial = 'publicado' where id = 'e0000000-0000-0000-0000-000000000001'$$) like '%revisão humana pendente%');
update public.events set revisao_humana = 'Aprovado' where id = t.ev(1);
select t.chk('D6 publica após revisão humana', t.falha($$update public.events set status_editorial = 'publicado' where id = 'e0000000-0000-0000-0000-000000000001'$$) is null);
update public.events set status_editorial = 'em_apuracao', pre_release = null where id = t.ev(1);   -- volta ao estado do cenário (a trava só vale p/ pronto/publicado)

-- E) regras vivem em PARÂMETROS no banco: mudar o parâmetro muda o resultado (sem tocar no index)
update public.fila_parametros set parametros = jsonb_set(parametros, '{score_corte}', '30') where vigente;
select t.chk('E1 corte 30: e3 (35) entra na seleção e vira C', t.pri(3) = 'C' and public.fila_decisao_score(t.ev(3)) ->> 'situacao' = 'NA_SELECAO');
update public.fila_parametros set parametros = jsonb_set(parametros, '{score_corte}', '40') where vigente;
update public.fila_parametros set parametros = jsonb_set(parametros, '{score_b}', '75') where vigente;
select t.chk('E2 limiar B=75: e7 (70) deixa de ser B', t.pri(7) = 'C');
update public.fila_parametros set parametros = jsonb_set(parametros, '{score_b}', '60') where vigente;
update public.fila_parametros set parametros = jsonb_set(parametros, '{janela_atualidade_dias}', '5') where vigente;
select t.chk('E3 janela 5 dias: e7 (data 10 dias atrás) deixa de ser "atual"', t.pri(7) = 'C');
update public.fila_parametros set parametros = jsonb_set(parametros, '{janela_atualidade_dias}', '90') where vigente;
select t.chk('E4 parâmetros restaurados => e7 volta a B', t.pri(7) = 'B');
select t.chk('E5 só uma versão vigente de parâmetros', (select count(*) from public.fila_parametros where vigente) = 1);
select t.chk('E6 item informa a versão das regras', public.fila_item(t.ev(1)) ->> 'regras_versao' = 'FILA-PARAMS-V1');

-- F) a IA só gera pré-release se o banco permitir
select t.chk('F1 e1 (A) pode', (public.fila_pode_gerar_pre_release(t.ev(1)) ->> 'pode')::boolean);
select t.chk('F2 e3 (fora da seleção) não pode', not (public.fila_pode_gerar_pre_release(t.ev(3)) ->> 'pode')::boolean and public.fila_pode_gerar_pre_release(t.ev(3)) -> 'motivos' ? 'FORA_DA_SELECAO');
select t.chk('F3 e4 (sem score) não pode', public.fila_pode_gerar_pre_release(t.ev(4)) -> 'motivos' ? 'PENDENTE_DE_SCORE');
select t.chk('F4 e8 (prioridade D por já publicado) não pode', public.fila_pode_gerar_pre_release(t.ev(8)) -> 'motivos' ? 'PRIORIDADE_D');
select t.chk('F5 e5 (score provisório, PENDENTE) pode', (public.fila_pode_gerar_pre_release(t.ev(5)) ->> 'pode')::boolean);
update public.fila_parametros set parametros = jsonb_set(parametros, '{prioridades_sem_pre_release}', '[]') where vigente;
select t.chk('F6 parâmetro prioridades_sem_pre_release=[] libera e8', (public.fila_pode_gerar_pre_release(t.ev(8)) ->> 'pode')::boolean);
update public.fila_parametros set parametros = jsonb_set(parametros, '{prioridades_sem_pre_release}', '["D"]') where vigente;
select t.chk('F7 evento inexistente => pode=false', not (public.fila_pode_gerar_pre_release('99999999-9999-9999-9999-999999999999') ->> 'pode')::boolean);

-- G) rascunho da IA -> pré-release (só por clique, com permissão e travas)
set role authenticated;
select t.chk('G1 admin da empresa 1 vê o rascunho da IA',
  t.q('00000000-0000-0000-0000-0000000000a1', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000009')$$) ->> 'rascunho' like 'A empresa X%');
select t.chk('G2 admin de OUTRA empresa é recusado',
  t.como('00000000-0000-0000-0000-0000000000a2', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000009')$$) like '%sem permissão%');
select t.chk('G3 cliente (sem permissão editorial) é recusado',
  t.como('00000000-0000-0000-0000-0000000000c1', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000009')$$) like '%sem permissão%');
select t.chk('G4 sem sessão é recusado',
  t.como('', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000009')$$) like '%sessão obrigatória%');
select t.chk('G5 evento fora da seleção: rascunho existe mas bloqueio=FORA_DA_SELECAO',
  t.q('00000000-0000-0000-0000-0000000000a1', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000003')$$) ->> 'bloqueio' = 'FORA_DA_SELECAO');
select t.chk('G6 evento já publicado: bloqueio=STATUS_JA_DECIDIDO',
  t.q('00000000-0000-0000-0000-0000000000a1', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000008')$$) ->> 'bloqueio' = 'STATUS_JA_DECIDIDO');
select t.chk('G7 análise sem rascunho: bloqueio=ANALISE_SEM_RASCUNHO',
  t.q('00000000-0000-0000-0000-0000000000a1', $$select public.fila_rascunho_pre_release('e0000000-0000-0000-0000-000000000002')$$) ->> 'bloqueio' = 'ANALISE_SEM_RASCUNHO');
reset role;
create temp table t_exec as select id from public.api_execucoes where event_id = t.ev(9);
create temp table t_exec3 as select id from public.api_execucoes where event_id = t.ev(3);
grant select on t_exec, t_exec3 to authenticated;
set role authenticated;
select t.chk('G8 aplicar com execução errada é recusado',
  t.como('00000000-0000-0000-0000-0000000000a1', $$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000009','00000000-0000-0000-0000-00000000dead')$$) like '%análise mais recente%');
select t.chk('G9 admin de outra empresa não aplica',
  t.como('00000000-0000-0000-0000-0000000000a2', format($$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000009','%s')$$, (select id from t_exec))) like '%sem permissão%');
select t.chk('G10 aplicar em evento fora da seleção é recusado',
  t.como('00000000-0000-0000-0000-0000000000a1', format($$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000003','%s')$$, (select id from t_exec3))) like '%FORA_DA_SELECAO%');
select t.chk('G11 admin aplica o rascunho do evento 9',
  t.q('00000000-0000-0000-0000-0000000000a1', format($$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000009','%s')$$, (select id from t_exec))) ->> 'ok' = 'true');
reset role;
select t.chk('G12 events.pre_release do evento 9 recebeu o texto', (select pre_release from public.events where id = t.ev(9)) like 'A empresa X teve a outorga Y%');
select t.chk('G13 log append-only registrou quem aplicou', (select count(*) from public.fila_pre_release_aplicacoes where event_id = t.ev(9) and usuario_id = '00000000-0000-0000-0000-0000000000a1' and not substituiu) = 1);
set role authenticated;
select t.chk('G14 reaplicar sem confirmar substituição é recusado',
  t.como('00000000-0000-0000-0000-0000000000a1', format($$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000009','%s')$$, (select id from t_exec))) like '%já tem pré-release%');
select t.chk('G15 com confirmação, substitui e registra substituiu=true',
  t.q('00000000-0000-0000-0000-0000000000a1', format($$select public.fila_aplicar_rascunho_pre_release('e0000000-0000-0000-0000-000000000009','%s', true)$$, (select id from t_exec))) ->> 'ok' = 'true');
reset role;
select t.chk('G16 log tem 2 linhas, a 2ª com substituiu', (select count(*) from public.fila_pre_release_aplicacoes where event_id = t.ev(9)) = 2
  and exists (select 1 from public.fila_pre_release_aplicacoes where event_id = t.ev(9) and substituiu));
select t.chk('G17 log é append-only (update)', t.falha($$update public.fila_pre_release_aplicacoes set substituiu = false$$) like '%append-only%');
select t.chk('G18 log é append-only (delete)', t.falha($$delete from public.fila_pre_release_aplicacoes$$) like '%append-only%');
select t.chk('G19 nenhum OUTRO evento teve pré-release alterado (nada automático)',
  not exists (select 1 from public.events e join t_antes_ev a on a.id = e.id where e.id <> t.ev(9) and e.pre_release is distinct from a.pre_release));
select t.chk('G20 nenhuma chamada de IA criada (api_execucoes inalterado)', (select count(*) from public.api_execucoes) = (select n from t_antes_api));

-- H) segurança de acesso
select t.chk('H1 anon não executa fila_aplicar_rascunho_pre_release', not has_function_privilege('anon', 'public.fila_aplicar_rascunho_pre_release(uuid,uuid,boolean)', 'execute'));
select t.chk('H2 anon não executa fila_editorial', not has_function_privilege('anon', 'public.fila_editorial(uuid)', 'execute'));
select t.chk('H3 authenticated não escreve parâmetros nem o registro de pré-releases', not has_table_privilege('authenticated', 'public.fila_parametros', 'update')
  and not has_table_privilege('authenticated', 'public.fila_parametros', 'insert') and not has_table_privilege('authenticated', 'public.fila_pre_release_aplicacoes', 'insert'));
select t.chk('H4 service_role executa fila_pode_gerar_pre_release (servidor da IA)', has_function_privilege('service_role', 'public.fila_pode_gerar_pre_release(uuid)', 'execute'));
select t.chk('H5 service_role NÃO executa aplicar (só usuário logado, por clique)', not has_function_privilege('service_role', 'public.fila_aplicar_rascunho_pre_release(uuid,uuid,boolean)', 'execute'));
select t.chk('H6 fila_item respeita o RLS de quem consulta (security invoker)', (select prosecdef from pg_proc where proname = 'fila_item') = false
  and (select prosecdef from pg_proc where proname = 'fila_editorial') = false);

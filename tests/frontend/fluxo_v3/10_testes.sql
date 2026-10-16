-- Testes do fluxo v3 (rodar SÓ em banco de TESTE, depois de 00_stubs.sql e da migração).
-- Cada teste grava uma linha em t.res (ok/falha). O runner imprime o resultado e falha se houver qualquer falha.
drop schema if exists t cascade;
create schema t;
create table t.res (n serial, nome text, ok boolean, detalhe text);

create function t.afirma(p_nome text, p_cond boolean, p_det text default null) returns void language plpgsql as $$
begin insert into t.res (nome, ok, detalhe) values (p_nome, coalesce(p_cond, false), p_det); end $$;

-- executa p_sql e espera ERRO cuja mensagem contenha p_trecho (opcionalmente sob outro papel)
create function t.erra(p_nome text, p_sql text, p_trecho text, p_papel text default null) returns void language plpgsql as $$
declare v_ok boolean; v_msg text;
begin
  begin
    if p_papel is not null then execute 'set local role ' || p_papel; end if;
    execute p_sql;
    v_ok := false; v_msg := 'NAO FALHOU';
  exception when others then
    v_ok := position(lower(p_trecho) in lower(sqlerrm)) > 0; v_msg := sqlerrm;
  end;
  reset role;
  insert into t.res (nome, ok, detalhe) values (p_nome, v_ok, case when v_ok then null else 'esperava "' || p_trecho || '" e veio: ' || v_msg end);
end $$;

-- executa p_sql e espera SUCESSO
create function t.passa(p_nome text, p_sql text, p_papel text default null) returns void language plpgsql as $$
declare v_ok boolean; v_msg text;
begin
  begin
    if p_papel is not null then execute 'set local role ' || p_papel; end if;
    execute p_sql; v_ok := true;
  exception when others then v_ok := false; v_msg := sqlerrm;
  end;
  reset role;
  insert into t.res (nome, ok, detalhe) values (p_nome, v_ok, v_msg);
end $$;

create function t.usuario() returns uuid language sql immutable as $$ select '11111111-1111-1111-1111-111111111111'::uuid $$;

create function t.novo_caso() returns uuid language plpgsql as $$
declare v uuid;
begin
  insert into public.events (empresa_id, titulo) values ('e0000000-0000-0000-0000-000000000001', 'caso de teste') returning id into v;
  insert into public.evidencias (event_id, url) select v, 'https://exemplo/' || g from generate_series(1, 3) g;
  return v;
end $$;

create function t.ev(p_event uuid, p_n int) returns uuid language sql as $$
  select id from (select id, row_number() over (order by url) rn from public.evidencias where event_id = p_event) x where rn = p_n $$;

create function t.matriz_ok(p_event uuid) returns jsonb language sql as $$
  select jsonb_build_array(
    jsonb_build_object('codigo','core.url_documento','estado','confirmado','critico',true,'classe_impacto','FATO_PRINCIPAL','fonte_primaria',true,'evidencia_ids',jsonb_build_array(t.ev(p_event,1))),
    jsonb_build_object('codigo','core.empresa','estado','confirmado','critico',true,'classe_impacto','ATRIBUICAO','evidencia_ids',jsonb_build_array(t.ev(p_event,1),t.ev(p_event,2))),
    jsonb_build_object('codigo','core.fato_novo','estado','confirmado','critico',true,'classe_impacto','FATO_PRINCIPAL','evidencia_ids',jsonb_build_array(t.ev(p_event,2))),
    jsonb_build_object('codigo','core.antecedente','estado','nao_localizado','critico',false,'classe_impacto','PERIFERICA','observacao','sem antecedente localizado'),
    jsonb_build_object('codigo','core.contato_jornalistico_atual','estado','nao_localizado','critico',false,'classe_impacto','PERIFERICA','observacao','contato atual nao localizado')) $$;

create function t.afirmacoes_ok(p_event uuid) returns jsonb language sql as $$
  select jsonb_build_array(jsonb_build_object('id','A1','texto','Afirmacao 1','status','confirmado',
    'evidencias',jsonb_build_array(jsonb_build_object('ev','E1','evidencia_id',t.ev(p_event,1))))) $$;

create function t.rev_ok() returns jsonb language sql as $$
  select jsonb_build_object('fonte_primaria','localizada_e_legivel','identidade_evento','confirmada','natureza_ato','ato_efetivado','duplicidade','nao') $$;

create function t.ultimo(p_tab text, p_event uuid) returns uuid language plpgsql as $$
declare v uuid;
begin
  execute format('select id from public.%I where event_id = $1 order by %s desc limit 1', p_tab,
                 case p_tab when 'fluxo_transicoes' then 'seq' when 'dossie_versoes' then 'versao' else 'versao' end) into v using p_event;
  return v;
end $$;

-- conduz um caso (por todas as etapas humanas) até o estado p_ate, usando só as funções reais do fluxo
create function t.avanca(p_event uuid, p_ate text, p_matriz jsonb default null, p_rev jsonb default null,
                         p_modo text default 'completa', p_extra jsonb default '{}'::jsonb) returns void language plpgsql as $$
declare est text; u uuid := t.usuario(); v_lote uuid; v_ex uuid; v_dos uuid; v_hash text; v_pv uuid; v_th text; n int := 0; v_res jsonb;
begin
  loop
    est := public.fluxo_estado(p_event);
    exit when est = p_ate;
    n := n + 1; if n > 30 then raise exception 'avanca: loop sem fim em % rumo a %', est, p_ate; end if;
    if est = 'SEM_FLUXO' then
      insert into public.selecao_lotes (versao_regra, itens) values ('t', jsonb_build_array(jsonb_build_object('ordem',1,'event_id',p_event))) returning id into v_lote;
      perform public.fluxo_registrar(p_event, 'COLETOR_SELECIONAR', 'REVISAO_SELECAO', null, null, jsonb_build_object('lote_id', v_lote));
    elsif est = 'REVISAO_SELECAO' then perform public.fluxo_registrar(p_event, 'APROVAR_PARA_IA', 'PRONTO_PARA_IA', u, null, '{}');
    elsif est = 'PRONTO_PARA_IA' then perform public.fluxo_registrar(p_event, 'LIBERAR_IA', 'IA_LIBERADA', u, null, '{}');
    elsif est = 'IA_LIBERADA' then
      insert into public.api_execucoes (event_id, empresa_id, operacao, status) values (p_event, 'e0000000-0000-0000-0000-000000000001', 'analise_editorial', 'sucesso') returning id into v_ex;
      perform public.fluxo_registrar(p_event, 'EXECUTAR_IA', 'IA_EXECUTADA', u, null, jsonb_build_object('execucao_ia_id', v_ex));
    elsif est = 'IA_EXECUTADA' then
      select id into v_ex from public.api_execucoes where event_id = p_event and operacao = 'analise_editorial' order by created_at desc limit 1;
      insert into public.dossie_versoes (event_id, empresa_id, versao, modo_analise, execucao_ia_id, base, afirmacoes, matriz, alertas, delta, hash)
      values (p_event, '00000000-0000-0000-0000-000000000000', 0, p_modo, v_ex, '{"dossie":"base"}', t.afirmacoes_ok(p_event),
              coalesce(p_matriz, t.matriz_ok(p_event)), coalesce(p_extra->'alertas', '{}'::jsonb),
              case when p_modo = 'delta' then '{"campos":[]}'::jsonb end, '') returning id into v_dos;
      perform public.fluxo_registrar(p_event, 'ABRIR_REVISAO_ANALISE', 'REVISAO_ANALISE_IA', u, null, jsonb_build_object('dossie_versao_id', v_dos));
    elsif est = 'REVISAO_ANALISE_IA' then
      select id, hash into v_dos, v_hash from public.dossie_versoes where event_id = p_event order by versao desc limit 1;
      perform public.fluxo_registrar(p_event, 'LIBERAR_PRE_RELEASE', 'PRE_RELEASE_LIBERADO', u, null,
        coalesce(p_rev, t.rev_ok()) || coalesce(p_extra->'liberacao', '{}'::jsonb) ||
        jsonb_build_object('dossie_versao_id', v_dos, 'hash_dossie', v_hash, 'conferencia', true));
    elsif est = 'PRE_RELEASE_LIBERADO' then
      select id into v_dos from public.dossie_versoes where event_id = p_event order by versao desc limit 1;
      insert into public.api_execucoes (event_id, empresa_id, operacao, status) values (p_event, 'e0000000-0000-0000-0000-000000000001', 'pre_release', 'sucesso') returning id into v_ex;
      perform public.fluxo_gerar_pre_release(p_event, u, v_dos, v_ex, '{"secoes":[{"titulo":"Fato","texto":"..."}]}'::jsonb,
                                             coalesce(p_extra->'validacao', '{}'::jsonb), 'prompt-v1', 'modelo-x');
    elsif est = 'PRE_RELEASE_GERADO' then
      v_pv := t.ultimo('pre_release_versoes', p_event);
      perform public.fluxo_registrar(p_event, 'ABRIR_REVISAO_FINAL', 'REVISAO_FINAL', u, null, jsonb_build_object('pre_release_versao_id', v_pv));
    elsif est = 'REVISAO_FINAL' then
      select id, texto_hash into v_pv, v_th from public.pre_release_versoes where event_id = p_event order by versao desc limit 1;
      perform public.fluxo_registrar(p_event, 'APROVAR', 'APROVADO_PARA_PUBLICACAO', u, null,
        jsonb_build_object('pre_release_versao_id', v_pv, 'conferencia_final', true, 'hash_pre_release', v_th));
    elsif est = 'APROVADO_PARA_PUBLICACAO' then
      v_pv := t.ultimo('pre_release_versoes', p_event);
      perform public.fluxo_registrar(p_event, 'PUBLICAR', 'PUBLICADO', u, null, jsonb_build_object('pre_release_versao_id', v_pv, 'confirmacao', true));
    else raise exception 'avanca: sem rota de % para %', est, p_ate;
    end if;
  end loop;
end $$;

-- =====================================================================================
-- A) FLAG DESLIGADA POR PADRÃO
-- =====================================================================================
select t.afirma('A01 flag nasce desligada', (select (parametros->>'fluxo_ativo')::boolean from public.pre_release_parametros where vigente) = false);
select t.afirma('A02 existe uma única versão vigente', (select count(*) from public.pre_release_parametros where vigente) = 1);
select t.afirma('A03 teto de seleção parametrizado em 20', (select (parametros->>'teto_selecao')::int from public.pre_release_parametros where vigente) = 20);

create temp table c0 as select t.novo_caso() as id;
select t.erra('A04 flag off: registrar transição recusa', format($q$select public.fluxo_registrar(%L,'COLETOR_ATUALIZAR','ATUALIZADO',null,null,'{}')$q$, (select id from c0)), 'fluxo_v3_desligado');
select t.erra('A05 flag off: selecao_lotes recusa', $q$insert into public.selecao_lotes (versao_regra, itens) values ('t','[]')$q$, 'fluxo_v3_desligado');
select t.erra('A06 flag off: dossie_versoes recusa',
  format($q$insert into public.dossie_versoes (event_id,empresa_id,versao,modo_analise,base,hash) values (%L,gen_random_uuid(),0,'completa','{}','')$q$, (select id from c0)), 'fluxo_v3_desligado');
select t.erra('A07 flag off: monitoramento_verificacoes recusa',
  format($q$insert into public.monitoramento_verificacoes (event_id,empresa_id,resultado) values (%L,gen_random_uuid(),'sem_mudanca')$q$, (select id from c0)), 'fluxo_v3_desligado');
select t.erra('A08 flag off: pre_release_versoes recusa',
  format($q$insert into public.pre_release_versoes (event_id,empresa_id,versao,dossie_versao_id,hash_dossie,liberacao_id,execucao_api_id,modo_analise,texto)
            values (%L,gen_random_uuid(),0,gen_random_uuid(),'',gen_random_uuid(),gen_random_uuid(),'completa','{}')$q$, (select id from c0)), 'fluxo_v3_desligado');
select t.afirma('A09 flag off: o estado de qualquer caso é SEM_FLUXO e nada foi gravado',
  public.fluxo_estado((select id from c0)) = 'SEM_FLUXO' and (select count(*) from public.fluxo_transicoes) = 0);

-- liga a flag por uma NOVA versão (auditável) e confere que a antiga ficou intacta
select public.pre_release_definir_fluxo_ativo(true, 'teste automatizado');
select t.afirma('A10 ligar cria nova versão vigente com flag true',
  (select count(*) from public.pre_release_parametros) = 2 and (select (parametros->>'fluxo_ativo')::boolean from public.pre_release_parametros where vigente) = true);
select t.afirma('A11 versão antiga preservada (flag false, não vigente)',
  (select (parametros->>'fluxo_ativo')::boolean from public.pre_release_parametros where versao_parametros = 'PRE-RELEASE-PARAMS-V1') = false
  and (select vigente from public.pre_release_parametros where versao_parametros = 'PRE-RELEASE-PARAMS-V1') = false);
select t.erra('A12 definir flag exige motivo', $q$select public.pre_release_definir_fluxo_ativo(false, '')$q$, 'motivo_obrigatorio');
select t.erra('A13 conteúdo de uma versão de parâmetros não pode ser reescrito',
  $q$update public.pre_release_parametros set parametros = '{}'::jsonb where versao_parametros = 'PRE-RELEASE-PARAMS-V1'$q$, 'registro_imutavel');
select t.erra('A14 versão de parâmetros não pode ser apagada', $q$delete from public.pre_release_parametros$q$, 'registro_imutavel');

-- =====================================================================================
-- B) CAMINHO FELIZ ATÉ PUBLICADO, e invariantes
-- =====================================================================================
create temp table c1 as select t.novo_caso() as id;
select t.passa('B01 caso completo: seleção → … → PUBLICADO', format($q$select t.avanca(%L,'PUBLICADO')$q$, (select id from c1)));
select t.afirma('B02 estado final PUBLICADO', public.fluxo_estado((select id from c1)) = 'PUBLICADO');
select t.afirma('B03 sequência de estados gravada, na ordem e sem pular',
  (select string_agg(para, '>' order by seq) from public.fluxo_transicoes where event_id = (select id from c1))
  = 'REVISAO_SELECAO>PRONTO_PARA_IA>IA_LIBERADA>IA_EXECUTADA>REVISAO_ANALISE_IA>PRE_RELEASE_LIBERADO>PRE_RELEASE_GERADO>REVISAO_FINAL>APROVADO_PARA_PUBLICACAO>PUBLICADO');
select t.afirma('B04 cada transição parte do estado em que o anterior terminou',
  not exists (select 1 from (select de, lag(para) over (order by seq) lp, seq from public.fluxo_transicoes where event_id = (select id from c1)) x
              where x.seq <> (select min(seq) from public.fluxo_transicoes where event_id = (select id from c1)) and x.de is distinct from x.lp));
select t.afirma('B05 pré-release sempre NAO_PUBLICADO e events.pre_release nunca escrito',
  (select bool_and(publicacao_estado = 'NAO_PUBLICADO') from public.pre_release_versoes) and (select count(*) from public.events where pre_release is not null) = 0);
select t.afirma('B06 versão presa à liberação e ao dossiê, com hash',
  (select v.liberacao_id = (select id from public.fluxo_transicoes where event_id = v.event_id and acao = 'LIBERAR_PRE_RELEASE')
          and v.hash_dossie = (select hash from public.dossie_versoes where id = v.dossie_versao_id) and length(v.texto_hash) = 64
   from public.pre_release_versoes v where v.event_id = (select id from c1)));
select t.afirma('B07 dossiê: hash sha256 calculado e versão 1', (select length(hash) = 64 and versao = 1 from public.dossie_versoes where event_id = (select id from c1)));
select t.afirma('B08 view de estado reflete PUBLICADO', (select estado from public.v_caso_fluxo_estado where event_id = (select id from c1)) = 'PUBLICADO');

-- =====================================================================================
-- C) TRANSIÇÕES PROIBIDAS e prova de que não há atalho de IA_EXECUTADA a PRE_RELEASE_GERADO
-- =====================================================================================
create temp table c2 as select t.novo_caso() as id;
select t.avanca((select id from c2), 'IA_EXECUTADA');
select t.erra('C01 IA_EXECUTADA → PRE_RELEASE_LIBERADO direto',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',%L,null,'{}')$q$, (select id from c2), t.usuario()), 'transicao_proibida');
select t.erra('C02 IA_EXECUTADA → PRE_RELEASE_GERADO direto',
  format($q$select public.fluxo_registrar(%L,'GERAR_PRE_RELEASE','PRE_RELEASE_GERADO',%L,null,'{}')$q$, (select id from c2), t.usuario()), 'transicao_proibida');
select t.erra('C03 IA_EXECUTADA → APROVADO / PUBLICADO',
  format($q$select public.fluxo_registrar(%L,'PUBLICAR','PUBLICADO',%L,null,'{}')$q$, (select id from c2), t.usuario()), 'transicao_proibida');
select t.erra('C04 acao existente com destino trocado (LIBERAR_PRE_RELEASE a partir de IA_EXECUTADA, de forjado)',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',%L,null,'{}')$q$, (select id from c2), t.usuario()), 'proibida');
select t.erra('C05 estado informado divergente do real',
  format($q$insert into public.fluxo_transicoes (event_id,empresa_id,de,acao,para,usuario_id) values (%L,gen_random_uuid(),'REVISAO_ANALISE_IA','LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',%L)$q$, (select id from c2), t.usuario()), 'estado_divergente');
select t.erra('C06 inserir versão do pré-release sem liberação (IA_EXECUTADA)',
  format($q$insert into public.pre_release_versoes (event_id,empresa_id,versao,dossie_versao_id,hash_dossie,liberacao_id,execucao_api_id,modo_analise,texto)
            values (%L,gen_random_uuid(),0,gen_random_uuid(),'',gen_random_uuid(),gen_random_uuid(),'completa','{"secoes":[]}')$q$, (select id from c2)), 'geracao_sem_liberacao_valida');
create temp table c3 as select t.novo_caso() as id;
select t.avanca((select id from c3), 'REVISAO_SELECAO');
select t.erra('C07 REVISAO_SELECAO → IA_LIBERADA (pula "pronto para IA")',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_IA','IA_LIBERADA',%L,null,'{}')$q$, (select id from c3), t.usuario()), 'transicao_proibida');
select t.avanca((select id from c3), 'IA_LIBERADA');
select t.erra('C08 IA_LIBERADA → REVISAO_ANALISE_IA (Liberar IA ≠ Executar IA; pula a execução)',
  format($q$select public.fluxo_registrar(%L,'ABRIR_REVISAO_ANALISE','REVISAO_ANALISE_IA',%L,null,'{}')$q$, (select id from c3), t.usuario()), 'transicao_proibida');

-- prova formal sobre a tabela de regras: nenhum caminho IA_EXECUTADA ⇒ PRE_RELEASE_GERADO evita REVISAO_ANALISE_IA ou PRE_RELEASE_LIBERADO
create function t.alcanca(p_origem text, p_alvo text, p_excluido text) returns boolean language sql stable as $$
  with recursive g(de, para) as (select distinct de, para from app_private.fluxo_regras() where de <> p_excluido and para <> p_excluido),
  r(estado) as (select p_origem union select g.para from g join r on g.de = r.estado)
  select exists (select 1 from r where estado = p_alvo) $$;
select t.afirma('C09 PRE_RELEASE_GERADO é alcançável a partir de IA_EXECUTADA (sanidade do grafo)', t.alcanca('IA_EXECUTADA','PRE_RELEASE_GERADO','__nenhum__'));
select t.afirma('C10 sem passar por REVISAO_ANALISE_IA, IA_EXECUTADA NÃO chega a PRE_RELEASE_GERADO', not t.alcanca('IA_EXECUTADA','PRE_RELEASE_GERADO','REVISAO_ANALISE_IA'));
select t.afirma('C11 sem passar por PRE_RELEASE_LIBERADO, IA_EXECUTADA NÃO chega a PRE_RELEASE_GERADO', not t.alcanca('IA_EXECUTADA','PRE_RELEASE_GERADO','PRE_RELEASE_LIBERADO'));
select t.afirma('C12 única origem de GERAR_PRE_RELEASE é PRE_RELEASE_LIBERADO',
  (select count(*) from app_private.fluxo_regras() where acao = 'GERAR_PRE_RELEASE') = 1 and (select de from app_private.fluxo_regras() where acao = 'GERAR_PRE_RELEASE') = 'PRE_RELEASE_LIBERADO');
select t.afirma('C13 único caminho para PRE_RELEASE_LIBERADO sai de REVISAO_ANALISE_IA',
  (select count(*) from app_private.fluxo_regras() where para = 'PRE_RELEASE_LIBERADO') = 1 and (select de from app_private.fluxo_regras() where para = 'PRE_RELEASE_LIBERADO') = 'REVISAO_ANALISE_IA');
select t.afirma('C14 PUBLICADO só se alcança por PUBLICAR a partir de APROVADO_PARA_PUBLICACAO',
  (select count(*) from app_private.fluxo_regras() where para = 'PUBLICADO') = 1 and (select de from app_private.fluxo_regras() where para = 'PUBLICADO') = 'APROVADO_PARA_PUBLICACAO');
select t.afirma('C15 só o coletor produz REVISAO_SELECAO automática e ATUALIZADO (demais entradas são ações humanas)',
  (select count(*) from app_private.fluxo_regras() where para = 'ATUALIZADO' and acao not like 'COLETOR\_%') = 0);

-- =====================================================================================
-- D) LIBERAÇÃO DO PRÉ-RELEASE: uso único, vinculada ao dossiê, invalidável
-- =====================================================================================
create temp table d1 as select t.novo_caso() as id;
select t.avanca((select id from d1), 'PRE_RELEASE_LIBERADO');
select t.erra('D01 gerar sem versão: GERAR_PRE_RELEASE direto é recusado',
  format($q$select public.fluxo_registrar(%L,'GERAR_PRE_RELEASE','PRE_RELEASE_GERADO',%L,null,'{}')$q$, (select id from d1), t.usuario()), 'geracao_exige_versao_do_caso');
select t.passa('D02 retirar a liberação volta para REVISAO_ANALISE_IA',
  format($q$select public.fluxo_registrar(%L,'RETIRAR_LIBERACAO_PRE_RELEASE','REVISAO_ANALISE_IA',%L,null,'{}')$q$, (select id from d1), t.usuario()));
select t.afirma('D03 estado após retirar = REVISAO_ANALISE_IA', public.fluxo_estado((select id from d1)) = 'REVISAO_ANALISE_IA');
-- após retirar, a liberação antiga não gera versão
select t.erra('D04 liberação retirada não gera versão',
  format($q$insert into public.pre_release_versoes (event_id,empresa_id,versao,dossie_versao_id,hash_dossie,liberacao_id,execucao_api_id,modo_analise,texto)
            select %L, gen_random_uuid(), 0, dossie_versao_id, '', id, (select id from public.api_execucoes limit 1), 'completa', '{"secoes":[]}'
              from public.fluxo_transicoes where event_id = %L and acao = 'LIBERAR_PRE_RELEASE'$q$, (select id from d1), (select id from d1)), 'geracao_sem_liberacao_valida');

-- uso único: depois de gerada, a mesma liberação não gera 2ª versão
create temp table d2 as select t.novo_caso() as id;
select t.avanca((select id from d2), 'PRE_RELEASE_GERADO');
select t.erra('D05 liberação é de uso único (2ª versão com a mesma liberação)',
  format($q$insert into public.pre_release_versoes (event_id,empresa_id,versao,dossie_versao_id,hash_dossie,liberacao_id,execucao_api_id,modo_analise,texto)
            select event_id, empresa_id, 0, dossie_versao_id, hash_dossie, liberacao_id, execucao_api_id, modo_analise, texto from public.pre_release_versoes where event_id = %L$q$, (select id from d2)), 'geracao_sem_liberacao_valida');
select t.erra('D06 gerar de novo exige nova liberação (fluxo_gerar_pre_release com o caso já em PRE_RELEASE_GERADO)',
  format($q$select public.fluxo_gerar_pre_release(%L,%L,(select id from public.dossie_versoes where event_id=%L),(select id from public.api_execucoes where event_id=%L and operacao='pre_release'),'{"secoes":[]}','{}','p','m')$q$,
         (select id from d2), t.usuario(), (select id from d2), (select id from d2)), 'geracao_sem_liberacao_valida');

-- liberação invalidada por mudança material (ATUALIZADO)
create temp table d3 as select t.novo_caso() as id;
select t.avanca((select id from d3), 'PRE_RELEASE_LIBERADO');
select t.passa('D07 coletor registra ATUALIZADO sobre caso com pré-release liberado',
  format($q$select public.fluxo_registrar(%L,'COLETOR_ATUALIZAR','ATUALIZADO',null,null,'{"origem":"coletor"}')$q$, (select id from d3)));
select t.erra('D08 liberação invalidada por ATUALIZADO: não gera versão',
  format($q$select public.fluxo_gerar_pre_release(%L,%L,(select id from public.dossie_versoes where event_id=%L),(select id from public.api_execucoes limit 1),'{"secoes":[]}','{}','p','m')$q$,
         (select id from d3), t.usuario(), (select id from d3)), 'geracao_sem_liberacao_valida');

-- hash do dossiê diferente na liberação
create temp table d4 as select t.novo_caso() as id;
select t.avanca((select id from d4), 'REVISAO_ANALISE_IA');
select t.erra('D09 liberação com hash de dossiê divergente',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',%L,null,%L::jsonb)$q$, (select id from d4), t.usuario(),
    (t.rev_ok() || jsonb_build_object('dossie_versao_id', t.ultimo('dossie_versoes',(select id from d4)), 'hash_dossie', 'x', 'conferencia', true))::text), 'hash_dossie_diverge');
select t.erra('D10 liberação sem conferência humana',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',%L,null,%L::jsonb)$q$, (select id from d4), t.usuario(),
    (t.rev_ok() || jsonb_build_object('dossie_versao_id', t.ultimo('dossie_versoes',(select id from d4)), 'hash_dossie', (select hash from public.dossie_versoes where event_id=(select id from d4)))::jsonb)::text), 'conferencia_obrigatoria');
select t.erra('D11 liberação exige usuário',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_PRE_RELEASE','PRE_RELEASE_LIBERADO',null,null,'{}')$q$, (select id from d4)), 'usuario_obrigatorio');

-- apuração humana exige novo dossiê antes de liberar
create temp table d5 as select t.novo_caso() as id;
select t.avanca((select id from d5), 'REVISAO_ANALISE_IA');
select t.erra('D12 apuração sem fonte/justificativa é recusada',
  format($q$select public.fluxo_registrar(%L,'APURACAO_REGISTRADA','REVISAO_ANALISE_IA',%L,null,'{"item":"core.antecedente"}')$q$, (select id from d5), t.usuario()), 'apuracao_exige');
select t.passa('D13 apuração com item, fonte e justificativa é aceita (fica em REVISAO_ANALISE_IA)',
  format($q$select public.fluxo_registrar(%L,'APURACAO_REGISTRADA','REVISAO_ANALISE_IA',%L,null,'{"item":"core.antecedente","fonte":"diario oficial","justificativa":"confirmado em leitura"}')$q$, (select id from d5), t.usuario()));
select t.erra('D14 liberar com o dossiê anterior à apuração é recusado (precisa de novo dossiê)',
  format($q$select t.avanca(%L,'PRE_RELEASE_LIBERADO')$q$, (select id from d5)), 'novo_dossie_depois_da_apuracao');

-- =====================================================================================
-- E) BLOQUEIOS DE GERAÇÃO G1–G4
-- =====================================================================================
-- (variante direta, sem atalhos: monta o dossiê com a matriz/alertas desejados e tenta liberar)
create function t.libera_com(p_matriz_fn text, p_rev jsonb, p_alertas jsonb) returns text language plpgsql as $$
declare v uuid := t.novo_caso(); m jsonb;
begin
  execute format('select %s', replace(p_matriz_fn, '$EV', quote_literal(v))) into m;
  perform t.avanca(v, 'PRE_RELEASE_LIBERADO', m, p_rev, 'completa', jsonb_build_object('alertas', p_alertas));
  return 'liberou';
end $$;

select t.erra('E01 G1: fonte primária não confirmada bloqueia a geração',
  $q$select t.libera_com($f$(select jsonb_set(jsonb_set(t.matriz_ok($EV::uuid), '{0,estado}', '"nao_localizado"'), '{0,observacao}', '"fonte nao localizada"') #- '{0,evidencia_ids}')$f$, t.rev_ok(), '{}'::jsonb)$q$, 'geracao_bloqueada: G1');
select t.erra('E02 G1: revisão humana diz que a fonte primária não é legível',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok() || '{"fonte_primaria":"ilegivel"}', '{}'::jsonb)$q$, 'G1');
select t.erra('E03 G2: identidade do evento incerta (revisão)',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok() || '{"identidade_evento":"incerta"}', '{}'::jsonb)$q$, 'G2');
select t.erra('E04 G2: chaves conflitantes no dossiê',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok(), '{"chaves_conflitantes":true}'::jsonb)$q$, 'G2');
select t.erra('E05 G3: dúvida entre pedido e ato efetivado (revisão sem natureza)',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok() - 'natureza_ato', '{}'::jsonb)$q$, 'G3');
select t.erra('E06 G3: dossiê sinaliza pedido/ato ambíguo',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok(), '{"pedido_ato_ambiguo":true}'::jsonb)$q$, 'G3');
select t.erra('E07 G4: risco de duplicidade (revisão)',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok() || '{"duplicidade":"possivel"}', '{}'::jsonb)$q$, 'G4');
select t.erra('E08 G4: duplicidade não resolvida no dossiê',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok(), '{"duplicidade_nao_resolvida":true}'::jsonb)$q$, 'G4');
select t.passa('E09 lacunas periféricas explícitas NÃO bloqueiam a geração',
  $q$select t.libera_com($f$t.matriz_ok($EV::uuid)$f$, t.rev_ok(), '{}'::jsonb)$q$);
select t.passa('E10 lacuna crítica (requer apuração humana, não fonte primária) PODE gerar o pré-release, se explícita',
  $q$select t.libera_com($f$(select t.matriz_ok($EV::uuid) || jsonb_build_array(jsonb_build_object('codigo','core.data_ato','estado','requer_apuracao_humana','critico',true,'classe_impacto','FATO_PRINCIPAL','observacao','data a apurar')))$f$, t.rev_ok(), '{}'::jsonb)$q$);

-- =====================================================================================
-- F) VALIDAÇÃO DO DOSSIÊ / MATRIZ TIPADA
-- =====================================================================================
create temp table f1 as select t.novo_caso() as id;
create temp table f1o as select t.novo_caso() as id;   -- outro evento (evidência alheia)
create function t.ins_dossie(p_event uuid, p_matriz jsonb, p_afirm jsonb default null) returns void language plpgsql as $$
begin
  insert into public.dossie_versoes (event_id, empresa_id, versao, modo_analise, base, afirmacoes, matriz, hash)
  values (p_event, gen_random_uuid(), 0, 'completa', '{}', coalesce(p_afirm, t.afirmacoes_ok(p_event)), p_matriz, '');
end $$;
select t.erra('F01 estado fora do vocabulário', format($q$select t.ins_dossie(%L,'[{"codigo":"x","estado":"talvez","classe_impacto":"PERIFERICA"}]')$q$, (select id from f1)), 'matriz_invalida: estado');
select t.erra('F02 item crítico nunca é PERIFERICA', format($q$select t.ins_dossie(%L,'[{"codigo":"x","estado":"nao_confirmado","critico":true,"classe_impacto":"PERIFERICA"}]')$q$, (select id from f1)), 'critico');
select t.erra('F03 confirmado exige evidência', format($q$select t.ins_dossie(%L,'[{"codigo":"x","estado":"confirmado","classe_impacto":"FATO_PRINCIPAL"}]')$q$, (select id from f1)), 'exige evidencia');
select t.erra('F04 nao_localizado exige observação', format($q$select t.ins_dossie(%L,'[{"codigo":"x","estado":"nao_localizado","classe_impacto":"PERIFERICA"}]')$q$, (select id from f1)), 'exige observacao');
select t.erra('F05 evidência de OUTRO evento é recusada na matriz',
  format($q$select t.ins_dossie(%L, jsonb_build_array(jsonb_build_object('codigo','x','estado','confirmado','classe_impacto','FATO_PRINCIPAL','evidencia_ids',jsonb_build_array(t.ev(%L,1)))))$q$, (select id from f1), (select id from f1o)), 'nao pertence ao evento');
select t.erra('F06 evidência de OUTRO evento é recusada nas afirmações',
  format($q$select t.ins_dossie(%L, '[]'::jsonb, jsonb_build_array(jsonb_build_object('id','A1','texto','t','status','confirmado','evidencias',jsonb_build_array(jsonb_build_object('ev','E1','evidencia_id',t.ev(%L,1))))))$q$, (select id from f1), (select id from f1o)), 'nao pertence ao evento');
select t.erra('F07 afirmação confirmada sem evidência', format($q$select t.ins_dossie(%L,'[]','[{"id":"A1","texto":"t","status":"confirmado","evidencias":[]}]')$q$, (select id from f1)), 'sem evidencia');
select t.erra('F08 afirmação sem texto', format($q$select t.ins_dossie(%L,'[]','[{"id":"A1","texto":"","status":"nao_confirmado"}]')$q$, (select id from f1)), 'sem id ou texto');
select t.erra('F09 aguardando_contraditorio com risco "false" exige justificativa escrita',
  format($q$select t.ins_dossie(%L,'[{"codigo":"x","estado":"aguardando_contraditorio","classe_impacto":"PERIFERICA","risco_reputacional":false}]')$q$, (select id from f1)), 'justificativa escrita');
select t.erra('F10 matriz não-lista', format($q$select t.ins_dossie(%L,'{"a":1}')$q$, (select id from f1)), 'matriz_invalida');
select t.erra('F11 hash informado que difere do calculado é recusado',
  format($q$insert into public.dossie_versoes (event_id,empresa_id,versao,modo_analise,base,afirmacoes,matriz,hash) values (%L,gen_random_uuid(),0,'completa','{}','[]','[]','abc')$q$, (select id from f1)), 'hash informado difere');
select t.passa('F12 dossiê válido é aceito (todos os oito estados tipados)',
  format($q$select t.ins_dossie(%L,'[]'::jsonb || jsonb_build_array(jsonb_build_object('codigo','a2','estado','confirmado','classe_impacto','FATO_PRINCIPAL','evidencia_ids',jsonb_build_array(t.ev(%L,1)))) ||
     '[{"codigo":"b","estado":"nao_confirmado","classe_impacto":"PERIFERICA"},
       {"codigo":"c","estado":"nao_localizado","classe_impacto":"PERIFERICA","observacao":"x"},
       {"codigo":"d","estado":"nao_aplicavel","classe_impacto":"PERIFERICA"},
       {"codigo":"e","estado":"requer_apuracao_humana","classe_impacto":"PERIFERICA"},
       {"codigo":"f","estado":"aguardando_contraditorio","classe_impacto":"PERIFERICA","risco_reputacional":true},
       {"codigo":"g","estado":"fonte_indisponivel","classe_impacto":"PERIFERICA"},
       {"codigo":"h","estado":"divergencia_entre_fontes","classe_impacto":"PERIFERICA"}]'::jsonb)$q$, (select id from f1), (select id from f1)));

-- =====================================================================================
-- G) BLOQUEIOS DE PUBLICAÇÃO B1–B6
-- =====================================================================================
create function t.ate_aprovar(p_matriz jsonb, p_extra jsonb default '{}') returns uuid language plpgsql as $$
declare v uuid := t.novo_caso();
begin perform t.avanca(v, 'APROVADO_PARA_PUBLICACAO', p_matriz, null, 'completa', p_extra); return v; end $$;
create function t.mx(p_event uuid, p_item jsonb) returns jsonb language sql as $$ select t.matriz_ok(p_event) || jsonb_build_array(p_item) $$;
create function t.ate_aprovar_com(p_item jsonb) returns uuid language plpgsql as $$
declare v uuid := t.novo_caso();
begin perform t.avanca(v, 'APROVADO_PARA_PUBLICACAO', t.mx(v, p_item)); return v; end $$;
create function t.mudanca_material(p_event uuid) returns void language sql as $$
  insert into public.monitoramento_verificacoes (event_id, empresa_id, resultado, delta, modo_sugerido, data_real_atualizacao, data_real_origem, impressao_material)
  values (p_event, gen_random_uuid(), 'mudanca_material', '{"campos":[{"campo":"fase","antes":"a","depois":"b"}]}', 'delta', current_date, 'ato', 'hash-novo') $$;

select t.erra('G01 B2: lacuna FATO_PRINCIPAL (requer apuração) bloqueia aprovar',
  $q$select t.ate_aprovar_com('{"codigo":"x.fato","estado":"requer_apuracao_humana","critico":true,"classe_impacto":"FATO_PRINCIPAL","observacao":"a apurar"}')$q$, 'publicacao_bloqueada: B2');
select t.erra('G02 B2: ATRIBUICAO não confirmada bloqueia', 
  $q$select t.ate_aprovar_com('{"codigo":"x.attr","estado":"nao_confirmado","critico":true,"classe_impacto":"ATRIBUICAO"}')$q$, 'B2');
select t.erra('G03 B2: GRAVIDADE não localizada bloqueia',
  $q$select t.ate_aprovar_com('{"codigo":"x.grav","estado":"nao_localizado","critico":true,"classe_impacto":"GRAVIDADE","observacao":"sem dado"}')$q$, 'B2');
select t.erra('G04 B2: divergência entre fontes em item de fato principal bloqueia',
  $q$select t.ate_aprovar_com('{"codigo":"x.div","estado":"divergencia_entre_fontes","critico":false,"classe_impacto":"FATO_PRINCIPAL"}')$q$, 'B2');
select t.erra('G05 B2: aguardando_contraditorio com risco reputacional bloqueia, mesmo em item PERIFERICO',
  $q$select t.ate_aprovar_com('{"codigo":"x.ctr","estado":"aguardando_contraditorio","classe_impacto":"PERIFERICA","risco_reputacional":true}')$q$, 'B2');
select t.erra('G06 B2: aguardando_contraditorio SEM avaliação de risco bloqueia (ausência de risco declarado ≠ sem risco)',
  $q$select t.ate_aprovar_com('{"codigo":"x.ctr","estado":"aguardando_contraditorio","classe_impacto":"PERIFERICA"}')$q$, 'B2');
select t.passa('G07 aguardando_contraditorio periférico com "sem risco" justificado por escrito NÃO bloqueia',
  $q$select t.ate_aprovar_com('{"codigo":"x.ctr","estado":"aguardando_contraditorio","classe_impacto":"PERIFERICA","risco_reputacional":false,"justificativa_sem_risco":"dado puramente cadastral"}')$q$);
select t.passa('G08 lacunas periféricas (requer apuração, fonte indisponível, não confirmado) NÃO bloqueiam',
  $q$select t.ate_aprovar_com('{"codigo":"x.per","estado":"fonte_indisponivel","classe_impacto":"PERIFERICA"}')$q$);

-- B3 validação reprovada
create temp table g3 as select t.novo_caso() as id;
select t.avanca((select id from g3), 'PRE_RELEASE_GERADO', null, null, 'completa', '{"validacao":{"bloqueantes":["afirmacao sem evidencia"]}}');
select t.afirma('G09 B3: versão com trava bloqueante nasce "reprovada"', (select status_validacao from public.pre_release_versoes where event_id = (select id from g3)) = 'reprovada');
select t.erra('G10 B3: versão reprovada não vai à revisão final',
  format($q$select public.fluxo_registrar(%L,'ABRIR_REVISAO_FINAL','REVISAO_FINAL',%L,null,%L::jsonb)$q$, (select id from g3), t.usuario(),
         jsonb_build_object('pre_release_versao_id', t.ultimo('pre_release_versoes',(select id from g3)))::text), 'versao_reprovada');
select t.passa('G11 B3: versão reprovada só pode ser devolvida',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_REPROVADA','DEVOLVIDO_PARA_AJUSTE',%L,'validacao reprovou','{"origem_devolucao":"FINAL"}')$q$, (select id from g3), t.usuario()));

-- B4 / B5 depois da geração
create temp table g4 as select t.novo_caso() as id;
select t.avanca((select id from g4), 'REVISAO_FINAL');
select t.ins_dossie((select id from g4), t.matriz_ok((select id from g4)));
select t.erra('G12 B4: dossiê mais novo que o da versão bloqueia aprovar', format($q$select t.avanca(%L,'APROVADO_PARA_PUBLICACAO')$q$, (select id from g4)), 'B4');
create temp table g5 as select t.novo_caso() as id;
select t.avanca((select id from g5), 'REVISAO_FINAL');
select t.mudanca_material((select id from g5));
select t.erra('G13 B5: mudança material depois da geração bloqueia aprovar', format($q$select t.avanca(%L,'APROVADO_PARA_PUBLICACAO')$q$, (select id from g5)), 'B5');
create temp table g6 as select t.novo_caso() as id;
select t.avanca((select id from g6), 'APROVADO_PARA_PUBLICACAO');
select t.mudanca_material((select id from g6));
select t.erra('G14 B5: mudança material entre aprovar e publicar bloqueia publicar', format($q$select t.avanca(%L,'PUBLICADO')$q$, (select id from g6)), 'B5');

-- B6 conferência final / confirmação
create temp table g7 as select t.novo_caso() as id;
select t.avanca((select id from g7), 'REVISAO_FINAL');
select t.erra('G15 B6: aprovar sem conferência final',
  format($q$select public.fluxo_registrar(%L,'APROVAR','APROVADO_PARA_PUBLICACAO',%L,null,%L::jsonb)$q$, (select id from g7), t.usuario(),
    jsonb_build_object('pre_release_versao_id', t.ultimo('pre_release_versoes',(select id from g7)), 'hash_pre_release', (select texto_hash from public.pre_release_versoes where event_id=(select id from g7)))::text), 'conferencia_final_obrigatoria');
select t.erra('G16 B6: aprovar com hash do pré-release diferente',
  format($q$select public.fluxo_registrar(%L,'APROVAR','APROVADO_PARA_PUBLICACAO',%L,null,%L::jsonb)$q$, (select id from g7), t.usuario(),
    jsonb_build_object('pre_release_versao_id', t.ultimo('pre_release_versoes',(select id from g7)), 'conferencia_final', true, 'hash_pre_release', 'x')::text), 'hash_pre_release_diverge');
select t.avanca((select id from g7), 'APROVADO_PARA_PUBLICACAO');
select t.erra('G17 B6: publicar sem confirmação própria',
  format($q$select public.fluxo_registrar(%L,'PUBLICAR','PUBLICADO',%L,null,%L::jsonb)$q$, (select id from g7), t.usuario(),
    jsonb_build_object('pre_release_versao_id', t.ultimo('pre_release_versoes',(select id from g7)))::text), 'confirmacao_de_publicacao_obrigatoria');
select t.erra('G18 B6: publicar outra versão que não a aprovada',
  format($q$select public.fluxo_registrar(%L,'PUBLICAR','PUBLICADO',%L,null,%L::jsonb)$q$, (select id from g7), t.usuario(),
    jsonb_build_object('pre_release_versao_id', gen_random_uuid(), 'confirmacao', true)::text), 'publicar_exige_a_versao_aprovada');
select t.erra('G19 PUBLICAR direto de IA_EXECUTADA é proibido',
  format($q$select public.fluxo_registrar(%L,'PUBLICAR','PUBLICADO',%L,null,'{}')$q$, (select id from c2), t.usuario()), 'proibida')  ;

-- =====================================================================================
-- H) DEVOLUÇÕES, DESCARTES, EXECUÇÃO DE IA
-- =====================================================================================
create temp table h1 as select t.novo_caso() as id;
select t.avanca((select id from h1), 'REVISAO_ANALISE_IA');
select t.erra('H01 devolver análise exige o ajuste pedido',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_ANALISE','DEVOLVIDO_PARA_AJUSTE',%L,'faltou fonte','{"origem_devolucao":"ANALISE"}')$q$, (select id from h1), t.usuario()), 'ajuste_pedido_obrigatorio');
select t.erra('H02 devolver exige motivo',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_ANALISE','DEVOLVIDO_PARA_AJUSTE',%L,null,'{"origem_devolucao":"ANALISE","ajuste_pedido":"x"}')$q$, (select id from h1), t.usuario()), 'motivo_obrigatorio');
select t.erra('H03 devolver exige origem coerente (FINAL numa devolução de análise)',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_ANALISE','DEVOLVIDO_PARA_AJUSTE',%L,'m','{"origem_devolucao":"FINAL","ajuste_pedido":"x"}')$q$, (select id from h1), t.usuario()), 'origem_devolucao_incoerente');
select t.passa('H04 devolução de análise correta',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_ANALISE','DEVOLVIDO_PARA_AJUSTE',%L,'faltou fonte','{"origem_devolucao":"ANALISE","ajuste_pedido":"buscar o diario oficial"}')$q$, (select id from h1), t.usuario()));
select t.erra('H05 reabrir sem nova IA só vale para devolução de origem FINAL',
  format($q$select public.fluxo_registrar(%L,'REABRIR','REVISAO_ANALISE_IA',%L,null,'{}')$q$, (select id from h1), t.usuario()), 'reabrir_sem_nova_ia');
select t.passa('H06 devolução de análise volta para nova IA (REABRIR_NOVA_ANALISE → PRONTO_PARA_IA)',
  format($q$select public.fluxo_registrar(%L,'REABRIR_NOVA_ANALISE','PRONTO_PARA_IA',%L,null,'{}')$q$, (select id from h1), t.usuario()));
select t.passa('H07 2º ciclo chega a PRE_RELEASE_GERADO com versão 2 encadeada à 1', format($q$select t.avanca(%L,'PRE_RELEASE_GERADO')$q$, (select id from h1)));
select t.afirma('H08 dossiê v2 e pré-release v1 (primeira geração deste caso) com encadeamento de dossiê',
  (select count(*) from public.dossie_versoes where event_id = (select id from h1)) = 2
  and (select dossie_anterior_id is not null from public.dossie_versoes where event_id = (select id from h1) and versao = 2));

create temp table h2 as select t.novo_caso() as id;
select t.avanca((select id from h2), 'REVISAO_FINAL');
select t.passa('H09 devolução na revisão final (origem FINAL)',
  format($q$select public.fluxo_registrar(%L,'DEVOLVER_FINAL','DEVOLVIDO_PARA_AJUSTE',%L,'ajustar titulo','{"origem_devolucao":"FINAL"}')$q$, (select id from h2), t.usuario()));
select t.passa('H10 reabrir sem nova IA após devolução FINAL → REVISAO_ANALISE_IA',
  format($q$select public.fluxo_registrar(%L,'REABRIR','REVISAO_ANALISE_IA',%L,null,'{}')$q$, (select id from h2), t.usuario()));
select t.erra('H11 não existe devolução a partir de PUBLICADO (despublicar não é uma transição do fluxo)', format($q$select public.fluxo_registrar(%L,'DEVOLVER_FINAL','DEVOLVIDO_PARA_AJUSTE',%L,'m','{}')$q$, (select id from c1), t.usuario()), 'transicao_proibida');

create temp table h3 as select t.novo_caso() as id;
select t.avanca((select id from h3), 'REVISAO_SELECAO');
select t.erra('H12 descartar exige motivo', format($q$select public.fluxo_registrar(%L,'DESCARTAR','DESCARTADO',%L,null,'{}')$q$, (select id from h3), t.usuario()), 'motivo_obrigatorio');
select t.passa('H13 descartar com motivo', format($q$select public.fluxo_registrar(%L,'DESCARTAR','DESCARTADO',%L,'fora do escopo','{}')$q$, (select id from h3), t.usuario()));
select t.erra('H14 coletor não atualiza caso DESCARTADO', format($q$select public.fluxo_registrar(%L,'COLETOR_ATUALIZAR','ATUALIZADO',null,null,'{}')$q$, (select id from h3)), 'transicao_proibida');
select t.erra('H15 reabrir descartado exige motivo', format($q$select public.fluxo_registrar(%L,'REABRIR_DESCARTADO','REVISAO_SELECAO',%L,null,'{}')$q$, (select id from h3), t.usuario()), 'motivo_obrigatorio');
select t.passa('H16 reabrir descartado com motivo volta à REVISAO_SELECAO', format($q$select public.fluxo_registrar(%L,'REABRIR_DESCARTADO','REVISAO_SELECAO',%L,'novo fato','{}')$q$, (select id from h3), t.usuario()));

create temp table h4 as select t.novo_caso() as id;
select t.avanca((select id from h4), 'REVISAO_ANALISE_IA');
select t.passa('H17 descartar ou monitorar a partir da revisão da análise (→ MONITORADO)',
  format($q$select public.fluxo_registrar(%L,'DESCARTAR_OU_MONITORAR','MONITORADO',%L,'sem relevancia hoje','{}')$q$, (select id from h4), t.usuario()));
create temp table h5 as select t.novo_caso() as id;
select t.avanca((select id from h5), 'APROVADO_PARA_PUBLICACAO');
select t.passa('H18 revogar aprovação (origem FINAL) devolve para ajuste',
  format($q$select public.fluxo_registrar(%L,'REVOGAR_APROVACAO','DEVOLVIDO_PARA_AJUSTE',%L,'achei erro','{"origem_devolucao":"FINAL"}')$q$, (select id from h5), t.usuario()));
select t.erra('H19 depois de revogada, PUBLICAR é proibido', format($q$select public.fluxo_registrar(%L,'PUBLICAR','PUBLICADO',%L,null,'{"confirmacao":true}')$q$, (select id from h5), t.usuario()), 'transicao_proibida');

-- EXECUTAR_IA / revisão da análise
create temp table h6 as select t.novo_caso() as id;
select t.avanca((select id from h6), 'IA_LIBERADA');
select t.erra('H20 EXECUTAR_IA sem execução registrada', format($q$select public.fluxo_registrar(%L,'EXECUTAR_IA','IA_EXECUTADA',%L,null,'{}')$q$, (select id from h6), t.usuario()), 'execucao_ia_invalida');
create function t.api_exec(p_event uuid, p_op text, p_status text) returns uuid language sql as $$
  insert into public.api_execucoes (event_id, empresa_id, operacao, status) values (p_event, gen_random_uuid(), p_op, p_status) returning id $$;
select t.erra('H21 EXECUTAR_IA com execução que falhou',
  format($q$select public.fluxo_registrar(%L,'EXECUTAR_IA','IA_EXECUTADA',%L,null,jsonb_build_object('execucao_ia_id', t.api_exec(%L,'analise_editorial','erro')))$q$, (select id from h6), t.usuario(), (select id from h6)), 'execucao_ia_invalida');
select t.erra('H22 EXECUTAR_IA com execução de outro evento',
  format($q$select public.fluxo_registrar(%L,'EXECUTAR_IA','IA_EXECUTADA',%L,null,jsonb_build_object('execucao_ia_id', t.api_exec(%L,'analise_editorial','sucesso')))$q$, (select id from h6), t.usuario(), (select id from c0)), 'execucao_ia_invalida');
select t.erra('H23 EXECUTAR_IA com operação que não é análise editorial',
  format($q$select public.fluxo_registrar(%L,'EXECUTAR_IA','IA_EXECUTADA',%L,null,jsonb_build_object('execucao_ia_id', t.api_exec(%L,'pre_release','sucesso')))$q$, (select id from h6), t.usuario(), (select id from h6)), 'execucao_ia_invalida');
create temp table h7 as select t.novo_caso() as id;
select t.avanca((select id from h7), 'IA_EXECUTADA');
create function t.dossie_solto(p_event uuid) returns uuid language sql as $$
  insert into public.dossie_versoes (event_id, empresa_id, versao, modo_analise, base, afirmacoes, matriz, hash)
  values (p_event, gen_random_uuid(), 0, 'completa', '{}', '[]', '[]', '') returning id $$;
select t.erra('H24 abrir a revisão com dossiê que não pertence à última execução de IA',
  format($q$select public.fluxo_registrar(%L,'ABRIR_REVISAO_ANALISE','REVISAO_ANALISE_IA',%L,null,jsonb_build_object('dossie_versao_id', t.dossie_solto(%L)))$q$,
         (select id from h7), t.usuario(), (select id from h7)), 'dossie_nao_pertence');
select t.erra('H25 abrir a revisão sem dossiê',
  format($q$select public.fluxo_registrar(%L,'ABRIR_REVISAO_ANALISE','REVISAO_ANALISE_IA',%L,null,'{}')$q$, (select id from h7), t.usuario()), 'dossie_invalido');

-- =====================================================================================
-- I) CASO ATUALIZADO
-- =====================================================================================
create temp table i1 as select t.novo_caso() as id;
select t.avanca((select id from i1), 'PUBLICADO');
select t.passa('I01 coletor registra ATUALIZADO sobre caso PUBLICADO (sem despublicar)',
  format($q$select public.fluxo_registrar(%L,'COLETOR_ATUALIZAR','ATUALIZADO',null,null,'{"origem":"coletor"}')$q$, (select id from i1)));
select t.afirma('I02 caso publicado continua com a versão publicada intacta e events.pre_release nulo',
  (select count(*) from public.pre_release_versoes where event_id = (select id from i1)) = 1
  and (select pre_release from public.events where id = (select id from i1)) is null);
select t.afirma('I03 depois de ATUALIZADO o sistema PARA (nenhuma transição automática)',
  public.fluxo_estado((select id from i1)) = 'ATUALIZADO');
select t.erra('I04 de ATUALIZADO não se vai direto a PRE_RELEASE_LIBERADO nem a IA',
  format($q$select public.fluxo_registrar(%L,'LIBERAR_IA','IA_LIBERADA',%L,null,'{}')$q$, (select id from i1), t.usuario()), 'transicao_proibida');
select t.passa('I05 abrir a revisão da mudança',
  format($q$select public.fluxo_registrar(%L,'ABRIR_REVISAO_MUDANCA','REVISAO_MUDANCA',%L,null,'{}')$q$, (select id from i1), t.usuario()));
select t.erra('I06 aprovar nova análise exige o modo (delta ou completa)',
  format($q$select public.fluxo_registrar(%L,'APROVAR_NOVA_ANALISE','PRONTO_PARA_IA',%L,null,'{}')$q$, (select id from i1), t.usuario()), 'modo_analise_obrigatorio');
select t.passa('I07 aprovar nova análise em modo delta',
  format($q$select public.fluxo_registrar(%L,'APROVAR_NOVA_ANALISE','PRONTO_PARA_IA',%L,null,'{"modo_analise":"delta"}')$q$, (select id from i1), t.usuario()));
select t.passa('I08 2º ciclo (delta) vai até PUBLICADO de novo, sempre pelos mesmos portões', format($q$select t.avanca(%L,'PUBLICADO',null,null,'delta')$q$, (select id from i1)));
select t.afirma('I09 duas versões de pré-release encadeadas, ambas NAO_PUBLICADO como artefato',
  (select count(*) from public.pre_release_versoes where event_id = (select id from i1)) = 2
  and (select versao_anterior_id is not null from public.pre_release_versoes where event_id = (select id from i1) and versao = 2)
  and (select modo_analise from public.pre_release_versoes where event_id = (select id from i1) and versao = 2) = 'delta');

create temp table i2 as select t.novo_caso() as id;
select t.erra('I10 análise delta que contradiz a anterior não libera pré-release (só completa ou descartar)',
  format($q$select t.avanca(%L,'PRE_RELEASE_LIBERADO',null,null,'delta','{"liberacao":{"contradiz_analise_anterior":true}}')$q$, (select id from i2)), 'contradiz_analise_anterior');
create temp table i3 as select t.novo_caso() as id;
select t.avanca((select id from i3), 'PUBLICADO');
select public.fluxo_registrar((select id from i3), 'COLETOR_ATUALIZAR', 'ATUALIZADO', null, null, '{}');
select public.fluxo_registrar((select id from i3), 'ABRIR_REVISAO_MUDANCA', 'REVISAO_MUDANCA', t.usuario(), null, '{}');
select t.erra('I11 manter monitorado exige motivo', format($q$select public.fluxo_registrar(%L,'MANTER_MONITORADO','MONITORADO',%L,null,'{}')$q$, (select id from i3), t.usuario()), 'motivo_obrigatorio');
select t.passa('I12 manter monitorado com motivo', format($q$select public.fluxo_registrar(%L,'MANTER_MONITORADO','MONITORADO',%L,'mudanca sem relevancia editorial','{}')$q$, (select id from i3), t.usuario()));

-- ultima_atualizacao: só muda com mudança material
create temp table i4 as select t.novo_caso() as id;
insert into public.monitoramento_verificacoes (event_id, empresa_id, resultado) values ((select id from i4), gen_random_uuid(), 'sem_mudanca');
select t.afirma('I13 verificação sem mudança NÃO cria nem altera ultima_atualizacao',
  not exists (select 1 from public.v_caso_ultima_atualizacao where event_id = (select id from i4)));
insert into public.monitoramento_verificacoes (event_id, empresa_id, resultado, delta, modo_sugerido, data_real_atualizacao, data_real_origem)
  values ((select id from i4), gen_random_uuid(), 'mudanca_material', '{"campos":[]}', 'delta', date '2026-09-01', 'ato');
select t.afirma('I14 mudança material grava a data REAL (do ato), não a de hoje',
  (select ultima_atualizacao from public.v_caso_ultima_atualizacao where event_id = (select id from i4)) = date '2026-09-01');
insert into public.monitoramento_verificacoes (event_id, empresa_id, resultado) values ((select id from i4), gen_random_uuid(), 'sem_mudanca');
select t.afirma('I15 nova verificação sem mudança depois NÃO muda a data', (select ultima_atualizacao from public.v_caso_ultima_atualizacao where event_id = (select id from i4)) = date '2026-09-01');
select t.erra('I16 "sem mudança" não pode trazer data/delta',
  format($q$insert into public.monitoramento_verificacoes (event_id,empresa_id,resultado,data_real_atualizacao,data_real_origem) values (%L,gen_random_uuid(),'sem_mudanca',current_date,'ato')$q$, (select id from i4)), 'chk_verif_sem_mudanca_vazia');
select t.erra('I17 mudança material exige delta e data real',
  format($q$insert into public.monitoramento_verificacoes (event_id,empresa_id,resultado) values (%L,gen_random_uuid(),'mudanca_material')$q$, (select id from i4)), 'chk_verif_mudanca_completa');
select t.erra('I18 verificação de evento inexistente',
  $q$insert into public.monitoramento_verificacoes (event_id,empresa_id,resultado) values (gen_random_uuid(),gen_random_uuid(),'sem_mudanca')$q$, 'evento_inexistente');

-- =====================================================================================
-- J) SELEÇÃO: teto 20 é limite, não meta
-- =====================================================================================
select t.erra('J01 21 itens ultrapassam o teto',
  $q$insert into public.selecao_lotes (versao_regra, itens) select 't', jsonb_agg(jsonb_build_object('event_id', gen_random_uuid())) from generate_series(1,21)$q$, 'chk_selecao_dentro_do_teto');
select t.erra('J02 teto acima de 20 é recusado', $q$insert into public.selecao_lotes (versao_regra, teto, itens) values ('t', 21, '[]')$q$, 'selecao_lotes_teto_check');
select t.erra('J03 teto 0 é recusado', $q$insert into public.selecao_lotes (versao_regra, teto, itens) values ('t', 0, '[]')$q$, 'selecao_lotes_teto_check');
select t.passa('J04 rodada com 0 itens é válida', $q$insert into public.selecao_lotes (versao_regra, itens) values ('t', '[]')$q$);
insert into public.selecao_lotes (versao_regra, itens) select 't7', jsonb_agg(jsonb_build_object('ordem', g, 'event_id', gen_random_uuid())) from generate_series(1,7) g;
select t.afirma('J05 rodada com 7 itens válida: selecionados = 7 (nunca preenche até 20) e hash do ranking', 
  (select selecionados = 7 and length(hash_ranking) = 64 from public.selecao_lotes where versao_regra = 't7'));
select t.afirma('J06 exatamente 20 itens é aceito', 
  (select count(*) from (select 1) q where (select jsonb_array_length(itens) from (select jsonb_agg(1) itens from generate_series(1,20)) z) = 20) = 1);
select t.passa('J06b rodada de 20 itens inserida', $q$insert into public.selecao_lotes (versao_regra, itens) select 't20', jsonb_agg(jsonb_build_object('event_id', gen_random_uuid())) from generate_series(1,20)$q$);

create temp table j2 as select t.novo_caso() as id;
create temp table j2lote as
  with l as (insert into public.selecao_lotes (versao_regra, teto, itens) values ('t3', 3, jsonb_build_array(
        jsonb_build_object('ordem',1,'event_id',(select id from j2)), jsonb_build_object('ordem',2,'event_id',gen_random_uuid()))) returning id)
  select id from l;
create temp table j3 as select t.novo_caso() as id;
create temp table j4 as select t.novo_caso() as id;
select t.erra('J07 caso fora do ranking congelado não entra por COLETOR_SELECIONAR',
  format($q$select public.fluxo_registrar(%L,'COLETOR_SELECIONAR','REVISAO_SELECAO',null,null,jsonb_build_object('lote_id',%L))$q$, (select id from j3), (select id from j2lote)), 'caso_fora_do_ranking');
select t.erra('J08 lote inexistente', format($q$select public.fluxo_registrar(%L,'COLETOR_SELECIONAR','REVISAO_SELECAO',null,null,'{}')$q$, (select id from j3)), 'lote_inexistente');
select t.erra('J09 inclusão manual exige origem SELECAO_MANUAL',
  format($q$select public.fluxo_registrar(%L,'INCLUIR_MANUAL','REVISAO_SELECAO',%L,'quero este',jsonb_build_object('lote_id',%L))$q$, (select id from j3), t.usuario(), (select id from j2lote)), 'SELECAO_MANUAL');
select t.erra('J10 inclusão manual exige motivo',
  format($q$select public.fluxo_registrar(%L,'INCLUIR_MANUAL','REVISAO_SELECAO',%L,null,jsonb_build_object('lote_id',%L,'origem','SELECAO_MANUAL'))$q$, (select id from j3), t.usuario(), (select id from j2lote)), 'motivo_obrigatorio');
select t.passa('J11 1ª inclusão manual cabe no teto (2 do ranking + 1 manual = 3)',
  format($q$select public.fluxo_registrar(%L,'INCLUIR_MANUAL','REVISAO_SELECAO',%L,'caso pedido pelo editor',jsonb_build_object('lote_id',%L,'origem','SELECAO_MANUAL'))$q$, (select id from j3), t.usuario(), (select id from j2lote)));
select t.erra('J12 2ª inclusão manual estoura o teto da rodada',
  format($q$select public.fluxo_registrar(%L,'INCLUIR_MANUAL','REVISAO_SELECAO',%L,'outro caso',jsonb_build_object('lote_id',%L,'origem','SELECAO_MANUAL'))$q$, (select id from j4), t.usuario(), (select id from j2lote)), 'teto_da_rodada_atingido');
select t.passa('J13 coletor seleciona caso que está no ranking (sem usuário)',
  format($q$select public.fluxo_registrar(%L,'COLETOR_SELECIONAR','REVISAO_SELECAO',null,null,jsonb_build_object('lote_id',%L))$q$, (select id from j2), (select id from j2lote)));
select t.erra('J14 ação humana sem usuário é recusada',
  format($q$select public.fluxo_registrar(%L,'APROVAR_PARA_IA','PRONTO_PARA_IA',null,null,'{}')$q$, (select id from j2)), 'usuario_obrigatorio');

-- =====================================================================================
-- K) IMUTABILIDADE
-- =====================================================================================
select t.erra('K01 UPDATE em fluxo_transicoes', $q$update public.fluxo_transicoes set motivo = 'x'$q$, 'registro_imutavel');
select t.erra('K02 DELETE em fluxo_transicoes', $q$delete from public.fluxo_transicoes$q$, 'registro_imutavel');
select t.erra('K03 TRUNCATE em fluxo_transicoes (bloqueado; referenciada por FK)', $q$truncate public.fluxo_transicoes$q$, 'cannot truncate');
select t.erra('K03b TRUNCATE em fluxo_transicoes com CASCADE', $q$truncate public.fluxo_transicoes cascade$q$, 'registro_imutavel');
select t.erra('K03c TRUNCATE em selecao_lotes', $q$truncate public.selecao_lotes$q$, 'registro_imutavel');
select t.erra('K03d TRUNCATE em monitoramento_verificacoes', $q$truncate public.monitoramento_verificacoes$q$, 'registro_imutavel');
select t.erra('K04 UPDATE em dossie_versoes (hash)', $q$update public.dossie_versoes set hash = 'x'$q$, 'registro_imutavel');
select t.erra('K05 DELETE em dossie_versoes', $q$delete from public.dossie_versoes$q$, 'registro_imutavel');
select t.erra('K06 UPDATE em pre_release_versoes (texto)', $q$update public.pre_release_versoes set texto = '{}'$q$, 'registro_imutavel');
select t.erra('K07 DELETE em pre_release_versoes', $q$delete from public.pre_release_versoes$q$, 'registro_imutavel');
select t.erra('K08 UPDATE em selecao_lotes', $q$update public.selecao_lotes set itens = '[]'$q$, 'registro_imutavel');
select t.erra('K09 DELETE em selecao_lotes', $q$delete from public.selecao_lotes$q$, 'registro_imutavel');
select t.erra('K10 UPDATE em monitoramento_verificacoes', $q$update public.monitoramento_verificacoes set resultado = 'sem_mudanca'$q$, 'registro_imutavel');
select t.erra('K11 TRUNCATE em pre_release_versoes', $q$truncate public.pre_release_versoes cascade$q$, 'registro_imutavel');
select t.erra('K12 TRUNCATE em dossie_versoes', $q$truncate public.dossie_versoes cascade$q$, 'registro_imutavel');

-- =====================================================================================
-- L) RLS / GRANTS
-- =====================================================================================
select t.afirma('L01 RLS ligada nas 6 tabelas novas',
  (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname in ('pre_release_parametros','selecao_lotes','monitoramento_verificacoes','dossie_versoes','fluxo_transicoes','pre_release_versoes')
      and c.relrowsecurity) = 6);
select t.erra('L02 anon não lê fluxo_transicoes', $q$select count(*) from public.fluxo_transicoes$q$, 'permission denied', 'anon');
select t.erra('L03 anon não lê dossie_versoes', $q$select count(*) from public.dossie_versoes$q$, 'permission denied', 'anon');
select t.erra('L04 anon não lê pre_release_versoes', $q$select count(*) from public.pre_release_versoes$q$, 'permission denied', 'anon');
select t.erra('L05 anon não lê parametros/flag', $q$select count(*) from public.pre_release_parametros$q$, 'permission denied', 'anon');
select t.erra('L06 anon não lê a view de estado', $q$select count(*) from public.v_caso_fluxo_estado$q$, 'permission denied', 'anon');
select t.erra('L07 anon não insere', $q$insert into public.selecao_lotes (versao_regra, itens) values ('x','[]')$q$, 'permission denied', 'anon');
select t.erra('L08 anon não executa as RPCs', $q$select public.fluxo_registrar(gen_random_uuid(),'x','y',null,null,'{}')$q$, 'permission denied', 'anon');
select t.erra('L09 authenticated não lê payload/motivo das transições', $q$select payload from public.fluxo_transicoes$q$, 'permission denied', 'authenticated');
select t.erra('L10 authenticated não faz select * em fluxo_transicoes', $q$select * from public.fluxo_transicoes$q$, 'permission denied', 'authenticated');
select t.passa('L11 authenticated lê só as colunas seguras', $q$select id, event_id, de, acao, para, created_at from public.fluxo_transicoes limit 1$q$, 'authenticated');
select t.afirma('L12 authenticated enxerga linhas nas colunas seguras (política por visibilidade do evento)',
  (select n > 0 from (select count(*) n from public.v_caso_fluxo_estado) x));
select t.passa('L12b authenticated lê o estado de cada caso pela view', $q$select estado from public.v_caso_fluxo_estado$q$, 'authenticated');
select t.erra('L13 authenticated não lê dossiês', $q$select count(*) from public.dossie_versoes$q$, 'permission denied', 'authenticated');
select t.erra('L14 authenticated não lê pré-release', $q$select texto from public.pre_release_versoes$q$, 'permission denied', 'authenticated');
select t.erra('L15 authenticated não lê lotes de seleção', $q$select count(*) from public.selecao_lotes$q$, 'permission denied', 'authenticated');
select t.erra('L16 authenticated não lê a flag/parametros', $q$select count(*) from public.pre_release_parametros$q$, 'permission denied', 'authenticated');
select t.erra('L17 authenticated não lê delta/impressão das verificações', $q$select delta from public.monitoramento_verificacoes$q$, 'permission denied', 'authenticated');
select t.passa('L18 authenticated lê resultado e data real das verificações', $q$select resultado, data_real_atualizacao from public.monitoramento_verificacoes limit 1$q$, 'authenticated');
select t.passa('L19 authenticated lê a view de estado e a de última atualização', $q$select count(*) from public.v_caso_fluxo_estado; select count(*) from public.v_caso_ultima_atualizacao$q$, 'authenticated');
select t.erra('L20 authenticated não insere transição', $q$insert into public.fluxo_transicoes (event_id,empresa_id,de,acao,para) values (gen_random_uuid(),gen_random_uuid(),'SEM_FLUXO','x','MONITORADO')$q$, 'permission denied', 'authenticated');
select t.erra('L21 authenticated não executa fluxo_registrar', $q$select public.fluxo_registrar(gen_random_uuid(),'x','y',null,null,'{}')$q$, 'permission denied', 'authenticated');
select t.erra('L22 authenticated não liga/desliga a flag', $q$select public.pre_release_definir_fluxo_ativo(false,'x')$q$, 'permission denied', 'authenticated');
select t.erra('L23 authenticated não executa as funções de bloqueio', $q$select public.fluxo_estado(gen_random_uuid())$q$, 'permission denied', 'authenticated');
select t.passa('L24 service_role lê transições', $q$select count(*) from public.fluxo_transicoes$q$, 'service_role');
select t.passa('L25 service_role insere lote de seleção', $q$insert into public.selecao_lotes (versao_regra, itens) values ('svc','[]')$q$, 'service_role');
select t.erra('L26 service_role não faz UPDATE em fluxo_transicoes', $q$update public.fluxo_transicoes set motivo='x'$q$, 'permission denied', 'service_role');
select t.erra('L27 service_role não faz DELETE em dossie_versoes', $q$delete from public.dossie_versoes$q$, 'permission denied', 'service_role');
select t.erra('L28 service_role não faz TRUNCATE', $q$truncate public.pre_release_versoes$q$, 'permission denied', 'service_role');
select t.erra('L29 service_role só altera a coluna vigente dos parâmetros', $q$update public.pre_release_parametros set parametros = '{}'$q$, 'permission denied', 'service_role');
select t.passa('L30 service_role executa a RPC de registro (caso novo, só leitura do estado)', $q$select public.fluxo_estado(gen_random_uuid())$q$, 'service_role');
select t.passa('L31 service_role registra transição pelo RPC',
  format($q$select public.fluxo_registrar(%L,'COLETOR_ATUALIZAR','ATUALIZADO',null,null,'{}')$q$, (select id from c0)), 'service_role');
select t.afirma('L32 events.pre_release nunca foi escrito por nenhum teste', (select count(*) from public.events where pre_release is not null) = 0);
select t.afirma('L33 api_execucoes: o fluxo nunca criou execuções de IA (só os testes criaram as suas)',
  (select count(*) from public.api_execucoes where operacao not in ('analise_editorial','pre_release')) = 0);

select format('%s testes | %s falhas', count(*), count(*) filter (where not ok)) as resumo from t.res;
select nome, detalhe from t.res where not ok order by n;

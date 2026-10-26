-- Dados
insert into public.usuarios_perfil(id, role, nome, ativo) values
 ('00000000-0000-0000-0000-00000000000a','master','M',true),
 ('00000000-0000-0000-0000-0000000000a1','admin','Admin da empresa 1',true),
 ('00000000-0000-0000-0000-0000000000a2','admin','Admin da empresa 2',true),
 ('00000000-0000-0000-0000-0000000000a3','admin','Admin inativo',false),
 ('00000000-0000-0000-0000-0000000000a4','admin','Admin vínculo inativo',true),
 ('00000000-0000-0000-0000-0000000000c1','cliente','Cliente',true);
insert into public.usuario_empresas values
 ('00000000-0000-0000-0000-0000000000a1','11111111-1111-1111-1111-111111111111',true),
 ('00000000-0000-0000-0000-0000000000a2','22222222-2222-2222-2222-222222222222',true),
 ('00000000-0000-0000-0000-0000000000a3','11111111-1111-1111-1111-111111111111',true),
 ('00000000-0000-0000-0000-0000000000a4','11111111-1111-1111-1111-111111111111',false),
 ('00000000-0000-0000-0000-0000000000c1','11111111-1111-1111-1111-111111111111',true);
insert into public.events(id, empresa_id, titulo_fato) values
 ('e0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','E1 da empresa 1'),
 ('e0000000-0000-0000-0000-000000000002','22222222-2222-2222-2222-222222222222','E2 da empresa 2');
insert into public.api_execucoes(event_id, empresa_id, operacao, status, modelo, custo_estimado_usd, versao_prompt, input_tokens, total_tokens, request_id_provider, data_inicio, erro, motivo_bloqueio, resposta_texto, metadata) values
 ('e0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','analise_editorial','sucesso','MODELO-SECRETO-X',0.1234,'PROMPT-V9',111,222,'req_SEGREDO', now(), null, null, 'Parecer da IA para E1', '{"elegibilidade":{"flags":{"sem_evidencia":false}},"campo_interno":"VAZAMENTO"}'),
 ('e0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','analise_editorial','bloqueado_pre_ia',null,0,null,0,0,null, now()-interval '1 day', null, 'sem_evidencia', 'texto que NÃO deve sair', '{"elegibilidade":{"flags":{"sem_evidencia":true}}}'),
 ('e0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','analise_editorial','erro','MODELO-SECRETO-X',0.01,'PROMPT-V9',1,2,'req_X', now()-interval '2 day', 'ERRO-INTERNO-COM-SEGREDO', null, null, null),
 ('e0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','outra_operacao','sucesso','M',0,'P',0,0,null, now(), null, null, 'OUTRA OPERAÇÃO', null),
 ('e0000000-0000-0000-0000-000000000002','22222222-2222-2222-2222-222222222222','analise_editorial','sucesso','M',0.5,'P',1,1,null, now(), null, null, 'Parecer E2', null);
-- 6 linhas no mesmo evento p/ testar limite 5
insert into public.api_execucoes(event_id, empresa_id, operacao, status, data_inicio)
 select 'e0000000-0000-0000-0000-000000000002','22222222-2222-2222-2222-222222222222','analise_editorial','pendente', now() - (g||' hour')::interval from generate_series(1,6) g;

-- Aplica a migração
\i :MIGPERM
\i :MIGFILE

create function t.como(p_uid text, p_sql text) returns text language plpgsql as $$
begin perform set_config('request.jwt.claim.sub', p_uid, false); return t.falha(p_sql); end $$;
create function t.json_como(p_uid text, p_ev uuid) returns jsonb language plpgsql security invoker as $$
declare r jsonb; begin perform set_config('request.jwt.claim.sub', p_uid, true); r := public.ia_assistida_evento(p_ev); return r; end $$;
grant execute on function t.json_como(text, uuid) to authenticated, anon;

set role authenticated;
-- A) master
select t.chk('A1 master lê qualquer evento (E1)', jsonb_array_length(t.json_como('00000000-0000-0000-0000-00000000000a','e0000000-0000-0000-0000-000000000001')) = 3);
select t.chk('A2 master lê evento de outra empresa (E2)', jsonb_array_length(t.json_como('00000000-0000-0000-0000-00000000000a','e0000000-0000-0000-0000-000000000002')) = 5);
-- B) admin vinculado
select t.chk('B1 admin da empresa 1 lê E1', jsonb_array_length(t.json_como('00000000-0000-0000-0000-0000000000a1','e0000000-0000-0000-0000-000000000001')) = 3);
select t.chk('B2 admin da empresa 1 NÃO lê E2', t.como('00000000-0000-0000-0000-0000000000a1', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000002')$$) like '%sem permissão%');
select t.chk('B3 admin da empresa 2 NÃO lê E1', t.como('00000000-0000-0000-0000-0000000000a2', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('B4 admin com perfil inativo é recusado', t.como('00000000-0000-0000-0000-0000000000a3', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('B5 admin com vínculo inativo é recusado', t.como('00000000-0000-0000-0000-0000000000a4', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('B6 cliente é recusado', t.como('00000000-0000-0000-0000-0000000000c1', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('B7 usuário desconhecido é recusado', t.como('99999999-9999-9999-9999-999999999999', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('B8 evento inexistente: admin é recusado', t.como('00000000-0000-0000-0000-0000000000a1', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-0000000000ff')$$) like '%sem permissão%');
select t.chk('B9 sem sessão (auth.uid nulo) é recusado', t.como('', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sessão obrigatória%');
-- C) conteúdo: nada de custo/modelo/prompt
create temp table out_admin as select t.json_como('00000000-0000-0000-0000-0000000000a1','e0000000-0000-0000-0000-000000000001') as j;
select t.chk('C1 saída do admin não contém modelo/custo/prompt/tokens/request id/campo interno/erro',
  (select j::text !~* 'MODELO-SECRETO|PROMPT-V9|req_SEGREDO|VAZAMENTO|ERRO-INTERNO|custo|modelo|versao_prompt|tokens|0\.1234' from out_admin), (select j::text from out_admin));
select t.chk('C2 chaves devolvidas são só as 6 seguras',
  (select not exists (select 1 from out_admin, jsonb_array_elements(j) e, jsonb_object_keys(e) k
                       where k not in ('status','data_inicio','motivo_bloqueio','flags','resposta_texto','tem_erro'))
     from (select 1) x));
select t.chk('C3 resposta_texto só em status sucesso',
  (select bool_and((e->>'status') = 'sucesso' or (e->'resposta_texto') = 'null'::jsonb) from out_admin, jsonb_array_elements(j) e));
select t.chk('C4 texto de linha não-sucesso não vaza', (select j::text not like '%NÃO deve sair%' from out_admin));
select t.chk('C5 só analise_editorial', (select j::text not like '%OUTRA OPERAÇÃO%' from out_admin));
select t.chk('C6 parecer do sucesso presente', (select j::text like '%Parecer da IA para E1%' from out_admin));
select t.chk('C7 flags extraídas de metadata.elegibilidade', (select (j->1->'flags'->>'sem_evidencia') = 'true' from out_admin));
select t.chk('C8 tem_erro é booleano sem expor o texto', (select (j->2->>'tem_erro') = 'true' from out_admin));
select t.chk('C9 mais recente primeiro', (select (j->0->>'status') = 'sucesso' and (j->2->>'status') = 'erro' from out_admin));
select t.chk('C10 limite de 5 linhas', jsonb_array_length(t.json_como('00000000-0000-0000-0000-00000000000a','e0000000-0000-0000-0000-000000000002')) = 5);
-- D) a função não abre a tabela
select t.chk('D1 authenticated continua sem SELECT direto em api_execucoes', t.falha('select * from public.api_execucoes') like '%permission denied%');
reset role;
set role anon;
select t.chk('D2 anon não executa a função', t.falha($$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%permission denied%');
reset role;
select t.chk('D3 função é SECURITY DEFINER com search_path fixo',
  (select p.prosecdef and exists (select 1 from unnest(p.proconfig) c where c like 'search_path=%') from pg_proc p where p.proname='ia_assistida_evento'));
select t.chk('D4 função é STABLE (não escreve)', (select p.provolatile = 's' from pg_proc p where p.proname='ia_assistida_evento'));
select t.chk('D5 api_execucoes não foi alterada pelas migrações (11 originais)', (select count(*) = 11 from public.api_execucoes));

-- E) permissões vêm do BANCO (perfil_permissoes), não do código
set role authenticated;
select t.chk('E1 minhas_permissoes do master', (select (p->>'ia_assistida_custo')::boolean and (p->>'admin_painel')::boolean and (p->>'todas_empresas')::boolean
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-00000000000a',false) s, public.minhas_permissoes() p) x));
select t.chk('E2 minhas_permissoes do admin: ia sim, custo/painel/novo cliente não',
  (select (p->>'ia_assistida')::boolean and not (p->>'ia_assistida_custo')::boolean and not (p->>'admin_painel')::boolean and not (p->>'cliente_criar')::boolean and (p->>'editorial')::boolean
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-0000000000a1',false) s, public.minhas_permissoes() p) x));
select t.chk('E3 cliente (sem linhas na matriz) recebe {}', (select p = '{}'::jsonb
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-0000000000c1',false) s, public.minhas_permissoes() p) x));
select t.chk('E4 perfil inativo recebe {}', (select p = '{}'::jsonb
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-0000000000a3',false) s, public.minhas_permissoes() p) x));
select t.chk('E5 sem sessão: erro', t.como('', 'select public.minhas_permissoes()') like '%sessão obrigatória%');
select t.chk('E6 tem_permissao: ação inexistente = false', (select not public.tem_permissao('acao_que_nao_existe')
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-00000000000a',false)) x));
select t.chk('E7 aplicação não consegue alterar a matriz (sem grant de escrita)',
  t.falha($$update public.perfil_permissoes set permitido = true where role='admin' and acao='admin_painel'$$) like '%permission denied%'
  and t.falha($$insert into public.perfil_permissoes values ('admin','x',true)$$) like '%permission denied%'
  and t.falha($$delete from public.perfil_permissoes$$) like '%permission denied%');
select t.chk('E8 matriz é legível para quem está logado', (select count(*) = 16 from public.perfil_permissoes));
reset role;
set role anon;
select t.chk('E9 anon não lê a matriz nem executa as funções', t.falha('select * from public.perfil_permissoes') like '%permission denied%'
  and t.falha('select public.tem_permissao(''editorial'')') like '%permission denied%' and t.falha('select public.minhas_permissoes()') like '%permission denied%');
reset role;
-- F) mudar a linha no banco muda o comportamento SEM tocar em código
update public.perfil_permissoes set permitido = false where role='admin' and acao='ia_assistida';
set role authenticated;
select t.chk('F1 admin sem a permissão ia_assistida no banco passa a ser recusado', t.como('00000000-0000-0000-0000-0000000000a1', $$select public.ia_assistida_evento('e0000000-0000-0000-0000-000000000001')$$) like '%sem permissão%');
select t.chk('F2 minhas_permissoes reflete a mudança', (select not (p->>'ia_assistida')::boolean
   from (select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-0000000000a1',false) s, public.minhas_permissoes() p) x));
reset role;
update public.perfil_permissoes set permitido = true where role='admin' and acao='ia_assistida';
update public.perfil_permissoes set permitido = true where role='admin' and acao='todas_empresas';
set role authenticated;
select t.chk('F3 dar "todas_empresas" ao admin libera outra empresa (escopo também vem do banco)', jsonb_array_length(t.json_como('00000000-0000-0000-0000-0000000000a1','e0000000-0000-0000-0000-000000000002')) = 5);
reset role;
update public.perfil_permissoes set permitido = false where role='admin' and acao='todas_empresas';
-- G) idempotência não sobrescreve ajuste manual
update public.perfil_permissoes set permitido = false where role='admin' and acao='carteiras_editar';
\i :MIGPERM
select t.chk('G1 re-aplicar a migração não desfaz ajuste manual', (select not permitido from public.perfil_permissoes where role='admin' and acao='carteiras_editar'));
update public.perfil_permissoes set permitido = true where role='admin' and acao='carteiras_editar';

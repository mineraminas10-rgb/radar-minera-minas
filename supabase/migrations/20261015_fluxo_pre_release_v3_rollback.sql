-- =====================================================================================
-- ROLLBACK (NÃO APLICADO) da migração 20261015_fluxo_pre_release_v3.sql
-- Remove SOMENTE o que a migração criou: 6 tabelas, 2 views, funções public.fluxo_* / pre_release_definir_fluxo_ativo
-- e funções app_private novas. Não toca em events, evidencias, api_execucoes, execucoes nem em nenhuma tabela existente.
--
-- TRAVA DE SEGURANÇA: se já existir qualquer linha de registro (transições, dossiês, versões, lotes, verificações),
-- o rollback RECUSA, porque apagar esse histórico é irreversível. Para apagar mesmo assim (depois de exportar):
--     select set_config('radar.rollback_confirmado', 'sim', false);
-- e rode o script na mesma sessão. Sem linhas, roda direto.
-- =====================================================================================

do $$
declare n bigint := 0; c bigint; t text;
begin
  foreach t in array array['fluxo_transicoes', 'dossie_versoes', 'pre_release_versoes', 'selecao_lotes', 'monitoramento_verificacoes'] loop
    if to_regclass('public.' || t) is not null then
      execute format('select count(*) from public.%I', t) into c;
      n := n + c;
    end if;
  end loop;
  if n > 0 and coalesce(current_setting('radar.rollback_confirmado', true), '') <> 'sim' then
    raise exception 'rollback_recusado: existem % linhas de registro do fluxo v3. Exporte-as e confirme com set_config(''radar.rollback_confirmado'',''sim'',false).', n;
  end if;
end $$;

drop view if exists public.v_caso_fluxo_estado;
drop view if exists public.v_caso_ultima_atualizacao;

-- tabelas em ordem inversa de dependência (as FKs apontam só para tabelas novas ou para tabelas existentes, nunca o contrário)
alter table if exists public.fluxo_transicoes drop constraint if exists fk_fluxo_transicoes_pre_release_versao;
drop table if exists public.pre_release_versoes;
drop table if exists public.fluxo_transicoes;
drop table if exists public.dossie_versoes;
drop table if exists public.monitoramento_verificacoes;
drop table if exists public.selecao_lotes;
drop table if exists public.pre_release_parametros;

drop function if exists public.fluxo_gerar_pre_release(uuid, uuid, uuid, uuid, jsonb, jsonb, text, text);
drop function if exists public.fluxo_registrar(uuid, text, text, uuid, text, jsonb);
drop function if exists public.fluxo_pendencias_publicacao(uuid);
drop function if exists public.fluxo_bloqueios_geracao(uuid, jsonb);
drop function if exists public.fluxo_estado(uuid);
drop function if exists public.pre_release_definir_fluxo_ativo(boolean, text);

drop function if exists app_private.pre_release_antes_insert();
drop function if exists app_private.fluxo_transicao_antes_insert();
drop function if exists app_private.fluxo_regras();
drop function if exists app_private.dossie_antes_insert();
drop function if exists app_private.fluxo_validar_afirmacoes(uuid, jsonb);
drop function if exists app_private.fluxo_validar_matriz(uuid, jsonb);
drop function if exists app_private.monitoramento_antes_insert();
drop function if exists app_private.selecao_lote_antes_insert();
drop function if exists app_private.fluxo_parametros_guarda();
drop function if exists app_private.fluxo_imutavel();
drop function if exists app_private.fluxo_exige_ativo();
drop function if exists app_private.fluxo_ativo();
-- o schema app_private NÃO é removido (já existia em produção e tem outras funções)

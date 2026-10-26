-- =====================================================================================
-- IA ASSISTIDA — leitura para ADMIN, sem custo   (NÃO APLICADA)
-- Problema: api_execucoes só é legível pelo master (RLS). O admin precisa VER o resultado da análise da IA
-- (status, parecer, flags, motivo de bloqueio), mas NÃO modelo, custo, tokens, prompt, metadata bruta nem texto de erro.
-- RLS e GRANT de coluna não separam master de admin (ambos são o papel "authenticated"), então a separação é feita
-- por UMA função SECURITY DEFINER que devolve só os campos seguros.
-- ADITIVA e idempotente: cria 1 função. NÃO altera api_execucoes, RLS, policies, grants de tabelas, events nem nada existente.
-- NÃO chama IA, não gera pré-release, não publica.
-- Quem pode chamar (checado DENTRO da função, por auth.uid(), pela tabela public.perfil_permissoes — nada de papel fixo no código):
--   * precisa da permissão 'ia_assistida' (perfil ativo);
--   * e ou tem 'todas_empresas' (hoje: master) ou tem vínculo ativo (usuario_empresas) à empresa do evento (hoje: admin).
-- DEPENDE de 20261017_permissoes_perfil.sql (aplicar antes).
-- Reverter: 20261018_ia_assistida_leitura_admin_rollback.sql
-- =====================================================================================

create or replace function public.ia_assistida_evento(p_event_id uuid) returns jsonb
language plpgsql stable security definer set search_path = public, pg_catalog as $$
declare
  uid  uuid := auth.uid();
  emp  uuid;
  ok   boolean := false;
  res  jsonb;
begin
  if uid is null then
    raise exception 'ia_assistida_evento: sessão obrigatória' using errcode = 'insufficient_privilege';
  end if;
  if public.tem_permissao('ia_assistida') then
    if public.tem_permissao('todas_empresas') then
      ok := true;
    else
      select e.empresa_id into emp from public.events e where e.id = p_event_id;
      ok := emp is not null and exists (select 1 from public.usuario_empresas ue
                                         where ue.usuario_id = uid and ue.empresa_id = emp and coalesce(ue.ativo, true));
    end if;
  end if;
  if not ok then
    raise exception 'ia_assistida_evento: sem permissão para este evento' using errcode = 'insufficient_privilege';
  end if;

  -- SOMENTE campos seguros. Fora de propósito: modelo, custo_estimado_usd, tokens, versao_prompt, metadata (exceto flags), erro (texto), prompt.
  select coalesce(jsonb_agg(x order by x_ord desc), '[]'::jsonb) into res
    from (
      select jsonb_build_object(
               'status',          a.status,
               'data_inicio',     a.data_inicio,
               'motivo_bloqueio', a.motivo_bloqueio,
               'flags',           coalesce(a.metadata -> 'elegibilidade' -> 'flags', '{}'::jsonb),
               'resposta_texto',  case when a.status = 'sucesso' then a.resposta_texto else null end,
               'tem_erro',        (a.erro is not null and btrim(a.erro::text) <> '')
             ) as x,
             a.data_inicio as x_ord
        from public.api_execucoes a
       where a.event_id = p_event_id and a.operacao = 'analise_editorial'
       order by a.data_inicio desc nulls last
       limit 5
    ) q;
  return res;
end $$;

revoke all on function public.ia_assistida_evento(uuid) from public, anon;
grant execute on function public.ia_assistida_evento(uuid) to authenticated;

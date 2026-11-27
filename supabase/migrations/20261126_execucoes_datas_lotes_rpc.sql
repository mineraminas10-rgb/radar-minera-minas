-- Expose apenas identificador e início dos lotes vinculados à empresa autorizada.
-- execucoes permanece protegida por RLS; a UI não recebe os demais campos operacionais.
create or replace function public.execucoes_datas_lotes(p_ids uuid[])
returns table (id uuid, inicio timestamptz)
language sql
stable
security definer
set search_path = public, app_private, pg_catalog
as $function$
  select x.id, x.inicio
  from public.execucoes as x
  where x.id = any(coalesce(p_ids, '{}'::uuid[]))
    and app_private.usuario_tem_acesso_empresa(x.empresa_id)
$function$;

revoke all on function public.execucoes_datas_lotes(uuid[]) from public, anon;
grant execute on function public.execucoes_datas_lotes(uuid[]) to authenticated;

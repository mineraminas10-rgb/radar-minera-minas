-- Use a data de entrada como critério primário, mantendo a ordem editorial nos empates.
create or replace function public.fila_editorial(p_empresa uuid) returns jsonb
language sql stable security invoker set search_path = public, pg_catalog as $$
  with itens as (
    select e.created_at, e.id, public.fila_item(e.id) as it
      from public.events e
     where e.empresa_id = p_empresa
  ), ord as (
    select it, row_number() over (order by
        created_at desc nulls last,
        (it -> 'atual' ->> 'atualizado')::boolean desc,
        (it -> 'rank' ->> 'prioridade')::int desc,
        (it -> 'rank' ->> 'criticidade')::int desc,
        (it -> 'atual' ->> 'material_ts')::bigint desc,
        (it -> 'ineditismo' ->> 'inedito')::boolean desc,
        coalesce((it -> 'decisao' ->> 'score_valor')::numeric * case when (it -> 'decisao' ->> 'score_decisorio')::boolean then 1 else null end, -1e18) desc,
        (it ->> 'qualidade_evidencia')::int desc,
        id desc) as ordem
      from itens where it is not null
  )
  select coalesce(jsonb_agg(it || jsonb_build_object('ordem', ordem) order by ordem), '[]'::jsonb) from ord
$$;

-- ROLLBACK (NÃO APLICADO) de 20261016_fila_editorial_travas.sql. Remove só o que ela criou; events/event_scores intactos.
-- TRAVA: se o registro de descartes tiver linhas, recusa (histórico auditável). Para apagar mesmo assim, depois de exportar:
--   select set_config('radar.rollback_confirmado','sim',false);   -- na mesma sessão
-- Observação: o registro é append-only; este rollback desliga o trigger de imutabilidade só para remover a tabela.
do $$
declare n bigint := 0;
begin
  if to_regclass('public.fila_decisoes_score_log') is not null then
    execute 'select count(*) from public.fila_decisoes_score_log' into n;
  end if;
  if n > 0 and coalesce(current_setting('radar.rollback_confirmado', true), '') <> 'sim' then
    raise exception 'rollback_recusado: % linhas no registro de decisões da fila. Exporte e confirme com set_config(''radar.rollback_confirmado'',''sim'',false).', n;
  end if;
end $$;

drop trigger if exists trg_fila_guarda_avanco on public.events;
drop view if exists public.v_fila_decisao_score;
drop table if exists public.fila_decisoes_score_log;
drop function if exists public.fila_registrar_decisoes_score(uuid, text, text);
drop function if exists public.fila_elegivel_para_ia(uuid);
drop function if exists public.fila_decisao_score(uuid);
drop function if exists app_private.fila_guarda_avanco();
drop function if exists app_private.fila_log_imutavel();

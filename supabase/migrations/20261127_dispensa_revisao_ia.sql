-- Dispensa revisão humana somente após análise de IA validada e com trilha auditável.
-- A publicação continua exigindo ação editorial explícita.

CREATE OR REPLACE FUNCTION public.fila_dispensar_revisao_ia(
  p_event_id uuid,
  p_execucao_id uuid
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth, pg_catalog
AS $$
DECLARE
  v_uid uuid := auth.uid();
  v_event public.events%ROWTYPE;
  v_exec public.api_execucoes%ROWTYPE;
  v_anterior text;
  v_final text;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Sessão autenticada obrigatória';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.usuarios_perfil up
    WHERE up.id = v_uid AND up.role = 'master' AND up.ativo IS TRUE
  ) THEN
    RAISE EXCEPTION 'Apenas master pode dispensar revisão humana';
  END IF;

  SELECT * INTO v_event
  FROM public.events e
  WHERE e.id = p_event_id
  FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Evento não encontrado'; END IF;

  IF v_event.status_editorial IN ('publicado', 'pronto_para_publicar', 'arquivado', 'descartado') THEN
    RAISE EXCEPTION 'A revisão não pode ser dispensada neste status editorial';
  END IF;

  SELECT * INTO v_exec
  FROM public.api_execucoes x
  WHERE x.id = p_execucao_id
    AND x.event_id = p_event_id
    AND x.empresa_id = v_event.empresa_id
    AND x.operacao = 'analise_editorial'
    AND x.status = 'sucesso'
    AND x.metadata #>> '{validacao,ok}' = 'true';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'A execução precisa ser uma análise editorial concluída e validada para este evento';
  END IF;

  v_anterior := v_event.revisao_humana;
  IF v_anterior = 'Pendente' THEN
    UPDATE public.events SET revisao_humana = 'Dispensada pela IA' WHERE id = p_event_id;
    v_final := 'Dispensada pela IA';

    INSERT INTO public.admin_auditoria (usuario_id, empresa_id, acao, entidade, entidade_id, valor_anterior, valor_novo)
    VALUES (v_uid, v_event.empresa_id, 'dispensar_revisao_humana_ia', 'events', p_event_id::text,
      jsonb_build_object('revisao_humana', v_anterior, 'status_editorial', v_event.status_editorial),
      jsonb_build_object('revisao_humana', v_final, 'status_editorial', v_event.status_editorial, 'execucao_id', p_execucao_id));
  ELSIF v_anterior IN ('Dispensada pela IA', 'Aprovada') THEN
    v_final := v_anterior;
  ELSE
    RAISE EXCEPTION 'Estado de revisão incompatível: %', coalesce(v_anterior, '(vazio)');
  END IF;

  UPDATE public.api_execucoes
  SET metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
    'dispensa_revisao', jsonb_build_object(
      'status', v_final, 'registrado_em', clock_timestamp(), 'usuario_id', v_uid,
      'motivo', 'Análise editorial de IA concluída e validada'
    )
  )
  WHERE id = p_execucao_id;

  RETURN jsonb_build_object('event_id', p_event_id, 'execucao_id', p_execucao_id, 'revisao_humana', v_final, 'status_editorial', v_event.status_editorial);
END;
$$;

REVOKE ALL ON FUNCTION public.fila_dispensar_revisao_ia(uuid, uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.fila_dispensar_revisao_ia(uuid, uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public.trg_bloqueia_publicacao_sem_revisao_humana()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  IF NEW.status_editorial = 'publicado'
    AND coalesce(NEW.revisao_humana, '') NOT IN ('Aprovada', 'Dispensada pela IA')
    AND NOT public.fila_excecao_revisao_ativa(NEW.id) THEN
    RAISE EXCEPTION 'Trava técnica: publicação exige revisão aprovada ou dispensa registrada por IA (evento %, revisão atual=%)',
      NEW.id_evento, coalesce(NEW.revisao_humana, '(vazio)');
  END IF;
  RETURN NEW;
END;
$$;

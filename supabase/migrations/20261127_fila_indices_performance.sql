-- Índices para reduzir o custo da fila editorial e apoiar a ordem por data de entrada.
create index if not exists idx_events_empresa_created_at_id
  on public.events (empresa_id, created_at desc nulls last, id desc);

create index if not exists idx_event_scores_event_latest
  on public.event_scores (event_id, vigente desc nulls last, created_at desc nulls last);

create index if not exists idx_documentos_event_id
  on public.documentos (event_id);

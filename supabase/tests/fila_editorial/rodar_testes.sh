#!/usr/bin/env bash
# Testa 20261016_fila_editorial_travas.sql num cluster Postgres 16 TEMPORÁRIO (socket unix, sem rede). Nunca toca em produção.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIG="${MIG_DIR:-$HERE/../../migrations_pendentes}"
BIN=/usr/lib/postgresql/16/bin
TMP="$(mktemp -d)"; chmod 755 "$TMP"
PORT=54331
export PGOPTIONS="-c client_min_messages=warning"
export PGHOST="$TMP/sock" PGPORT=$PORT PGUSER=postgres PGDATABASE=postgres
mkdir -p "$TMP/sock"; chown -R postgres "$TMP" 2>/dev/null || true
run_pg() { su postgres -s /bin/bash -c "$*"; }
run_pg "$BIN/initdb -D $TMP/data -A trust >/dev/null"
run_pg "$BIN/pg_ctl -D $TMP/data -o '-c listen_addresses= -k $TMP/sock -p $PORT' -l $TMP/pg.log -w start >/dev/null"
trap 'run_pg "$BIN/pg_ctl -D $TMP/data -m immediate stop >/dev/null" || true' EXIT
P="psql -X -q -v ON_ERROR_STOP=1"
$P -f "$HERE/00_stubs.sql"
dump_tabelas() { $BIN/pg_dump -s -t public.event_scores -t public.evidencias | grep -v '^\\\(un\)\?restrict'; }
dump_tabelas > "$TMP/antes.sql"
echo "== 1) aplica (1ª vez) e de novo (idempotência)"
$P -f "$MIG/20261016_fila_editorial_travas.sql"
$P -f "$MIG/20261016_fila_editorial_travas.sql"
dump_tabelas > "$TMP/depois.sql"
diff -q "$TMP/antes.sql" "$TMP/depois.sql" >/dev/null && echo "OK: event_scores/evidencias idênticas" || { echo "FALHA: migração alterou tabela existente"; exit 1; }
echo "== 1b) estático: só 1 trigger em events, sem ALTER/DROP/UPDATE/DELETE em tabelas existentes"
N=$(grep -Eic "create (or replace )?trigger .* on (public\.)?events\b" "$MIG/20261016_fila_editorial_travas.sql" || true)
[ "$N" = "1" ] && echo "OK: 1 trigger em events (guarda de avanço)" || { echo "FALHA: $N triggers em events"; exit 1; }
if grep -Eiq "alter table (if exists )?(public\.)?(events|event_scores|evidencias|documentos|checklist_[a-z_]*)\b|drop table (if exists )?(public\.)?(events|event_scores|evidencias)\b|(update|delete from|insert into) +public\.(events|event_scores|evidencias)\b" "$MIG/20261016_fila_editorial_travas.sql"; then echo "FALHA: migração escreve/altera tabela existente"; exit 1; else echo "OK"; fi
echo "== 2) testes"
$P -o /dev/null -v ON_ERROR_STOP=0 -f "$HERE/10_testes.sql" 2> "$TMP/erros_sql.txt" || true
$P -At -F ' | ' -c "select case when ok then 'ok   ' else 'FALHA' end, nome, case when ok then '' else coalesce(detalhe,'') end from t.res order by n" | tee "$TMP/resultado.txt"
TOTAL=$($P -At -c "select count(*) from t.res"); FALHAS=$($P -At -c "select count(*) from t.res where not ok")
echo "== $TOTAL testes, $FALHAS falhas"
grep -i "^ERROR" "$TMP/erros_sql.txt" | head -5 || true
[ "$FALHAS" = "0" ] || { echo "HÁ FALHAS"; exit 1; }
echo "== 3) rollback recusa com dados, aceita com confirmação, deixa tudo como antes"
if $P -f "$MIG/20261016_fila_editorial_travas_rollback.sql" 2>"$TMP/rb.err"; then echo "FALHA: rollback rodou com dados"; exit 1; else grep -q rollback_recusado "$TMP/rb.err" && echo "OK: recusado"; fi
$P -c "select set_config('radar.rollback_confirmado','sim',false)" -f "$MIG/20261016_fila_editorial_travas_rollback.sql"
dump_tabelas > "$TMP/pos.sql"; diff -q "$TMP/antes.sql" "$TMP/pos.sql" >/dev/null && echo "OK: pós-rollback idêntico"
RESTOS=$($P -At -c "select (select count(*) from pg_proc where proname like 'fila\_%') + (select count(*) from pg_trigger where tgname like 'trg_fila%') + (select count(*) from pg_class where relname in ('fila_decisoes_score_log','v_fila_decisao_score'))")
[ "$RESTOS" = "0" ] && echo "OK: nada sobrou" || { echo "FALHA: sobraram $RESTOS"; exit 1; }
$P -f "$MIG/20261016_fila_editorial_travas.sql"; $P -f "$MIG/20261016_fila_editorial_travas_rollback.sql"; $P -f "$MIG/20261016_fila_editorial_travas.sql"
echo "TUDO OK"

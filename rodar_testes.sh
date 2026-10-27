#!/usr/bin/env bash
# Testa 20261019_fila_regras_no_banco.sql (sobre 20261016 + 20261017) num cluster Postgres 16 TEMPORÁRIO (socket unix, sem rede). Nunca toca em produção.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIG="${MIG_DIR:-$HERE/../../migrations_pendentes}"
BIN=/usr/lib/postgresql/16/bin
TMP="$(mktemp -d)"; chmod 755 "$TMP"
PORT=54333
export PGOPTIONS="-c client_min_messages=warning"
export PGHOST="$TMP/sock" PGPORT=$PORT PGUSER=postgres PGDATABASE=postgres
mkdir -p "$TMP/sock"; chown -R postgres "$TMP" 2>/dev/null || true
run_pg() { su postgres -s /bin/bash -c "$*"; }
run_pg "$BIN/initdb -D $TMP/data -A trust >/dev/null"
run_pg "$BIN/pg_ctl -D $TMP/data -o '-c listen_addresses= -k $TMP/sock -p $PORT' -l $TMP/pg.log -w start >/dev/null"
trap 'run_pg "$BIN/pg_ctl -D $TMP/data -m immediate stop >/dev/null" || true' EXIT
P="psql -X -q -v ON_ERROR_STOP=1"
$P -f "$HERE/00_stubs.sql"
dump_tabelas() { $BIN/pg_dump -s -t public.events -t public.event_scores -t public.evidencias -t public.documentos -t public.api_execucoes | grep -v '^\\\(un\)\?restrict' | grep -v 'trg_fila_guarda_avanco'; }
$P -f "$MIG/20261016_fila_editorial_travas.sql"
$P -f "$MIG/20261017_permissoes_perfil.sql"
dump_tabelas > "$TMP/antes.sql"
echo "== 1) aplica 20261019 (1ª vez) e de novo (idempotência)"
$P -f "$MIG/20261019_fila_regras_no_banco.sql"
$P -f "$MIG/20261019_fila_regras_no_banco.sql"
dump_tabelas > "$TMP/depois.sql"
diff -q "$TMP/antes.sql" "$TMP/depois.sql" >/dev/null && echo "OK: events/event_scores/evidencias/documentos/api_execucoes com a mesma estrutura" || { echo "FALHA: migração alterou tabela existente"; diff "$TMP/antes.sql" "$TMP/depois.sql" | head; exit 1; }
[ "$($P -At -c "select count(*) from public.fila_parametros")" = "1" ] && echo "OK: 1 versão de parâmetros após 2 aplicações" || { echo "FALHA: parâmetros duplicados"; exit 1; }
echo "== 1b) estático: nenhuma escrita em tabela existente além de events.pre_release (função de clique)"
if grep -Eiq "alter table (if exists )?(public\.)?(events|event_scores|evidencias|documentos|api_execucoes)\b|drop table (if exists )?(public\.)?(events|event_scores|evidencias)\b|(delete from|insert into) +public\.(events|event_scores|evidencias|documentos|api_execucoes)\b" "$MIG/20261019_fila_regras_no_banco.sql"; then echo "FALHA: migração altera/escreve tabela existente"; exit 1; else echo "OK"; fi
N=$(grep -Eic "update +public\.events" "$MIG/20261019_fila_regras_no_banco.sql" || true)
[ "$N" = "1" ] && echo "OK: único UPDATE em events (pre_release, só em fila_aplicar_rascunho_pre_release)" || { echo "FALHA: $N UPDATE em events"; exit 1; }
if grep -Eiq "net\.http|http_post|pg_cron|cron\.schedule|pg_net" "$MIG/20261019_fila_regras_no_banco.sql"; then echo "FALHA: chamada externa/agendamento"; exit 1; else echo "OK: sem chamada externa, sem agendamento"; fi
echo "== 2) testes"
$P -o /dev/null -v ON_ERROR_STOP=0 -f "$HERE/10_testes.sql" 2> "$TMP/erros_sql.txt" || true
$P -At -F ' | ' -c "select case when ok then 'ok   ' else 'FALHA' end, nome, case when ok then '' else coalesce(detalhe,'') end from t.res order by n" | tee "$TMP/resultado.txt"
TOTAL=$($P -At -c "select count(*) from t.res"); FALHAS=$($P -At -c "select count(*) from t.res where not ok")
echo "== $TOTAL testes, $FALHAS falhas"
grep -i "ERROR" "$TMP/erros_sql.txt" | head -8 || true
[ "$FALHAS" = "0" ] && [ "$TOTAL" -ge 50 ] || { echo "HÁ FALHAS (ou testes faltando)"; exit 1; }
if [ -f "$HERE/paridade.py" ]; then echo "== 3) paridade banco x regras atuais do index.html (JS)"; python3 "$HERE/paridade.py" "$TMP" "$HERE/../../../index.html" "$PGHOST" "$PGPORT"; fi
echo "== 4) rollback recusa com registros, aceita com confirmação, restaura a 20261016"
if $P -f "$MIG/20261019_fila_regras_no_banco_rollback.sql" 2>"$TMP/rb.err"; then echo "FALHA: rollback rodou com registros"; exit 1; else grep -q rollback_recusado "$TMP/rb.err" && echo "OK: recusado"; fi
$P -c "select set_config('radar.rollback_confirmado','sim',false)" -f "$MIG/20261019_fila_regras_no_banco_rollback.sql"
RESTOS=$($P -At -c "select (select count(*) from pg_proc where proname in ('fila_item','fila_editorial','fila_pode_gerar_pre_release','fila_parametros_vigentes','fila_rascunho_pre_release','fila_aplicar_rascunho_pre_release','fila_bloqueios_core','fila_ia_core')) + (select count(*) from pg_class where relname in ('fila_parametros','fila_pre_release_aplicacoes'))")
[ "$RESTOS" = "0" ] && echo "OK: nada da 20261019 sobrou" || { echo "FALHA: restaram $RESTOS objetos"; exit 1; }
echo "== 5) pós-rollback: a 20261016 volta a funcionar"
$P -At -c "select public.fila_decisao_score('e0000000-0000-0000-0000-000000000002'::uuid) ->> 'situacao'" | grep -q SCORE_BAIXO_COM_GATILHO_FORTE && echo "OK: fila_decisao_score original restaurada" || { echo "FALHA"; exit 1; }

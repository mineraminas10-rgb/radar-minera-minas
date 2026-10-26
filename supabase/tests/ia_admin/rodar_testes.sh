#!/usr/bin/env bash
# Testa 20261017_permissoes_perfil + 20261018_ia_assistida_leitura_admin.sql num cluster Postgres 16 TEMPORÁRIO (socket unix, sem rede). Nunca toca em produção.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIG="${MIG_DIR:-$HERE/../../migrations_pendentes}"
BIN=/usr/lib/postgresql/16/bin
TMP="$(mktemp -d)"; chmod 755 "$TMP"
PORT=54332
export PGOPTIONS="-c client_min_messages=warning"
export PGHOST="$TMP/sock" PGPORT=$PORT PGUSER=postgres PGDATABASE=postgres
mkdir -p "$TMP/sock"; chown -R postgres "$TMP" 2>/dev/null || true
run_pg() { su postgres -s /bin/bash -c "$*"; }
run_pg "$BIN/initdb -D $TMP/data -A trust >/dev/null"
run_pg "$BIN/pg_ctl -D $TMP/data -o '-c listen_addresses= -k $TMP/sock -p $PORT' -l $TMP/pg.log -w start >/dev/null"
trap 'run_pg "$BIN/pg_ctl -D $TMP/data -m immediate stop >/dev/null" || true' EXIT
P="psql -X -q -v ON_ERROR_STOP=1"
$P -f "$HERE/00_stubs.sql"
echo "== estático: só cria a função (sem alterar tabela/policy/grant de tabela)"
if grep -Eiq "alter table|create policy|drop policy|grant +(select|insert|update|delete|all)|(update|delete from|insert into) +public\." "$MIG/20261018_ia_assistida_leitura_admin.sql"; then echo "FALHA: migração mexe em tabela/policy"; exit 1; else echo "OK"; fi
echo "== testes (migração aplicada 2x = idempotência)"
$P -c "select 1" >/dev/null
$P -o /dev/null -v ON_ERROR_STOP=0 -v MIGPERM="$MIG/20261017_permissoes_perfil.sql" -v MIGFILE="$MIG/20261018_ia_assistida_leitura_admin.sql" -f "$HERE/10_testes.sql" 2> "$TMP/erros_sql.txt" || true
$P -f "$MIG/20261018_ia_assistida_leitura_admin.sql"
$P -At -F ' | ' -c "select case when ok then 'ok   ' else 'FALHA' end, nome, case when ok then '' else coalesce(detalhe,'') end from t.res order by n" | tee "$TMP/resultado.txt"
TOTAL=$($P -At -c "select count(*) from t.res"); FALHAS=$($P -At -c "select count(*) from t.res where not ok")
echo "== $TOTAL testes, $FALHAS falhas"
grep -i "^ERROR" "$TMP/erros_sql.txt" | head -5 || true
[ "$FALHAS" = "0" ] && [ "$TOTAL" -ge 30 ] || { echo "HÁ FALHAS (ou testes faltando)"; exit 1; }
echo "== rollback (na ordem inversa)"
$P -f "$MIG/20261018_ia_assistida_leitura_admin_rollback.sql"
$P -f "$MIG/20261017_permissoes_perfil_rollback.sql"
[ "$($P -At -c "select count(*) from pg_proc where proname in ('ia_assistida_evento','tem_permissao','minhas_permissoes')")" = "0" ] && [ "$($P -At -c "select count(*) from pg_class where relname='perfil_permissoes'")" = "0" ] && echo "OK: nada sobrou" || { echo FALHA; exit 1; }
[ "$($P -At -c "select count(*) from public.api_execucoes")" = "11" ] && echo "OK: dados intactos"
echo "TUDO OK"

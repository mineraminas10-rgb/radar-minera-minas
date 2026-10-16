#!/usr/bin/env bash
# Roda os testes do fluxo v3 num cluster Postgres 16 TEMPORÁRIO (socket unix, sem rede). Nunca toca em produção.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIG="${MIG_DIR:-$HERE/../../migrations_pendentes}"
BIN=/usr/lib/postgresql/16/bin
TMP="$(mktemp -d)"; chmod 755 "$TMP"
PORT=54330
export PGOPTIONS="-c client_min_messages=warning"
export PGHOST="$TMP/sock" PGPORT=$PORT PGUSER=postgres PGDATABASE=postgres
mkdir -p "$TMP/sock"; chown -R postgres "$TMP" 2>/dev/null || true
run_pg() { su postgres -s /bin/bash -c "$*"; }
run_pg "$BIN/initdb -D $TMP/data -A trust >/dev/null"
run_pg "$BIN/pg_ctl -D $TMP/data -o '-c listen_addresses= -k $TMP/sock -p $PORT' -l $TMP/pg.log -w start >/dev/null"
trap 'run_pg "$BIN/pg_ctl -D $TMP/data -m immediate stop >/dev/null" || true' EXIT
P="psql -X -q -v ON_ERROR_STOP=1"
$P -f "$HERE/00_stubs.sql"
dump_existentes() { $BIN/pg_dump -s -t public.events -t public.evidencias -t public.execucoes -t public.api_execucoes | grep -v '^\\\(un\)\?restrict'; $P -At -c "select pg_get_functiondef('app_private.is_master()'::regprocedure)"; }
dump_existentes > "$TMP/antes.sql"

echo "== 1) aplica a migração (1ª vez) e de novo (idempotência)"
$P -f "$MIG/20261015_fluxo_pre_release_v3.sql"
$P -f "$MIG/20261015_fluxo_pre_release_v3.sql"
dump_existentes > "$TMP/depois.sql"
if diff -q "$TMP/antes.sql" "$TMP/depois.sql" >/dev/null; then echo "OK: tabelas/funções existentes idênticas (nenhuma interferência)"; else echo "FALHA: migração alterou objeto existente"; diff "$TMP/antes.sql" "$TMP/depois.sql"; exit 1; fi

echo "== 1b) checagem estática: nenhum ALTER/DROP/UPDATE/DELETE em tabela que já existe"
if grep -Eiq "alter table (if exists )?(public\.)?(events|evidencias|execucoes|api_execucoes|checklist_[a-z_]*|event_scores|empresas|carteiras|usuarios?)\b|create (or replace )?trigger .* on (public\.)?(events|evidencias|execucoes|api_execucoes)\b|insert into public\.(events|evidencias|execucoes|api_execucoes)\b" "$MIG/20261015_fluxo_pre_release_v3.sql"; then echo "FALHA: migração mexe em tabela existente"; exit 1; else echo "OK: migração só cria objetos novos"; fi
echo "== 2) testes de transições, bloqueios, imutabilidade e permissões"
$P -o /dev/null -f "$HERE/10_testes.sql"
$P -At -F ' | ' -c "select case when ok then 'ok   ' else 'FALHA' end, nome, case when ok then '' else coalesce(detalhe,'') end from t.res order by n" > "$TMP/resultado.txt"
cat "$TMP/resultado.txt"
TOTAL=$($P -At -c "select count(*) from t.res"); FALHAS=$($P -At -c "select count(*) from t.res where not ok")
echo "== $TOTAL testes, $FALHAS falhas"
[ "$FALHAS" = "0" ] || { echo "HÁ FALHAS"; exit 1; }

echo "== 3) rollback: recusa com dados, aceita com confirmação, deixa tudo como antes"
if $P -f "$MIG/20261015_fluxo_pre_release_v3_rollback.sql" 2>"$TMP/rb.err"; then echo "FALHA: rollback rodou com dados sem confirmação"; exit 1; else grep -q rollback_recusado "$TMP/rb.err" && echo "OK: rollback recusado com dados"; fi
$P -c "select set_config('radar.rollback_confirmado','sim',false)" -f "$MIG/20261015_fluxo_pre_release_v3_rollback.sql"
dump_existentes > "$TMP/pos_rollback.sql"
diff -q "$TMP/antes.sql" "$TMP/pos_rollback.sql" >/dev/null && echo "OK: pós-rollback idêntico ao estado original" || { echo "FALHA: pós-rollback difere"; exit 1; }
RESTOS=$($P -At -c "select (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname in ('pre_release_parametros','selecao_lotes','monitoramento_verificacoes','dossie_versoes','fluxo_transicoes','pre_release_versoes','v_caso_fluxo_estado','v_caso_ultima_atualizacao')) + (select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where (n.nspname='public' and (p.proname like 'fluxo\_%' or p.proname='pre_release_definir_fluxo_ativo')) or (n.nspname='app_private' and p.proname<>'is_master'))")
[ "$RESTOS" = "0" ] && echo "OK: nenhum objeto do fluxo v3 sobrou" || { echo "FALHA: sobraram $RESTOS objetos"; exit 1; }
echo "== 4) rollback sem dados roda direto e a migração reaplica limpa"
$P -f "$MIG/20261015_fluxo_pre_release_v3.sql"
$P -f "$MIG/20261015_fluxo_pre_release_v3_rollback.sql"
$P -f "$MIG/20261015_fluxo_pre_release_v3.sql"
echo "TUDO OK"

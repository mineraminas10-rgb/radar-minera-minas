# Fluxo v3 — pacote de migration (NÃO APLICADO)

Conteúdo (caminhos relativos à raiz do repositório):

- `supabase/migrations_pendentes/20261015_fluxo_pre_release_v3.sql` — migration aditiva (6 tabelas, funções, 2 views). Flag nasce DESLIGADA.
- `supabase/migrations_pendentes/20261015_fluxo_pre_release_v3_rollback.sql` — rollback (recusa se já houver dados, salvo confirmação explícita).
- `supabase/tests/fluxo_v3/` — stubs, 199 testes SQL e `rodar_testes.sh` (Postgres 16 temporário, só teste).

Regras:
1. Nada deste pacote foi aplicado em produção. Só aplicar com autorização expressa.
2. Rodar os testes: `bash supabase/tests/fluxo_v3/rodar_testes.sh` (precisa de Postgres 16 instalado; roda como root e usa o usuário `postgres` do sistema).
3. Ligar/desligar a flag depois de aplicada: `select public.pre_release_definir_fluxo_ativo(true, 'motivo');`

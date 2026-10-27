# Entrega urgente — fila editorial (NADA aplicado em produção)

## Arquivos (mesmos caminhos do repositório)
- index.html (frontend: única mudança que vai ao ar quando você publicar o arquivo)
- tests/frontend/test_fila_editorial.py (novo) — 13 testes da fila (cobre os 10 obrigatórios + extras)
- supabase/migrations_pendentes/20261016_fila_editorial_travas.sql + _rollback.sql — NÃO APLICAR sem sua autorização
- supabase/tests/fila_editorial/ — 45 testes SQL em Postgres local temporário
- contagens_simuladas_fila.sql — um SELECT somente-leitura para você rodar e ver as contagens reais

## Como entra em produção (quando você autorizar)
1. Subir index.html no GitHub (a interface já passa a mostrar tudo; não grava nada no banco).
2. Em outro passo, e só com sua autorização explícita: aplicar a migration 20261016 (guarda de avanço no banco + registro de descartes).

## Premissas a confirmar
- Criticidade vem de event_scores.componentes.criticidade (gravada pelo CRIT-V1.2). Enquanto o CRIT não estiver em produção, o campo mostra "—" e o corte <40 só vale para scores decisórios (relevância editorial ou estágio final).
- Hoje os 59 scores são preliminares: aparecem como "N · Provisório", nunca descartam.
- "ATUALIZADO" = componentes.ultima_atualizacao_material (ou events.ultima_atualizacao_material, se a coluna existir) posterior à entrada. Sem esse dado, nenhum caso é ATUALIZADO.
- Marcar publicado exige estar em "Pronto p/ publicar" e revisão humana diferente de "Pendente" (premissa: já existe trigger de revisão humana no banco).
- Score pendente só bloqueia publicação se EXIGE_SCORE_PARA_PUBLICAR = true (hoje false).

## Atualização — prioridade editorial (derivada)
- event_scores.prioridade NÃO é alterada: continua como "Prioridade CRIT (histórica)", só em detalhes. O card, a ordem e o filtro usam prioridade_editorial (A IMEDIATA, B ALTA, C AVALIAR, D BAIXA/FORA, PENDENTE).
- Criticidade = gravidade do fato; prioridade = urgência de tratar agora. Fato crítico já publicado, antigo e sem atualização material fica D, com o motivo escrito no card.
- Ineditismo: conteúdo ainda não publicado antes. Já publicado = status "publicado" ou componentes.publicado_antes = true. Inédito antes de já publicado no desempate.
- Contrato opcional de componentes (CRIT/análise): atualizacao_material.impacto ("critico"|"relevante"), evidencia_suficiente, reforcos. Sem eles, esses critérios não disparam.
- Parâmetro a confirmar: janela de atualidade = 90 dias (JANELA_ATUALIDADE_DIAS).
- Decisões minhas a confirmar: CRITICO com score < 40 vira C (regra C citada por você); score >= 80 sem gatilho/evidência cai em B; criticidade BAIXA/ROTINA => D mesmo com score alto (salvo atualização material).

---
## Acréscimo — permissões no banco + IA assistida visível para ADMIN (sem custo)
**Ordem de aplicação (nenhuma aplicada; só com autorização):** 1) `20261017_permissoes_perfil.sql`  2) `20261018_ia_assistida_leitura_admin.sql`.
- `20261017_permissoes_perfil.sql` (+rollback): tabela `perfil_permissoes (role, acao, permitido)` semeada com a matriz que já existia no index.html (+ `ia_assistida`, `ia_assistida_custo`, `todas_empresas`), funções `minhas_permissoes()` e `tem_permissao(acao)`. Ninguém da aplicação escreve na tabela; muda-se com UPDATE no banco. Reaplicar não sobrescreve ajustes.
- `20261018_ia_assistida_leitura_admin.sql` (+rollback): função `ia_assistida_evento(uuid)` que devolve só status, data, motivo, flags, parecer (se sucesso) e "tem_erro" — sem modelo/custo/prompt. Quem pode vem da tabela: permissão `ia_assistida` + (`todas_empresas` ou vínculo ativo à empresa do evento).
- `index.html`: não tem mais a matriz fixa; ao entrar lê `minhas_permissoes` e `pode(acao)` obedece só ao banco. Se a função ainda não existir (migration não aplicada) usa uma cópia mínima de transição (admin SEM ia_assistida) para o sistema não travar; qualquer outro erro bloqueia o acesso em vez de liberar. Mudou a matriz no banco -> a tela é refeita na próxima revalidação.
- Ainda no código (escopo de empresas no login; o banco/RLS já barra): a checagem `role === 'master'` ao carregar empresas.
- Testes: `supabase/tests/ia_admin/rodar_testes.sh` (39 SQL, mutações detectadas) e `tests/frontend/test_ia_assistida_admin.py` (14).

---

## Acréscimo — regras da fila NO BANCO + rascunho da IA como pré-release (migração 20261019, NÃO aplicada)

**Princípio:** nenhuma regra de negócio da fila fica no `index.html`. Prioridade A/B/C/D, ineditismo, atualidade, ordem da fila, bloqueios de avanço e
"a IA pode gerar pré-release para este evento?" são decididos por funções do banco; os limiares (corte 40, B=60, A=80, janela de 90 dias, níveis de gatilho
forte, rótulos e textos) estão na tabela `public.fila_parametros` (versionada). O index só exibe.

**O que a migração cria:** `fila_parametros`; `fila_item(evento)` e `fila_editorial(empresa)` (fila já ordenada); `fila_bloqueios_publicacao`; `fila_pode_gerar_pre_release`;
`fila_rascunho_pre_release` e `fila_aplicar_rascunho_pre_release` (+ registro append-only `fila_pre_release_aplicacoes`). Redefine `fila_decisao_score` e a trava de avanço
(mesma saída, agora lendo os parâmetros e o mesmo núcleo de bloqueios da interface).

**Pré-release:** o rascunho que a IA já gera (`api_execucoes`, "não aplicado ao evento") só vira `events.pre_release` por **clique** de quem tem a permissão `editorial`,
com as travas no banco (evento já decidido, fora da seleção, análise mais recente que a vista, substituição explícita). O servidor da IA (`executar-ai`) consulta
`fila_pode_gerar_pre_release` antes de qualquer chamada paga. Nada roda sozinho; nenhuma IA é chamada pela migração.

**Decisão nova (mude se discordar):** `prioridades_sem_pre_release = ["D"]` — a IA não gera pré-release para prioridade D (fora da seleção, baixa/rotina, já publicado sem novidade).
Para liberar: `update public.fila_parametros set parametros = jsonb_set(parametros,'{prioridades_sem_pre_release}','[]') where vigente;`

**Ordem de aplicação:** `20261016_fila_editorial_travas.sql` → `20261019_fila_regras_no_banco.sql` (a 20261017 já está aplicada). Antes, rode `20261019_checagem_previa.sql` (somente leitura; esperado: 0 linhas "faltando").
A edge function `executar-ai` precisa ser reimplantada para passar a consultar o banco (sem isso ela segue como antes).
Rollback: `20261019_fila_regras_no_banco_rollback.sql` (restaura a `fila_decisao_score` e a trava da 20261016).

**Testes:** `supabase/tests/fila_regras/rodar_testes.sh` — 66 testes SQL + paridade com as regras antigas do index (700 cenários, inclusive a ORDEM da fila: 0 divergências);
`tests/frontend/test_fila_regras_banco.py` — 15 testes (interface só exibe o banco; modo de transição se a migração ainda não existe; rascunho só por clique).
Sem a migração aplicada, o index continua funcionando em **modo de transição** (avisa na tela) com a cópia local da regra, a ser removida depois.

**Também neste pacote:** a data de **Entrada** passou para o topo do card, ao lado dos indicadores (Atualidade, Ineditismo…).


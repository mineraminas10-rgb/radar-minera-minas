# Relatório de implementação — Cartas Operacionais x estado real do sistema

Data deste relatório: 30/09/2026. Escopo: consolidar, carta por carta, o que já está implementado e rodando (código + banco de produção), o que está especificado mas ainda não construído, e o que está parcialmente feito. Não é uma auditoria nova do zero — reaproveita e atualiza a auditoria de 28/09 (`AUDITORIA_RADAR_v2_8_M6_M8_M9A_2026-09-28.md` e `DELTA_IMPLEMENTACAO_ESCOPO_V2_8_2026-09-28.md`), conferindo de novo contra o banco de produção real (projeto `radarmineraminas`) e contra o repositório, porque dois dias se passaram e o trabalho desta sessão (Módulo 9A) mudou o quadro.

**Método**: código lido direto do repositório (`origin/main` + branch local testada); estado do banco lido ao vivo via acesso direto ao Postgres de produção (não é réplica desta vez — são contagens e valores reais, rodados agora); suíte de testes executada agora mesmo (52/52 M9A, 26/26 M8, ambos passando). Cartas usadas como referência: sempre a versão mais recente de cada uma.

## Resumo executivo

| Carta | Situação da carta | Código | Produção | Homologado? |
|---|---|---|---|---|
| M8 — Acidentes SEMAD v1.0 | Estudo e especificação fechados (19/09) | **Implementado e testado** (26/26) | Nunca rodou contra um comunicado real — 0 eventos M8 no banco | Não — carta exige rodada real antes de homologar |
| M9A — Movimentações ANM v1.0 | Estudo, calibração v0.2 e piloto editorial fechados (19/09) | **Implementado e testado** (52/52), corrigido nesta sessão | 1 caso real reprocessado e gravado em produção (830.649/2020); 5 eventos M9A no banco | Não — carta exige execução recorrente e repetição em nova data |
| Revisão/Calibração de scores M8/M9A | Diretriz de correção — **não autorizada para produção** | Infraestrutura de score pronta no banco; fórmulas 0–100 ainda não codificadas | `score_normalizado` populado (59/59 linhas) mas a fórmula que a carta pede (faixas, redutores, combinação) ainda não existe em código | Bloqueada por desenho — a própria carta proíbe produção |
| M6 — Outorgas IGAM v0.8 + Homologação | Especificação consolidada; homologação pendente | **Não existe nenhum coletor** (`coletores/m6_outorgas` nem chegou a ser criado no repo) | 0 eventos M6; 550 linhas de estoque histórico importado manualmente (não é o coletor) | Não — nem a rodada de homologação (caso Rima Industrial) foi rodada |
| M7 — Copam/CMI v0.5 | Estudo em andamento, arquitetura definida | **Não existe nenhum coletor** | 10 eventos M7 no banco, mas de carga editorial manual, não de coletor automatizado | Não |
| M5 — Audiências EIA/Rima v0.3.1 | Decisões fechadas para iniciar implementação | **Não existe nenhum coletor** | 2 eventos M5 no banco, mesma origem manual | Não |

Em uma frase: dos seis instrumentos, só M8 e M9A têm código — e mesmo esses dois seguem sem homologação formal porque nenhum rodou a rotina recorrente real que cada carta exige como critério de fechamento. M6/M7/M5 têm especificação pronta e zero linha de coletor.

---

## Módulo 8 — Acidentes e Emergências Ambientais da SEMAD (Carta v1.0, 19/09/2026)

**O que a carta pede**: descobrir comunicados novos/alterados no repositório oficial da SEMAD, abrir cada documento e extrair o texto (nativo ou OCR), classificar vínculo minerário (direto/provável/contextual/inexistente) e gravidade como duas pontuações independentes, gerar alerta auditável com prova e lacunas, encaminhar casos incertos para revisão humana. Situação declarada pela própria carta: "estudo e especificação fechados; implementação e homologação técnica ainda pendentes."

**O que existe em código** (`coletores/m8_acidentes/`): `discovery.py`, `extractor.py`, `signals.py`, `scoring.py`, `checklist_editorial.py`, `db_writer.py`, `main.py`, mais `test_scoring.py`/`test_signals.py`. Implementa literalmente as duas rubricas da carta (score_vinculo §8 e score_gravidade §9), com as faixas A–D, testado contra os 21 casos congelados da amostra de regressão (10 positivos + 10 negativos + 1 limítrofe) — 26/26 passando agora. `discovery.py` traz um aviso explícito no topo: o sandbox onde o código foi escrito não teve acesso de rede à página real da SEMAD, então a descoberta nunca foi exercitada contra o site ao vivo.

**O que falta**: rodar de fato contra a fonte real (0 eventos M8 no banco de produção hoje — nenhum comunicado real passou pelo pipeline); popular `empresa_citada`/`mina_unidade` antes de buscar antecedentes (sem isso, a busca de eventos relacionados do M8 é código morto); gravar timeline processual (hoje só grava uma data única, `data_ultima_verificacao`); scoring ainda lê pesos/faixas hardcoded em Python em vez de `regras_evento.config_json` (a infraestrutura de regra versionada já existe no banco, só não é lida).

## Módulo 9A — Movimentações dos Processos Minerários da ANM (Carta v1.0, 19/09/2026)

**O que a carta pede**: rotina recorrente que descubra movimentações materiais nos processos minerários da ANM (fontes: SCM Microdados, SIGMINE, DOU, SEI), consolide republicações e atos correlatos, aplique a pontuação M9A (SCORE-M9A-V0.2), e entregue estado editorial verificável (liberado / aguardando resposta da empresa / travado por documento). Situação declarada pela carta: "estudo, calibração v0.2 e carga dos cinco casos de controle concluídos; implementação recorrente e homologação técnica ainda pendentes."

**O que existe em código** (`coletores/m9a_movimentacoes/`): `ingestao_scm.py`, `signals.py`, `scoring.py`, `consolidacao.py`, `checklist_editorial.py`, `db_writer.py`, `main.py`, mais os testes — 52/52 passando agora. O trabalho desta sessão foi especificamente aqui: identificamos e corrigimos um bug de arquitetura no classificador — o código anterior comparava palavras-chave contra o texto narrativo livre do ato (`OBEvento`), que varia por redação, em vez da identidade oficial estável do dicionário do SCM (`DSEvento`, por `IDEvento`). Isso produzia falsos negativos (ex.: "GUIA DE UTILIZAÇÃO" vs. "GUIA UTILIZAÇÃO" no mesmo tipo de evento). A correção — novo módulo `classificacao_scm.py` — normaliza removendo preposições/artigos antes de comparar e sempre compara contra o nome do dicionário, nunca contra a narrativa; validamos contra as 2.926 linhas reais de `Evento.txt` que o mesmo padrão de inconsistência aparece em outros tipos de evento, não só no caso trabalhado.

**Produção**: o caso de teste vertical (processo 830.649/2020) foi reprocessado em produção nesta sessão — transação atômica auditável, com fotografia do estado anterior, 8 critérios de validação em trâmite antes do commit, e manifesto de reprocessamento gravado. Confirmei agora, direto no banco: a execução criou 1 execução, 2 marcos de timeline, 12 respostas de checklist, 16 evidências, 1 log de coleta, 1 novo score (vigente) e 1 job de enriquecimento — e o score legado (86, prioridade A) foi preservado como não-vigente, não apagado, exatamente como a trava de integridade exige. Esse era o ponto que eu não tinha conseguido confirmar por completo na sessão anterior (um bloqueio de permissão interrompeu a leitura de verificação); está confirmado agora: a gravação foi completa e correta.

**O que falta**: rodar de forma recorrente (hoje é uma execução pontual de um caso, não uma rotina agendada); repetir em nova data para medir estabilidade (critério explícito de homologação da carta); `EMPRESAS_RELEVANTES`/`MINERAIS_ESTRATEGICOS` continuam hardcoded em Python (o próprio código já registra isso como pendência); só 5 eventos M9A no banco no total.

## Revisão/Calibração de Scores M8 e M9A (carta transversal, sem numeração de módulo)

**O que a carta pede**: é uma carta de governança, não de escopo — decide que a arquitetura de ligar os scores nativos de M8/M9A a uma escala editorial 0–100 pode avançar, mas **nenhuma das duas fórmulas está autorizada para produção** ainda (M8 não tem faixas executáveis/redutores/regra de combinação; M9A só tem as dimensões, sem pesos nem fórmula reprodutível). Também determina cancelar o score 87 do caso Vale (Fábrica e Viga eram dois acidentes distintos, indevidamente combinados) e reprocessar os dois separadamente, ligados por vínculo editorial sem fusão.

**O que existe**: toda a infraestrutura de schema que a fórmula final vai precisar já está pronta e ociosa — `event_scores` tem as 13 colunas necessárias (score_bruto, score_normalizado, versão, prioridade, componentes, gatilhos/redutores/piso/teto aplicados, confiança evidencial), `regras_evento.config_json` já comporta regra versionada com gatilhos/redutores/piso/teto. Conferi agora: as 2 colunas aditivas que faltavam em 28/09 (`event_scores.confianca_evidencial`, `eventos_relacionados.evidencia_id`) e a opcional (`evidencias.campo_sustentado`) **já foram aplicadas em produção** — as três existem hoje. E `score_normalizado` — que em 28/09 nunca era escrito — está preenchido em 100% das 59 linhas de `event_scores` hoje.

**O que falta**: as fórmulas em si. `scoring.py` dos dois módulos continua com pesos/faixas fixos em Python, não lendo `regras_evento.config_json` — ou seja, o "score_normalizado" que já está populado é uma normalização mecânica do score bruto atual, não a fórmula calibrada com redutores/combinação que a carta pede que seja desenhada e testada antes de ir para produção. O caso Vale (separar Fábrica de Viga) segue pendente — não foi tocado em nenhuma sessão até agora.

## Módulo 6 — Outorgas (IGAM), Carta v0.8 Consolidada + Carta de Homologação

**O que a carta pede**: monitorar decisões hídricas do IGAM (Consulta de Decisões de Outorga, ~55.729 registros, mais repositório de portarias) que revelem expansão, paralisação, restrição, conflito, risco, obrigação ou mudança operacional de empreendimento mineral, classificando pelo **verbo decisório** do ato (nunca pelo nome do arquivo). A carta de homologação define um caso de aceite fechado: 3 documentos oficiais, 6 atos segmentados, caso Rima Industrial com resultado esperado (`manutencao_indeferimento`, score 57, Prioridade C), Codemig com revisão controlada, 4 atos não-minerais descartados antes de qualquer chamada de IA, e duas execuções idênticas sem duplicar (6/0/0/0 na repetição).

**O que existe**: nenhum arquivo de coletor no repositório — `coletores/m6_outorgas/` nem existe hoje (nem o `.gitkeep` que a auditoria de 28/09 via permanece). O único trabalho feito no M6 foi um piloto manual via navegador, em outro caso (Conceição do Pará, não o Rima Industrial da carta de homologação), registrado como migration. Em produção: 550 linhas em `outorgas_historico`, que é estoque histórico importado (não é o coletor rodando) — e 0 eventos com módulo M6. A própria carta de homologação já registrava isso em 28/09: "a auditoria da interface não localizou registros da Rima Industrial, da Codemig ou do processo 00722/2025."

**O que falta**: tudo — é o maior gap de código do sistema hoje. Construir do zero, no mesmo padrão do M8 (discovery → extractor → classificação por verbo decisório → scoring → checklist → db_writer → main), usando o caso Rima Industrial como fixture de aceite e o teste de idempotência 6/0/0/0 como critério de pronto.

## Módulo 7 — Copam/CMI, Carta v0.5

**O que a carta pede**: descobrir processos minerários pautados nas reuniões da Câmara de Atividades Minerárias do Copam e acompanhar 11 estados distintos do ciclo (reunião identificada → pauta publicada → parecer inicial/alterado → pedido de vista → retirada → votação → decisão → certificado → ata → outorga vinculada), sem tratar estados como equivalentes (parecer favorável ≠ decisão; decisão ≠ efeitos).

**O que existe**: nenhum coletor no repositório. Os 10 eventos M7 no banco são carga editorial manual (mesmo padrão dos outros módulos sem coletor), não produto de rotina automatizada. A própria carta reconhece trabalho anterior em arquitetura/campos/deduplicação/logs como "válido" mas não há arquivo correspondente no código atual — provavelmente ficou em versões de especificação, não chegou a ser codificado.

**O que falta**: coletor completo, com máquina de estados para os 11 estágios do ciclo da CMI.

## Módulo 5 — Audiências Públicas e EIA/Rima, Carta v0.3.1

**O que a carta pede**: descoberta estruturada na consulta online da SEMAD (divergência conhecida entre 2.293 registros na interface e 1.007 linhas no Excel — a carta já avisa para não tratar o Excel como universo completo), tratando processo como não-único (republicação, prazo alterado, cancelamento e nova convocação geram eventos próprios), com enriquecimento documental de EIA/Rima como camada adicional que não bloqueia o registro básico quando falha.

**O que existe**: nenhum coletor. Os 2 eventos M5 no banco também são carga manual.

**O que falta**: coletor completo — descoberta na consulta SEMAD, tratamento de processo-não-é-chave-única, camada de enriquecimento documental tolerante a falha.

---

## Infraestrutura transversal (vale para todos os módulos, não é específica de uma carta)

Este ponto já estava mapeado em detalhe na auditoria de 28/09 e continua válido: o banco tem hoje **mais estrutura do que os coletores usam**. Checklist editorial (12 perguntas fixas + override por carteira), timeline processual (com campos de prazo que só o M9A usa parcialmente e o M8 não usa), eventos relacionados (vínculo sem fusão — o mecanismo que vai servir o caso Vale quando chegar a vez), job de enriquecimento (idempotência por hash+versão, já correta nos dois coletores que existem), logs reconciliáveis por constraint de banco, e a tabela `maturidade_modulos` (9 estágios de maturidade por módulo) — pronta, mas com **0 linhas hoje**, nunca populada por nenhum coletor. As travas técnicas (triggers que impedem publicar sem revisão humana, apagar sem rastro, ou trocar carteira sem herdar validação) já existem e funcionam, e nenhum trabalho desta sessão nem da auditoria anterior tocou nelas.

No frontend (`painel/index.html`): mostra prioridade, score (sem rótulo de qual), empresa, título, resumo, checklist e uma lista plana de fontes/evidências. Não mostra timeline, eventos relacionados, processamento nem saúde dos módulos — não porque falte tela, mas porque o dado que alimentaria essas abas ainda não é gravado pelos coletores (M8 sem timeline, `maturidade_modulos` vazia).

## Pendência de publicação no GitHub

O código corrigido do M9A nesta sessão (4 commits, testados 52/52 + 26/26) está pronto localmente mas o `git push` para `mineraminas10-rgb/radar-minera-minas` está bloqueado por uma configuração de sessão (não é permissão de conta GitHub — confirmei isso rodando diagnóstico direto contra `api.github.com`, que recusa qualquer repositório, inclusive um alheio, usado só como controle). Entreguei os 4 commits como arquivos `.patch` para você aplicar localmente com `git am` e dar push com suas próprias credenciais — ainda não aplicados no GitHub até você fazer isso.

## Leitura direta

Dos seis instrumentos (M5, M6, M7, M8, M9A, Calibração), só dois têm código rodando — e mesmo esses dois não estão homologados porque nenhuma carta foi satisfeita no critério que ela mesma define para fechar (execução recorrente real para M8/M9A; a rodada de homologação inteira para M6; qualquer coletor, no caso de M5/M7). O que a sessão de hoje mudou concretamente: corrigiu um bug de arquitetura real no M9A (classificação por narrativa em vez de dicionário oficial), validou a correção contra a amostra completa do dicionário do SCM, e executou — com sucesso confirmado ponta a ponta — o primeiro reprocessamento real em produção do engajamento inteiro.

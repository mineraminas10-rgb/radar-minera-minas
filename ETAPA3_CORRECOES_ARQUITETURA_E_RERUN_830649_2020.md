# Etapa 3 — Correções de arquitetura no coletor M9A + reprocessamento local corrigido de `830.649/2020`

Data: 28/09/2026
Continuação de `ETAPA3_PLANO_ESCRITA_REPROCESSAMENTO_830649_2020.md`. **Nenhuma escrita foi feita no Supabase de produção.** Todo este trabalho foi código (`coletores/m9a_movimentacoes/`) + testes automatizados + uma rodada contra a réplica local (`radar_draft_test`), nunca produção. `pytest` no módulo M9A: **52/52** (eram 31 antes desta rodada — 21 testes novos, cobrindo as 4 correções). M8 (26/26) e os dois testes de integração (M8 e M9A) seguem passando, sem regressão.

## 1. As quatro correções, o que mudou e por que são generalizáveis

### 1.1 — Classificador: `Evento.txt` (dicionário oficial) + normalização, não texto livre

Criei `coletores/m9a_movimentacoes/classificacao_scm.py`. Duas peças, nenhuma delas específica ao `IDEvento=2325`:

- `normalizar_termo()`: minúsculas, sem acento, **remove um pequeno conjunto de preposições/artigos** ("de", "da", "do", "das", "dos", "e", "em") antes de qualquer comparação de palavra-chave. Testei contra a amostra real do dicionário inteiro (`Evento.txt`, 2.926 linhas, baixado hoje) e confirmei que a inconsistência de preposição **não é exclusiva da guia de utilização**: o mesmo dicionário tem `"PORTARIA CONCESSÃO DE LAVRA"` e `"ALVARÁ DE PESQUISA"` (com "de") ao lado de `"GUIA UTILIZAÇÃO"` (sem "de") — não dava pra resolver caso a caso, por isso a normalização é a correção certa.
- `sufixo_situacao()`: o dicionário do SCM tem uma gramática de sufixo consistente (`PUBL`/`AUTORIZADA`/`APROVADO` = concluído; `PROTOC`/`REQUERIMENTO` = em trâmite; `INDEFERIDA`/`CANCELADA`/`DEVOLVIDA`/`ANULADA` = negativo). Um teste pego na malha fina: `"GUIA UTILIZAÇÃO INDEFERIDA PUBL"` tem `PUBL` **e** `INDEFERIDA` ao mesmo tempo — a primeira versão que escrevi classificava isso como "concluído" (errado: uma guia indeferida não foi autorizada). Corrigido checando negativo/em-trâmite **antes** de concluído.

`signals.py.extrair_signais_m9a()` e `db_writer.mapear_tipo_marco()` agora classificam **sempre** a partir de `descricao_tipo_evento` (= `DSEvento`, o nome do dicionário, join por `IDEvento` — estável, o mesmo texto para qualquer processo que tiver aquele tipo de evento), nunca mais a partir de `evento_tipo` (narrativa livre `OBEvento`/`DSPublicacaoDOU`, que só entra como `trecho_literal` de evidência). `autorizacao_extracao` e `avanco_pesquisa` agora também exigem `situacao == 'concluido'`, no lugar do antigo `"protocolo" not in evento_tipo` (era um hack específico da palavra "protocolo"; agora é genérico, via sufixo do dicionário).

Ponto de extensão `_OVERRIDE_POR_ID_EVENTO` existe no código, **vazio de propósito** — não criei uma regra específica para o 2325 nem para nenhum outro IDEvento, como você pediu.

### 1.2 — `area_ha` ligado ao pipeline

`consolidacao.Ato` ganhou os campos `id_tipo_evento`, `texto_narrativo` e `area_ha`. `main.py.processar_caso()` agora passa `ato.area_ha` para `linha["area_ha"]`, que `signals.py` já lia mas nunca recebia. `dimensao_objetiva` (+2) passa a disparar de verdade quando há área — testado com `area_ha="1468.73"` (a área real do processo). `area_ha` também virou campo rastreável em `extrair_evidencias_campo()` — antes a área nunca virava evidência gravável, mesmo sendo usada no sinal.

### 1.3 — Sequência processual do mesmo instrumento (emissão → prorrogação)

Em `consolidacao.py`, nova regra 4b: `extrair_identificador_instrumento()` extrai o padrão **"Nº NNN/AAAA"** (com o marcador "Nº"/"N°" explícito) do texto narrativo de um ato. Testei contra os dois textos reais:
- `"Guia n° 61/2023"` (emissão, 2023) → `"61/2023"`
- `"GUIA DE UTILIZAÇÃO N°61/2023"` (prorrogação, 2026) → `"61/2023"` — mesmo identificador, confirma que é a mesma guia
- `"GU - 405/2026"` (o número do PRÓPRIO despacho de prorrogação, não da guia sendo prorrogada) → **não extrai nada**, porque não tem o marcador "Nº" — testei isso especificamente para não confundir os dois números

`chave_caso_editorial()` agora agrupa por `processo + instrumento` quando esse identificador existe, antes de cair na regra 3 (empresa+data+substância+geografia). Isso é o que permite emissão (2023) e prorrogação (2026) da mesma guia caírem no mesmo caso **mesmo com datas diferentes** — sem fundir os fatos: cada ato continua sendo seu próprio marco de timeline, com sua própria evidência (ver §3). O padrão é genérico — qualquer guia/portaria/alvará cujo texto siga a notação "Nº NNN/AAAA" da ANM é reconhecido, testei com números diferentes (`test_instrumentos_diferentes_nao_consolidam`) para confirmar que só agrupa quando o número bate.

Também corrigi, como efeito colateral necessário: `FAMILIAS_COMPLEMENTARES` (decaimento+intimação) comparava contra texto sem normalizar as próprias palavras-chave — `"instauracao de decaimento"` (com "de") nunca batia contra um texto já normalizado (sem "de"). Um teste existente pegou isso (`test_familia_decaimento_e_intimacao...` quebrou ao rodar a suíte depois da correção 1.1, antes de eu consertar `familia_de()`).

**Gap relacionado, NÃO corrigido nesta rodada** (fica registrado, não escondido): as palavras-chave de `FAMILIAS_COMPLEMENTARES` (`"instauracao de decaimento"`, `"decisao de decaimento"` etc.) foram inventadas por mim, sem uma amostra real — e a amostra real que baixei hoje do dicionário mostra nomes bem mais diferentes (`"LEI SNUC-INST PROC ADM DECAIMENTO ALV PESQUISA PUBL"`). Os SINAIS de pontuação (`mudanca_material_direito`, `decaimento_caducidade_ou_interdicao_lavra` em `signals.py`) continuam funcionando, porque usam correspondência de substring simples (`"decaimento" in texto`, que ainda bate). Mas o AGRUPAMENTO por família (`consolidacao.FAMILIAS_COMPLEMENTARES`, usado para juntar "instauração de decaimento" + "intimação para defesa" no mesmo caso) provavelmente não vai bater contra o texto real de decaimento/caducidade da forma como está. Não mexi nisso agora porque não era o que você pediu nesta rodada (você pediu guia de utilização/área/sequência de instrumento) e verificar isso direito precisaria de uma amostra real de casos de decaimento, que não tenho ainda.

### 1.4 — Busca de antecedentes no universo mais amplo (pergunta 11)

Nova função pura `consolidacao.buscar_processos_por_titular_no_universo()` — busca no **universo inteiro ingerido nesta execução** (`main.run()` agora passa `atos` completo, não só o caso sendo processado), não só nos eventos que já existem no Editorial. `main.py.processar_caso()` ganhou o parâmetro `universo_atos` e combina as duas camadas (editorial + universo), com `criterio_vinculo` distinto para cada uma em `eventos_relacionados` (`"mesma_empresa_editorial"` vs. achado do universo).

Para o caso 830.649/2020 especificamente, fiz a busca real (não simulada) contra o universo mais amplo possível — **não o recorte M9A, o cadastro inteiro do SCM**: baixei `ProcessoPessoa.txt` (89 MB, toda relação pessoa↔processo do SCM) e busquei todas as linhas com `IDPessoa=9037559` (o titular, identificado por CNPJ exato em `Pessoa.txt`, critério mais forte que nome em texto). **Resultado: 1 única linha — o próprio 830.649/2020.** Universo pesquisado: `ProcessoPessoa.txt` inteiro (não só os 5 eventos já no Editorial). Critério: `IDPessoa` (CNPJ `43149260000136`). Resultado: 0 processos antecedentes. Isso já está refletido na pergunta 11 do checklist abaixo (`nao_localizado`, agora com busca real por trás, não "não procurei").

### `job_enriquecimento` — nomenclatura corrigida

`versao_enriquecedor` (o campo mais próximo de "o que esse job registra") mudou de `"enriquecedor-m9a-v0.1"` para **`"enriquecedor-m9a-scm-v0.1"`** — nome explícito de que o job cobre só a estruturação via SCM, não o "enriquecimento ambiental" que o texto legado do evento menciona. Confirmei isso gravado na réplica local: `versao_enriquecedor='enriquecedor-m9a-scm-v0.1'`, `status='concluido'` — lido exatamente pelo que é (SCM), não por um enriquecimento ambiental que este coletor não faz. SEMAD/FEAM continua não implementado, sem nenhuma linha fingindo que foi.

## 2. Resultado do rerun — pipeline corrigido, caso real `830.649/2020`

Rodado via `main.processar_caso()` de verdade (não uma simulação isolada), com os dois atos reais do SCM como entrada, contra a réplica local:

**Ato normalizado** (2 atos, mesmo caso — regra 4b):
| Ato | Data | `id_tipo_evento` | `descricao_tipo_evento` (dicionário, usado p/ classificar) | `texto_narrativo` (evidência) |
|---|---|---|---|---|
| Emissão original | 2023-02-14 | 285 | `AUT PESQ/GUIA UTILIZAÇÃO AUTORIZADA PUBL` | "Autoriza a emissão de Guia de Utilização... Guia n° 61/2023... 300.000 toneladas/ano..." |
| Prorrogação | 2026-07-22 | 2325 | `AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL` | "Prorroga por 03 (três) anos... GUIA DE UTILIZAÇÃO N°61/2023..." |

**Sinais** (agregados dos dois atos, OR): `autorizacao_extracao=True` (situação `concluido` nos dois), `mineral_estrategico=True` (minério de ferro), `dimensao_objetiva=True` (área 1.468,73 ha, agora ligada — achado 1.2). Nenhum piso/teto disparado.

**Score bruto → normalizado → prioridade**: `gatilhos_aplicados={autorizacao_extracao:3, mineral_estrategico:2, dimensao_objetiva:2}` → **`score_bruto=7.0`** → **`score_normalizado=70.0`** → **`prioridade='B'`**.

**Checklist**: 6/12 confirmado (1,2,3,4,6,8 — cada um com `evidencia_id` real gravado), 5 `requer_apuracao_humana`, 1 `nao_localizado` (pergunta 11, com a busca real do universo por trás — ver §1.4).

**Completude**: `grau_completude='Media'` (6/12 = 0,50, entre os limiares 0,40–0,75).

**Timeline**: 2 marcos, cada um com sua própria evidência — **os fatos não foram fundidos**:
- `2023-02-14` → `tipo_marco='publicacao'`, trecho = texto da emissão (inclui "300.000 toneladas/ano")
- `2026-07-22` → `tipo_marco='publicacao'`, trecho = texto da prorrogação (**não** menciona toneladas/ano — a capacidade fica só no marco de 2023, como você pediu)

**Evidências**: 16 linhas (8 campos rastreados × 2 atos: `processo`, `evento_tipo`, `descricao_tipo_evento`, `titular`, `substancia`, `municipio`, `data_evento`, `area_ha`), cada uma com `trecho_literal` específico do seu próprio ato.

## 3. Comparação

| | Produção (legado) | Rodada anterior (pré-correção, Cenário A/B) | **Rodada corrigida (agora)** |
|---|---|---|---|
| `score_bruto` | 86 (fora de escala) | 2,0 (A) / 5,0 (B) | **7,0** |
| `score_normalizado` | 86,00 | 20,0 / 50,0 | **70,0** |
| `prioridade` | A | C / B | **B** |
| `gatilhos_aplicados` | nenhum (campo NULL) | `{mineral_estrategico:2}` (+`autorizacao_extracao:3` no B) | **`{autorizacao_extracao:3, mineral_estrategico:2, dimensao_objetiva:2}`** |
| Checklist | 0/12 (tabela vazia) | 6/12 | **6/12** (igual — checklist não dependia das correções) |
| `grau_completude` | `Alta` (sem checklist por trás) | `Media` | **`Media`** |
| `timeline_processual` | 0 marcos | 0 (não gravado ainda no plano anterior) | **2 marcos, cada um com evidência própria, fatos não fundidos** |
| `evidencias` | 0 | 8 (planejadas manualmente) | **16, geradas pelo pipeline real, sem exceção manual** |
| Antecedentes (pergunta 11) | não verificado | não buscado | **buscado no universo inteiro do SCM (89 MB, `ProcessoPessoa.txt`), 0 encontrados** |

A diferença entre a rodada anterior (2,0–5,0) e esta (7,0) não é ajuste de calibração — é o resultado de três coisas reais que passaram a funcionar juntas: classificação estável (não depende mais de qual texto chegou), área ligada ao sinal `dimensao_objetiva`, e os dois atos da mesma guia processados como um caso só (mais sinal agregado, sem fundir os marcos). O score ainda está longe do 86 legado — isso continua sendo o ponto central do achado da Etapa 3: o valor antigo não tem memória de cálculo nenhuma por trás, então não dá pra saber se ele estava “certo” ou só foi atribuído por avaliação editorial solta.

## 4. `status_editorial` — preservado, como pedido

Não toquei em `status_editorial='liberado_para_pre_release'` em lugar nenhum (nem no plano, nem em nenhuma escrita — aliás, nenhuma escrita foi feita em produção). Fica registrada a mesma inconsistência do plano anterior: um evento com esse status ao lado de um checklist 6/12 (não 12/12) é uma contradição visível, mas a decisão de quando/como isso deveria mudar depende de uma regra objetiva que ainda não existe — não decidi isso sozinho.

## 5. O que fica para depois (não fiz, não era o pedido desta rodada)

- Validar `FAMILIAS_COMPLEMENTARES` (agrupamento de decaimento/caducidade) contra uma amostra real de `Evento.txt` — ver §1.3. Os SINAIS de pontuação de decaimento continuam funcionando; o AGRUPAMENTO específico dessa família, não teria como garantir sem amostra real.
- `ingestao_scm.py` foi reescrito para o schema relacional real (9 tabelas, colunas confirmadas contra o dump baixado hoje) no lugar do CSV único fictício de antes — mas **não testei contra o arquivo `ProcessoEvento.txt` completo (1,04 GB)** rodando de ponta a ponta neste sandbox; a lógica de join foi validada com os dados reais deste caso específico, não com o volume total.
- `eventos_relacionados` ainda não é gravado para antecedentes encontrados só no universo (não editorial) — a função de busca existe e funciona (`buscar_processos_por_titular_no_universo`), mas gravar isso exigiria um `event_id`, que só existe depois que o processo antecedente também virar evento — deixei isso registrado como limitação, não inventei um id.

## 6. Antes de qualquer escrita em produção

Nada muda no que já estava pendente de decisão sua (as 3 perguntas do plano anterior ficam resolvidas pelas correções: cenário A/B não existe mais, `area_ha` está ligado, antecedentes foram buscados de verdade). Falta só sua confirmação para eu:
1. Atualizar `ETAPA3_PLANO_ESCRITA_REPROCESSAMENTO_830649_2020.md` com estes números corrigidos (7,0/B/70,0, 2 marcos de timeline, 16 evidências, `job_enriquecimento` renomeado) no lugar dos números da rodada anterior; ou
2. Já seguir direto para a execução das escritas em produção, se você preferir pular a atualização do plano e ir direto pro texto final.

Nenhuma escrita foi feita. Parando aqui.

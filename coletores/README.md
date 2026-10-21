# M10 — Funil de contaminação socioambiental minerária

Camada determinística de triagem, em formato `coletores/m10_contaminacao/avaliador.py`.
Recebe evento/documento previamente coletado por adaptador oficial, registra os termos que
passaram cada gate e produz uma ficha candidata à fila editorial. A ficha nunca é publicada
automaticamente e mantém `revisao_humana: pendente`.

## Gates implementados

1. Atividade minerária: ao menos uma atividade direta no texto/metadado **ou** CNAE alvo.
2. Nexo ambiental amplo: ao menos um sinal hídrico superficial, terrestre ou subterrâneo.
3. Afetação humana/social: ao menos um termo social. Os gates 2 e 3 são cumulativos.
4. Auditoria: dias desde a última movimentação com data ISO; valor da multa apenas se vier
   estruturado com proveniência; alerta de prazo depende da jurisdição e do marco legal.
5. Saída neutra: processo, atividade, sinais encontrados, trecho literal do fiscal, links,
   cronologia e estado de revisão. O código não redige release nem afirma causalidade.

## Limites deliberados

- Isto é o avaliador do funil, não um crawler/OCR. Nenhum adaptador FEAM novo foi acrescentado;
  os coletores atuais ainda precisam fornecer os eventos ao M10 e enviar a ficha para a tabela
  da fila. As fontes oficiais indicadas são rotas para integração, não promessa de captura já ativa.
- Um trecho literal pode conter os sinais ou apenas um deles. `trecho_cobre_os_dois_nexos`
  informa isso; qualquer caso sem URL oficial ou sem trecho exige conferência manual.
- Termos são sinais para triagem, não prova de contaminação nem de nexo causal. A produção deve
  medir falsos positivos/negativos contra documentos reais antes de descartar casos fora da fila.
- A prioridade `ALTA_RELEVANCIA_ALERTA_VERMELHO` segue o limiar editorial informado (>=365 dias
  desde a última movimentação registrada ou <=12 meses até marco legal elegível). Isso é um alerta
  de exposição/inatividade, não um achado de impunidade ou prescrição.
- O código não lê o valor da multa de prosa livre e não presume valor zero quando ausente.
- Não se aplica uma regra universal de cinco anos. Na Lei federal 9.873/1999, o prazo punitivo
  quinquenal tem marco próprio e a prescrição intercorrente administrativa é de três anos.
  Em MG, o art. 2-A da Lei 21.735/2015 prevê hipótese de cinco anos de paralisação por inércia
  exclusiva da Administração. Exige conferir natureza do crédito, marcos, interrupções e autos.
- `data_abertura_processo` é preservada, mas não usada sozinha para contar prescrição. O cálculo
  exige o marco correto por regra e jurisdição; sem isso o campo de meses fica vazio e a ficha
  exibe somente a pendência de conferência jurídica.
- `gerar_ficha_html()` produz um bloco neutro com `<blockquote>`, multa quando informada e dias
  desde a movimentação registrada; desativa comentários. A função apenas gera HTML, sem publicar
  nem gravar no Supabase. A etapa de publicação ainda exige a integração de destino e preserva a
  revisão humana definida para a fila editorial.

## Fontes oficiais para adaptadores

| Órgão | Rota pública identificada | Papel |
|---|---|---|
| SEMAD | https://ecosistemas.meioambiente.mg.gov.br/consulta-ai | Consulta de autos de infração |
| SEMAD | https://meioambiente.mg.gov.br/web/semad/auto-de-infra%C3%A7%C3%A3o | Orientação/andamento e acesso a autos |
| FEAM | https://feam.br/web/feam/%C3%A1reas-impactadas-pela-minera%C3%A7%C3%A3o | Áreas impactadas e passivos minerários |
| FEAM | https://feam.br/w/feam-publica-5-inventario-de-areas-impactadas-pela-mineracao-no-estado | Inventários e documentos vinculados |
| IGAM | https://portalinfohidro.igam.mg.gov.br/monitoramento-da-qualidade-da-%C3%A1gua | Monitoramento da qualidade da água |
| IGAM | https://outorga.meioambiente.mg.gov.br/index.php?r=portaria/listar | Outorgas (rota já cadastrada no M6) |
| COPAM | https://sistemas.meioambiente.mg.gov.br/reunioes/reuniao-copam/index-externo | Reuniões, documentos, decisões e atas |
| ANM | https://www.gov.br/anm/pt-br/acesso-a-informacao/dados-abertos/bases-de-dados | Bases públicas, incluindo dados SIGBM |
| ANM | https://dadosabertos.anm.gov.br/SIGBM/ | Dados abertos SIGBM (rota existente no M9B) |

A captura diária requer adaptadores testados, deduplicação, OCR de PDFs quando aplicável,
registro de URL/hash/data da coleta e escrita idempotente na fila. Essa integração não faz parte
deste patch isolado.

## Integração das regras da carteira nos coletores existentes

M8 e M9A carregam carteira, vínculo da fonte, bandas A–D, critérios e pesos antes de processar
o lote. A decisão de entrada na fila ativa usa as bandas configuradas (A/B), os critérios da
carteira e a elegibilidade própria do módulo. O checklist editorial de 12 itens continua sendo
calculado separadamente e não altera o score.

- M8 mapeia a gravidade normalizada do acidente para o componente `dano_risco` (também aceita o
  rótulo `score_dano_risco`). Não atribui automaticamente a mesma nota a outras dimensões.
- M9A usa o score normalizado do módulo como base. Não transforma o score agregado em notas de
  dano, finanças, novidade ou interesse público.
- Se a carteira tiver peso para componente que o coletor ainda não calcula, o registro conserva
  score/evidências no histórico, mas não entra na fila ativa. O cálculo não usa média parcial e
  grava os pesos pendentes para orientar o próximo mapeamento.
- Em ambos, C/D, critérios não atendidos ou componentes ponderados indisponíveis não são
  descartados do histórico. Nenhum item é publicado automaticamente.

Os componentes customizados configurados na interface precisam corresponder a dimensões que o
coletor consiga medir com os dados de origem. Esse inventário deve crescer com regras explícitas
e validadas contra casos reais; não é seguro inferir dimensões ausentes a partir do score total.

## Executar testes

```bash
cd coletores/m10_contaminacao
python -m unittest -v
```

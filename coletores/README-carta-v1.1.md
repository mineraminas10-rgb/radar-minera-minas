# Filtro de descoberta — Carta Operacional v1.1

Este pacote adiciona uma classificação independente do score e do checklist editorial de 12 itens.

- O setor minerário é confirmado por termo direto, CNAE alvo ou identificador oficial. Vínculo contextual exige duas evidências tipadas e fica pendente.
- Uma porta editorial basta para sinalizar um caso; dano ambiental e impacto social não precisam aparecer juntos.
- O filtro diferencia negativa explícita, alegação/investigação, risco, pedido e decisão.
- Ausência ou inconclusividade vai para revisão humana; nada é apagado nem publicado.
- Watchlist sem fato novo é monitoramento, não nova pauta.
- A saída registra versão, motivo, evidências e URLs.
- O modo padrão é shadow: registra a classificação sem alterar a fila. A integração de M6/M8/M9A e a regressão com casos reais ainda são necessárias antes de ativar bloqueios na fila.

## Arquivos deste pacote

Extraia a partir da raiz do repositório:
- coletores/comum/portas_editoriais.py — arquivo novo
- coletores/avaliador.py — substitui o avaliador existente
- coletores/test_avaliador.py — substitui os testes antigos
- coletores/README-carta-v1.1.md — documentação nova; preserve o README existente

## Validar

No diretório coletores, execute:

    python -m unittest -v test_avaliador.py


## Integracao atual no M9A

coletores/main.py aplica avaliar_descoberta a cada caso consolidado, registra a contagem de resultados em resumo.triagem_carta e inclui a decisao da Carta no resultado de cada caso processado. Na ordenacao com limite de casos, CLASSIFICAR_AGORA vem primeiro; pendentes e nao avaliaveis continuam elegiveis para revisao humana, e casos de rotina/fora de escopo ficam por ultimo. O score de criticidade existente continua como desempate e nao e substituido pelo filtro.

A triagem ainda nao grava os campos da Carta na tabela do Supabase. A coleta deve continuar em piloto ate a regressao M9A rodar com as dependencias do modulo e casos reais de controle.

## Integração de descoberta nos coletores M6 e M8

M6 (outorgas) e M8 (acidentes) também executam avaliar_descoberta em modo shadow depois da leitura do ato ou documento. O resultado triagem_carta acompanha o retorno dos itens do M6 e é gravado junto aos componentes JSON do score nos módulos M6 e M8 quando há score persistido.

A classificação é metadado de descoberta: não substitui o score ponderado, não muda a prioridade da carteira e não descarta automaticamente casos com evidência ausente ou inconclusiva. Os filtros e decisões de cada módulo continuam sendo aplicados pelas regras próprias já configuradas.

O M9A mantém a classificação e a ordenação da Carta no resultado da execução e grava a triagem junto aos componentes JSON do score quando o caso recebe score. Em M6 e M8, a triagem também fica nos componentes JSON do score persistido.

## Verificação desta integração

- Sintaxe verificada com python -m py_compile nos orquestradores M9A, M6 e M8 e no módulo compartilhado.
- Testes do avaliador da Carta passaram.
- Testes de score e sinais do M6/M8 passaram nos diretórios próprios.
- Os testes de coleta que importam o pacote supabase precisam das dependências de requirements.txt; sem o pacote supabase instalado não foi possível executar essa parte da regressão.
- Não foi executada coleta contra fontes reais nem gravação em produção.

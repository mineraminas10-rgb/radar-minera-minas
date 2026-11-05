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

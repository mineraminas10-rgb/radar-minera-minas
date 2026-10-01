"""
Módulo 9A — derivação das 12 respostas do checklist editorial (mesma
Matriz de Fechamento Jornalístico do M8 — as 12 perguntas valem para todos
os módulos, semeadas em `checklist_perguntas`). Ver
coletores/m8_acidentes/checklist_editorial.py para a convenção das 4
respostas ('confirmado' | 'nao_localizado' | 'nao_aplicavel' |
'requer_apuracao_humana') — é a mesma aqui.

Interpretação específica do M9A (diferente do M8 em alguns pontos, porque
o tipo de evento é diferente — M9A é sobre atos administrativos da ANM,
não comunicados de acidente):
  - pergunta 8 ("o que foi determinado ou autorizado") FAZ sentido pro
    M9A (o próprio ato do SCM É uma determinação da ANM), diferente do M8
    onde não se aplicava.
  - pergunta 5 (dimensão) e 9 (situação processual) ficam
    'requer_apuracao_humana', não 'nao_localizado': a carta prevê
    SIGMINE (área/geometria) e SEI/processo judicial (fundamento,
    recursos) como enriquecimento de uma etapa separada (§8) que este
    primeiro pacote não implementa — não procuramos ainda, então não é
    honesto dizer "não localizado".
"""
from typing import Optional

RESPOSTA_CONFIRMADO = "confirmado"
RESPOSTA_NAO_LOCALIZADO = "nao_localizado"
RESPOSTA_NAO_APLICAVEL = "nao_aplicavel"
RESPOSTA_REQUER_APURACAO = "requer_apuracao_humana"


def derivar_checklist_m9a(
    titular: Optional[str] = None,
    municipio: Optional[str] = None,
    data_evento: Optional[str] = None,
    descricao: Optional[str] = None,
    efeito_operacional: Optional[str] = None,  # 'comprovado' | 'provavel' | 'nao_comprovado' | None
    quantidade_processos_no_caso: int = 1,
    teve_antecedentes: bool = False,
) -> dict:
    """Retorna {numero_pergunta (1-12): resposta} para um caso editorial
    consolidado do M9A (um caso pode agrupar vários atos/processos — ver
    consolidacao.py)."""
    respostas = {}

    # 1. O que aconteceu agora? — o(s) ato(s) do SCM são o fato novo.
    respostas[1] = RESPOSTA_CONFIRMADO

    # 2. Quem está envolvido?
    respostas[2] = RESPOSTA_CONFIRMADO if titular else RESPOSTA_NAO_LOCALIZADO

    # 3. Onde aconteceu?
    respostas[3] = RESPOSTA_CONFIRMADO if municipio else RESPOSTA_NAO_LOCALIZADO

    # 4. Quando aconteceu?
    respostas[4] = RESPOSTA_CONFIRMADO if data_evento else RESPOSTA_NAO_LOCALIZADO

    # 5. Qual é a dimensão do fato? (área, geometria) — vem do SIGMINE, que
    #    este pacote ainda não ingere (carta §8, etapa separada).
    respostas[5] = RESPOSTA_REQUER_APURACAO

    # 6. Qual foi a conduta, causa ou objeto?
    respostas[6] = RESPOSTA_CONFIRMADO if descricao else RESPOSTA_NAO_LOCALIZADO

    # 7. Qual foi a consequência ambiental, social, operacional ou econômica?
    #    Mapeia direto pro campo efeito_operacional (carta §10: "comprovado,
    #    provável ou não comprovado").
    if efeito_operacional == "comprovado":
        respostas[7] = RESPOSTA_CONFIRMADO
    elif efeito_operacional == "nao_comprovado":
        respostas[7] = RESPOSTA_NAO_LOCALIZADO
    else:  # 'provavel' ou None
        respostas[7] = RESPOSTA_REQUER_APURACAO

    # 8. O que foi determinado ou autorizado? — diferente do M8: o próprio
    #    ato (cessão, concessão, decaimento etc.) É uma decisão da ANM.
    respostas[8] = RESPOSTA_CONFIRMADO if descricao else RESPOSTA_NAO_LOCALIZADO

    # 9. Qual é a situação processual completa (recursos, exaurimento)? —
    #    vem do SEI/processo judicial, também §8 (não implementado aqui).
    respostas[9] = RESPOSTA_REQUER_APURACAO

    # 10. O que acontece agora (prazo, próximo marco)? — depende do
    #     enriquecimento obrigatório da carta §8, que este coletor não
    #     executa sozinho (ver main.py: pendencia_apuracao sempre aponta
    #     pra isso).
    respostas[10] = RESPOSTA_REQUER_APURACAO

    # 11. Qual é o histórico relevante? — confirmado quando o caso já
    #     agrupa mais de um ato/processo (histórico dentro do próprio
    #     caso) OU quando achamos casos anteriores da mesma empresa.
    if quantidade_processos_no_caso > 1 or teve_antecedentes:
        respostas[11] = RESPOSTA_CONFIRMADO
    else:
        respostas[11] = RESPOSTA_NAO_LOCALIZADO

    # 12. O que dizem empresa, órgão e terceiros? — sem busca de
    #     contraditório implementada.
    respostas[12] = RESPOSTA_REQUER_APURACAO

    return respostas


# Limiares documentados de 28/09/2026 (achado da auditoria: events.grau_completude
# já existia no schema desde antes, mas nenhum coletor o preenchia). Cobertura
# = proporção de respostas 'confirmado' sobre as 12 perguntas — NUNCA a
# partir do tamanho do texto (regra explícita da Rapha, 28/09/2026). Mesmos
# limiares usados em coletores/m8_acidentes/checklist_editorial.py.
LIMIAR_GRAU_ALTA = 0.75   # >= 9/12 confirmadas
LIMIAR_GRAU_MEDIA = 0.40  # >= 5/12 confirmadas


def calcular_grau_completude(respostas: dict) -> str:
    """Retorna 'Alta' | 'Media' | 'Baixa' (mesmos valores do enum
    grau_completude do banco) a partir da proporção de respostas
    'confirmado' entre as 12 perguntas do checklist — mesma convenção de
    denominador (12, não só as aplicáveis) já usada hoje no painel
    ("Atende N de 12 pontos")."""
    if not respostas:
        return "Baixa"
    confirmadas = sum(1 for r in respostas.values() if r == RESPOSTA_CONFIRMADO)
    proporcao = confirmadas / 12
    if proporcao >= LIMIAR_GRAU_ALTA:
        return "Alta"
    if proporcao >= LIMIAR_GRAU_MEDIA:
        return "Media"
    return "Baixa"

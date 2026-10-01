"""
Módulo 6 — derivação das 12 respostas do checklist editorial (mesmas 12
perguntas genéricas de `checklist_perguntas`, usadas por todos os módulos
— ver coletores/m8_acidentes/checklist_editorial.py para o mesmo padrão).

Lógica pura, sem tocar banco (ver test_checklist_editorial.py).
"""
from typing import Optional

RESPOSTA_CONFIRMADO = "confirmado"
RESPOSTA_NAO_LOCALIZADO = "nao_localizado"
RESPOSTA_NAO_APLICAVEL = "nao_aplicavel"
RESPOSTA_REQUER_APURACAO = "requer_apuracao_humana"


def derivar_checklist_m6(
    fora_de_escopo: bool,
    tipo_evento_normalizado: str,
    titular: Optional[str] = None,
    municipio: Optional[str] = None,
    data_decisao: Optional[str] = None,
    processo_ou_portaria: Optional[str] = None,
    vazao_volume_documentado: bool = False,
    finalidade_uso: Optional[str] = None,
    score_calculado: bool = False,
    tem_cronologia_anterior: bool = False,
    recurso_ou_reconsideracao_pendente: Optional[bool] = None,
) -> dict:
    """Retorna {numero_pergunta (1-12): resposta}."""

    if fora_de_escopo:
        # Carta M6 §43.4: "Fora de escopo [...] não recebe prioridade
        # editorial" — o checklist completo não se aplica a um ato sem
        # vínculo mineral, só o registro de descarte (log_coleta).
        return {n: RESPOSTA_NAO_APLICAVEL for n in range(1, 13)}

    if tipo_evento_normalizado == "indeterminado":
        # Verbo decisório não identificado — carta §23: nunca presumir
        # classificação a partir de elemento posterior. Tudo pendente de
        # apuração humana, não "não localizado" (ainda nem sabemos o que
        # procurar).
        return {n: RESPOSTA_REQUER_APURACAO for n in range(1, 13)}

    respostas = {}

    # 1. O que aconteceu agora? — a própria publicação do ato é o fato novo.
    respostas[1] = RESPOSTA_CONFIRMADO

    # 2. Quem está envolvido?
    respostas[2] = RESPOSTA_CONFIRMADO if titular else RESPOSTA_NAO_LOCALIZADO

    # 3. Onde aconteceu?
    respostas[3] = RESPOSTA_CONFIRMADO if municipio else RESPOSTA_NAO_LOCALIZADO

    # 4. Quando aconteceu?
    respostas[4] = RESPOSTA_CONFIRMADO if data_decisao else RESPOSTA_NAO_LOCALIZADO

    # 5. Qual é a dimensão do fato? (vazão/volume/área — carta §44.5 contrato de dados)
    respostas[5] = RESPOSTA_CONFIRMADO if vazao_volume_documentado else RESPOSTA_NAO_LOCALIZADO

    # 6. Qual foi a conduta, causa ou objeto?
    respostas[6] = RESPOSTA_CONFIRMADO if (finalidade_uso or processo_ou_portaria) else RESPOSTA_NAO_LOCALIZADO

    # 7. Qual foi a consequência? — só calculamos de verdade depois do score rodar.
    respostas[7] = RESPOSTA_CONFIRMADO if score_calculado else RESPOSTA_REQUER_APURACAO

    # 8. O que foi determinado ou autorizado? — aqui SIM é o núcleo do M6
    #    (ato administrativo de outorga), diferente do M8.
    respostas[8] = RESPOSTA_CONFIRMADO if tipo_evento_normalizado != "indeterminado" else RESPOSTA_REQUER_APURACAO

    # 9. Qual é a situação processual?
    if recurso_ou_reconsideracao_pendente is None:
        respostas[9] = RESPOSTA_REQUER_APURACAO
    else:
        respostas[9] = RESPOSTA_CONFIRMADO

    # 10. O que acontece agora (prazo e próximo marco)? — carta §44.7:
    #     "determinação de novo ato não significa que o novo ato já tenha
    #     sido publicado" — isso é sempre uma pendência de monitoramento,
    #     nunca uma resposta fechada por este coletor.
    respostas[10] = RESPOSTA_REQUER_APURACAO

    # 11. Qual é o histórico relevante?
    respostas[11] = RESPOSTA_CONFIRMADO if tem_cronologia_anterior else RESPOSTA_NAO_LOCALIZADO

    # 12. O que dizem empresa, órgão e terceiros? — busca de contraditório
    #     não é parte deste coletor (mesma razão do M8).
    respostas[12] = RESPOSTA_REQUER_APURACAO

    return respostas


LIMIAR_GRAU_ALTA = 0.75
LIMIAR_GRAU_MEDIA = 0.40


def calcular_grau_completude(respostas: dict) -> str:
    """Mesmos limiares de M8/M9A — cobertura = proporção de 'confirmado'
    sobre as 12 perguntas, nunca a partir do tamanho do texto."""
    if not respostas:
        return "Baixa"
    confirmadas = sum(1 for r in respostas.values() if r == RESPOSTA_CONFIRMADO)
    proporcao = confirmadas / 12
    if proporcao >= LIMIAR_GRAU_ALTA:
        return "Alta"
    if proporcao >= LIMIAR_GRAU_MEDIA:
        return "Media"
    return "Baixa"

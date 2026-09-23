"""
Módulo 8 — derivação das 12 respostas do checklist editorial (Checklist
Completo de Enriquecimento e Pré-Release, seção "Matriz de fechamento
jornalístico" — as mesmas 12 perguntas valem para todos os módulos, já
semeadas em `checklist_perguntas` no banco).

Este arquivo só decide qual resposta ('confirmado' | 'nao_localizado' |
'nao_aplicavel' | 'requer_apuracao_humana') cabe pra cada uma das 12
perguntas, a partir do que o coletor M8 já extraiu. É lógica pura, sem
tocar banco — dá pra testar sem Supabase (ver test_checklist_editorial.py).

IMPORTANTE — isto é interpretação minha, não algo que o checklist crava
byte a byte (ele é genérico, vale pra 9 módulos diferentes). Documentei o
raciocínio de cada pergunta abaixo; se a Rapha quiser outro critério é só
ajustar aqui, o resto do coletor não muda.

Convenção das 4 respostas (mesmo texto do checklist, seção "Como usar"):
  - 'confirmado'            -> achamos e temos evidência (equivale ao "Sim"
                                do checklist; o enum do banco usa esse nome).
  - 'nao_localizado'        -> procuramos no texto e não achamos.
  - 'nao_aplicavel'         -> a pergunta não se aplica a este tipo de evento.
  - 'requer_apuracao_humana' -> este coletor (primeira versão) ainda não
                                tenta responder essa pergunta sozinho (ex.:
                                contraditório, próximo marco) — não é o
                                mesmo que "não localizado", que implica que
                                já foi procurado.
"""
from typing import Optional

RESPOSTA_CONFIRMADO = "confirmado"
RESPOSTA_NAO_LOCALIZADO = "nao_localizado"
RESPOSTA_NAO_APLICAVEL = "nao_aplicavel"
RESPOSTA_REQUER_APURACAO = "requer_apuracao_humana"


def derivar_checklist_m8(
    extracao_falhou: bool,
    faixa_vinculo: str,
    empresa_citada: Optional[str] = None,
    local_descrito: Optional[str] = None,
    municipio: Optional[str] = None,
    data_hora_ocorrencia: Optional[str] = None,
    volume_quantidade: Optional[float] = None,
    descricao_literal: Optional[str] = None,
    modalidade: Optional[str] = None,
    score_gravidade_calculado: bool = False,
    teve_antecedentes: bool = False,
) -> dict:
    """Retorna {numero_pergunta (1-12): resposta}. Ver checklist_perguntas
    no banco para o texto exato de cada pergunta."""

    if extracao_falhou:
        # carta §16 / checklist "Falha de download, OCR, busca ou IA nunca
        # autoriza... transformar ausência de achado em inexistência" —
        # documento não abriu, então quase tudo fica pra apuração humana,
        # não "não localizado" (não chegamos nem a procurar no texto).
        return {n: RESPOSTA_REQUER_APURACAO for n in range(1, 13)}

    respostas = {}

    # 1. O que aconteceu agora? — o próprio comunicado é o fato novo.
    respostas[1] = RESPOSTA_CONFIRMADO

    # 2. Quem está envolvido?
    respostas[2] = RESPOSTA_CONFIRMADO if empresa_citada else RESPOSTA_NAO_LOCALIZADO

    # 3. Onde aconteceu?
    respostas[3] = RESPOSTA_CONFIRMADO if (local_descrito or municipio) else RESPOSTA_NAO_LOCALIZADO

    # 4. Quando aconteceu?
    respostas[4] = RESPOSTA_CONFIRMADO if data_hora_ocorrencia else RESPOSTA_NAO_LOCALIZADO

    # 5. Qual é a dimensão do fato? (volume/quantidade — carta §6 grupo Evento)
    respostas[5] = RESPOSTA_CONFIRMADO if volume_quantidade is not None else RESPOSTA_NAO_LOCALIZADO

    # 6. Qual foi a conduta, causa ou objeto?
    respostas[6] = RESPOSTA_CONFIRMADO if (descricao_literal or modalidade) else RESPOSTA_NAO_LOCALIZADO

    # 7. Qual foi a consequência ambiental, social, operacional ou econômica?
    #    Só calculamos isso de verdade quando o vínculo já foi confirmado/
    #    aprovado e o score de gravidade rodou (carta §9). Se o caso foi
    #    descartado por não ser minerário, a pergunta não se aplica a ESTE
    #    módulo (o M8 só mede consequência de acidente minerário).
    if faixa_vinculo == "descartado":
        respostas[7] = RESPOSTA_NAO_APLICAVEL
    elif score_gravidade_calculado:
        respostas[7] = RESPOSTA_CONFIRMADO
    else:
        respostas[7] = RESPOSTA_REQUER_APURACAO

    # 8. O que foi determinado ou autorizado? — M8 é um comunicado de
    #    ocorrência, não uma decisão administrativa (isso é M1/M3/M7).
    #    Não aplicável por natureza do módulo.
    respostas[8] = RESPOSTA_NAO_APLICAVEL

    # 9. Qual é a situação processual? — mesma razão da 8: comunicado de
    #    acidente não abre processo por si só neste coletor (cruzar com
    #    M3/autos de infração é um passo futuro, não implementado aqui).
    respostas[9] = RESPOSTA_NAO_APLICAVEL

    # 10. O que acontece agora (prazo e próximo marco)? — este coletor não
    #     calcula prazo/próximo marco pra acidentes; fica sempre para a
    #     revisão humana decidir o encaminhamento.
    respostas[10] = RESPOSTA_REQUER_APURACAO

    # 11. Qual é o histórico relevante? — depende de eventos_relacionados
    #     (antecedentes por empresa/mina) terem sido encontrados.
    respostas[11] = RESPOSTA_CONFIRMADO if teve_antecedentes else RESPOSTA_NAO_LOCALIZADO

    # 12. O que dizem empresa, órgão e terceiros? — este coletor não faz
    #     busca de contraditório (etapa separada, carta não descreve isso
    #     pro M8) — sempre pendente de apuração, nunca "não localizado".
    respostas[12] = RESPOSTA_REQUER_APURACAO

    return respostas

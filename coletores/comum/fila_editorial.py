"""Regras de entrada na fila ativa, sem apagar score, prioridade ou histórico.

Os limiares são nativos de cada módulo. Score normalizado não é comparado entre
M8 e M9A para decidir relevância editorial.
"""

PRIORIDADES_ATIVAS = {"A", "B"}


def elegibilidade_m8(faixa_vinculo: str, prioridade: str) -> tuple[bool, str]:
    """M8: vínculo provável/confirmado e banda configurada A/B entram na fila.

    A banda é calculada no score editorial 0–100 da carteira; não há um piso
    adicional fixo na escala bruta de gravidade do coletor.
    """
    if faixa_vinculo not in ("provavel", "confirmado"):
        return False, "vinculo_nao_suficiente"
    if prioridade not in PRIORIDADES_ATIVAS:
        return False, "abaixo_das_bandas_A_B_da_carteira"
    return True, "prioridade_A_B_com_gravidade_de_pauta"


def elegibilidade_m9a(prioridade: str) -> tuple[bool, str]:
    """M9A: a criticidade/prioridade final decide se o caso entra na fila.

    O score bruto do M9A usa escala própria (0–10); não se compara esse valor
    diretamente com score normalizado (0–100). A régua de criticidade já
    aplica os parâmetros do sistema e a faixa A/B é a política editorial de
    entrada na fila ativa. O score, checklist e evidências são preservados.
    """
    if prioridade not in PRIORIDADES_ATIVAS:
        return False, "abaixo_do_piso_editorial_m9a"
    return True, "prioridade_A_B_pela_regua_editorial"

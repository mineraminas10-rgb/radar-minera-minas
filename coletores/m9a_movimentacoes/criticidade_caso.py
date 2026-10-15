"""
Ponte entre os atos consolidados do M9A (consolidacao.Ato) e a régua de criticidade comum (CRIT-V1.2).

Um CASO pode agrupar vários atos do mesmo processo/instrumento. A criticidade do caso é a do seu MELHOR ato
(maior nível; empate: maior pontuação de reforços; empate: ato mais recente). Cada ato é classificado pelo
tipo oficial do dicionário SCM (DSEvento), nunca pela narrativa livre do ato.
"""
import os
import sys
from datetime import date
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import criticidade as crit


def _entrada(ato, n_municipios: int) -> dict:
    return {
        "tipo_scm": ato.descricao, "data_ato": ato.data_evento, "titular": ato.empresa,
        "substancia": ato.substancia, "area_ha": ato.area_ha, "n_municipios": n_municipios,
        # o ato vem de um registro oficial do SCM (microdados da ANM): essa é a evidência oficial do caso
        "tem_evidencia": True,
    }


def criticidade_do_caso(atos: List, par: dict, referencia: date) -> crit.ResultadoCriticidade:
    n_mun = len({a.municipio for a in atos if a.municipio})
    melhor = None
    melhor_chave = None
    for ato in atos:
        r = crit.classificar_m9a(_entrada(ato, n_mun), par, referencia)
        chave = (par["niveis"].index(r.nivel) if r.nivel in par["niveis"] else -1, r.pontuacao, -(r.idade_dias if r.idade_dias is not None else 10 ** 9))
        if melhor is None or chave > melhor_chave:
            melhor, melhor_chave = r, chave
    return melhor


def data_mais_recente(atos: List) -> str:
    return max((str(a.data_evento) for a in atos), default="")


def janela_data_minima(par: dict, referencia: date, janela_dias: Optional[int]) -> Optional[str]:
    """Data mínima (AAAA-MM-DD) dos eventos que valem a leitura nesta rodada. `janela_dias` None = usa o
    parâmetro versionado m9a.janela_leitura_dias; 0 = sem filtro de data."""
    dias = par["m9a"]["janela_leitura_dias"] if janela_dias is None else janela_dias
    if not dias:
        return None
    from datetime import timedelta
    return (referencia - timedelta(days=dias)).isoformat()

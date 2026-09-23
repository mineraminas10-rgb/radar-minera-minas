"""
Módulo 9A (Movimentações dos Processos Minerários da ANM) — motor de
pontuação. Implementa a rubrica SCORE-M9A-V0.2 da Carta Operacional
Módulo 9A v1.0 (19/09/2026), seções 6 e 7 (travas semânticas).

Escala 0 a 10 (§6). Faixas: A 8-10, B 5-7, C 2-4, D 0-1.

Versão da regra: SCORE-M9A-V0.2.
"""
from dataclasses import dataclass
from typing import List, Tuple

VERSAO_REGRA_SCORE = "SCORE-M9A-V0.2"


@dataclass
class SignaisM9A:
    # Positivos (carta §6)
    mudanca_material_direito: bool = False    # +4 — decaimento/caducidade/cessão/transferência/penhora/indisponibilidade/interdição/renúncia/concessão
    autorizacao_extracao: bool = False        # +3 — guia de utilização ou portaria de lavra (exclui mero protocolo)
    avanco_pesquisa: bool = False             # +3 — relatório aprovado, nova substância ou reavaliação aprovada
    alvara_comum_pesquisa: bool = False       # +2 — só como sinal de monitoramento quando isolado
    dimensao_objetiva: bool = False           # +2 — área, volume, tonelagem, produção ou outra grandeza
    empresa_relevante: bool = False           # +2 — grande porte ou importância regional/nacional
    mineral_estrategico: bool = False         # +2 — ferro, ouro, lítio, manganês, nióbio, grafite, terras raras, cobalto, níquel, fosfato, titânio
    reserva_ou_substancia: bool = False       # +1 — nova substância ou reavaliação de reserva
    varios_municipios: bool = False           # +1 — dois ou mais municípios no mesmo processo

    # Redutores (carta §6, cada um com teto próprio — ver §7)
    rotina: bool = False                      # -5, teto final 1 — protocolo, juntada, pagamento TAH/RAL, documento diverso
    exigencia_generica: bool = False          # -3, teto final 4 — não pode virar alerta isolado
    retificacao_formal: bool = False          # -2 — quando não altera área/prazo/interdição/suspensão/elemento material

    # Trava de piso (carta §7): SUBCONJUNTO específico de mudanca_material_direito.
    # A carta dá o piso mínimo A só para decaimento/caducidade/interdição de
    # CONCESSÃO DE LAVRA — não para os outros atos do mesmo grupo (cessão,
    # transferência, penhora, indisponibilidade, renúncia, concessão
    # simples). Por isso é um sinal separado, não o mesmo booleano.
    decaimento_caducidade_ou_interdicao_lavra: bool = False


def score_m9a(sig: SignaisM9A) -> Tuple[float, str, List[str]]:
    """Retorna (score, faixa, justificativa) — Carta M9A §6/§7.

    faixa in {'A' (8-10), 'B' (5-7), 'C' (2-4), 'D' (0-1)}
    """
    pontos = 0.0
    justificativa: List[str] = []

    positivos = [
        (sig.mudanca_material_direito, 4, "mudança material do direito (+4)"),
        (sig.autorizacao_extracao, 3, "autorização de extração (+3)"),
        (sig.avanco_pesquisa, 3, "avanço de pesquisa (+3)"),
        (sig.alvara_comum_pesquisa, 2, "alvará comum de pesquisa (+2)"),
        (sig.dimensao_objetiva, 2, "dimensão objetiva (+2)"),
        (sig.empresa_relevante, 2, "empresa relevante (+2)"),
        (sig.mineral_estrategico, 2, "mineral estratégico (+2)"),
        (sig.reserva_ou_substancia, 1, "reserva ou substância (+1)"),
        (sig.varios_municipios, 1, "vários municípios (+1)"),
    ]
    for ativo, valor, texto in positivos:
        if ativo:
            pontos += valor
            justificativa.append(texto)

    # Escala é 0-10 (§6); espelha o teto de acumulação positiva do M8 antes
    # dos redutores, por simetria — a carta M9A não repete essa frase
    # explicitamente, então isto é uma leitura minha: CONFIRMAR COM A RAPHA.
    pontos = min(pontos, 10)

    if sig.rotina:
        pontos -= 5
        justificativa.append("rotina: protocolo/juntada/TAH/RAL/documento diverso (-5)")
    if sig.exigencia_generica:
        pontos -= 3
        justificativa.append("exigência genérica (-3)")
    if sig.retificacao_formal:
        pontos -= 2
        justificativa.append("retificação formal, sem alteração material (-2)")

    pontos = max(pontos, 0.0)

    # Tetos semânticos (§7) — aplicados depois dos redutores.
    if sig.rotina:
        pontos = min(pontos, 1)
        justificativa.append("teto: rotina não gera prioridade A/B isoladamente (§7)")
    if sig.exigencia_generica:
        pontos = min(pontos, 4)
        justificativa.append("teto: exigência genérica não vira alerta isolado (§7)")

    tem_reforco = sig.dimensao_objetiva or sig.empresa_relevante or sig.mineral_estrategico
    if sig.avanco_pesquisa and not tem_reforco:
        pontos = min(pontos, 7)
        justificativa.append("teto B: relatório de pesquisa aprovado sem dimensão/empresa relevante/mineral estratégico (§7)")

    outro_gatilho = any([
        sig.mudanca_material_direito, sig.autorizacao_extracao, sig.avanco_pesquisa,
        sig.dimensao_objetiva, sig.empresa_relevante, sig.mineral_estrategico,
        sig.reserva_ou_substancia, sig.varios_municipios,
    ])
    if sig.alvara_comum_pesquisa and not outro_gatilho:
        pontos = min(pontos, 4)
        justificativa.append("teto C: alvará comum de pesquisa sem outro gatilho (§7)")

    if sig.reserva_ou_substancia and not sig.dimensao_objetiva:
        pontos = min(pontos, 7)
        justificativa.append("teto B: reavaliação de reserva sem dimensão comprovada (§7)")

    # Piso (§7) — aplicado por último, prevalece sobre os tetos acima no
    # caso (não esperado na prática) de conflito.
    if sig.decaimento_caducidade_ou_interdicao_lavra:
        pontos = max(pontos, 8)
        justificativa.append("piso A: decaimento/caducidade/interdição de concessão de lavra (§7) — "
                              "não autoriza afirmar perda do título antes da decisão final")

    if pontos >= 8:
        faixa = "A"
    elif pontos >= 5:
        faixa = "B"
    elif pontos >= 2:
        faixa = "C"
    else:
        faixa = "D"

    return pontos, faixa, justificativa

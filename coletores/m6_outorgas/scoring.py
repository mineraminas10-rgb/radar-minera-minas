"""
Módulo 6 (Outorgas de Recursos Hídricos do IGAM) — motor de pontuação.

Implementa a Função de score M6 v1 (Carta Operacional M6 v0.8, §43.3/43.4/
43.5), confirmada como "ainda válida" pela Carta de Homologação M6-V1.0 §1.

Diferença importante em relação a M8/M9A: lá, cada componente nasce de um
sinal BOOLEANO extraído do texto (ex.: "tem antecedente? sim/não" -> +N
pontos fixos). Aqui a própria carta não dá uma subfórmula determinística
por componente — dá uma régua descritiva (8 componentes, cada um com um
máximo e uma "regra" de que tipo de fato conta) e espera julgamento
editorial informado por ela, com memória de cálculo registrando o motivo
de cada pontuação parcial. O exemplo oficial (carta de homologação §4.2,
caso Rima) é exatamente assim: "Consequência operacional e regulatória:
8 de 20 — indeferimento mantido para um poço; efeito sobre a operação não
comprovado" — não há uma regra tipo "+8 se X".

Por isso `calcular_score_m6()` recebe os 8 componentes já como pontos
atribuídos (0 <= ponto <= máximo do componente), não como sinais booleanos
— e a responsabilidade desta função é: validar os limites, aplicar as
travas e redutores documentados (que SÓ reduzem, nunca aumentam), somar e
classificar na faixa. Quem atribui o ponto por componente (humano ou IA)
deve registrar a justificativa — é isso que `ComponenteScore.justificativa`
guarda, e que vira a memória de cálculo auditável.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Máximos por componente (carta M6 v0.8 §43.3) — soma = 100.
MAXIMOS = {
    "consequencia_operacional_regulatoria": 20,
    "dimensao_hidrica_fisica": 20,
    "risco_conflito_interesse_publico": 15,
    "materialidade_evento": 15,
    "novidade_sinal_temporal": 10,
    "cruzamentos_historico": 10,
    "relevancia_empresa_projeto": 5,
    "potencial_exclusividade": 5,
}

ORDEM_COMPONENTES = list(MAXIMOS.keys())


@dataclass
class ComponenteScore:
    pontos: float
    justificativa: str


@dataclass
class TravasM6:
    """Carta §43.5 — só reduzem, nunca aumentam. Nenhuma combinação destas
    travas pode produzir um score fora de [0, 100]; `calcular_score_m6`
    garante isso independente da soma bruta dos componentes."""
    vinculo_apenas_presumido: bool = False          # trava de B: teto 59
    parecer_sem_decisao_ou_recurso_pendente: bool = False  # trava de A: teto 79
    redutor_pontos: float = 0.0                     # 10 a 25, carta §43.5 (areia/registro antigo/retificação cadastral/etc.)
    motivo_redutor: str = ""


FAIXA_POR_PONTOS = (
    (80, 100, "A"),
    (60, 79, "B"),
    (35, 59, "C"),
    (0, 34, "D"),
)


def classificar_faixa(pontos_finais: float, fora_de_escopo: bool = False) -> str:
    """'A' | 'B' | 'C' | 'D' | 'Fora'. `fora_de_escopo` é decidido fora
    desta função (signals.tem_vinculo_mineral) — score M6 nunca promove
    um ato sem vínculo mineral para dentro das faixas A-D, mesmo que a
    soma dos componentes dê um número alto (carta §43.4: "Fora de
    escopo [...] Não recebe prioridade editorial, mesmo que ocorra em
    município minerador")."""
    if fora_de_escopo:
        return "Fora"
    for minimo, maximo, faixa in FAIXA_POR_PONTOS:
        if minimo <= pontos_finais <= maximo:
            return faixa
    return "D"  # defensivo; pontos_finais já é clampado em [0,100] por calcular_score_m6


def calcular_score_m6(
    componentes: dict,  # {nome_componente: ComponenteScore}
    travas: Optional[TravasM6] = None,
    fora_de_escopo: bool = False,
) -> Tuple[float, str, dict]:
    """Retorna (score_total 0-100, faixa, memoria_calculo). Levanta
    ValueError se algum componente faltar ou exceder seu máximo — nunca
    silenciosamente clampa um erro de quem chamou (isso escondaria um bug
    de atribuição de pontos, não uma trava documentada)."""
    travas = travas or TravasM6()

    faltando = set(ORDEM_COMPONENTES) - set(componentes.keys())
    if faltando:
        raise ValueError(f"componentes faltando: {sorted(faltando)}")

    soma = 0.0
    detalhe = {}
    for nome in ORDEM_COMPONENTES:
        c = componentes[nome]
        maximo = MAXIMOS[nome]
        if not (0 <= c.pontos <= maximo):
            raise ValueError(f"componente {nome}: pontos={c.pontos} fora de [0,{maximo}]")
        soma += c.pontos
        detalhe[nome] = {"pontos": c.pontos, "maximo": maximo, "justificativa": c.justificativa}

    pontos_finais = soma
    travas_aplicadas = []

    if travas.redutor_pontos:
        pontos_finais -= travas.redutor_pontos
        travas_aplicadas.append(f"redutor de {travas.redutor_pontos} pontos: {travas.motivo_redutor}")

    if travas.parecer_sem_decisao_ou_recurso_pendente and pontos_finais > 79:
        pontos_finais = 79
        travas_aplicadas.append("trava de A: parecer sem decisão/recurso pendente — teto 79")

    if travas.vinculo_apenas_presumido and pontos_finais > 59:
        pontos_finais = 59
        travas_aplicadas.append("trava de B: vínculo mineral apenas presumido — teto 59")

    pontos_finais = max(0.0, min(100.0, pontos_finais))

    faixa = classificar_faixa(pontos_finais, fora_de_escopo=fora_de_escopo)

    memoria = {
        "versao_regra": "SCORE-M6-V1",
        "componentes": detalhe,
        "soma_bruta_componentes": soma,
        "travas_aplicadas": travas_aplicadas,
        "score_final": pontos_finais,
        "faixa": faixa,
        "fora_de_escopo": fora_de_escopo,
    }
    return pontos_finais, faixa, memoria

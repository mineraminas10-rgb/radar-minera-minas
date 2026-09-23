"""
Módulo 8 (Acidentes e Emergências Ambientais da SEMAD) — motor de pontuação.

Implementa literalmente as duas rubricas da Carta Operacional Módulo 8 v1.0
(19/09/2026), seções 8 e 9. As duas pontuações são INDEPENDENTES por
desenho: score_vinculo responde só "isso pertence ao universo editorial do
Minera Minas?" e score_gravidade só é calculado depois que o vínculo está
confirmado ou aprovado em revisão humana (§5 passo 9, §9 primeiro parágrafo).

Este arquivo só faz a MATEMÁTICA da regra sobre um conjunto de sinais já
identificados (SignaisVinculo / SignaisGravidade). A extração desses sinais
a partir do texto real do comunicado (extractor.py) é uma etapa separada —
ver o aviso no topo de extractor.py sobre o que está e o que não está
validado contra documento real ainda.

Versão da regra: SCORE-M8-V1.0 (Carta Operacional Módulo 8 v1.0, §8/§9).
Qualquer mudança material nos limiares/pesos exige nova versão e regressão
proporcional (carta §21).
"""
from dataclasses import dataclass, fields
from typing import List, Tuple

VERSAO_REGRA_SCORE = "SCORE-M8-V1.0"


# ============================================================================
# Score de vínculo minerário (Carta §8)
# ============================================================================

@dataclass
class SignaisVinculo:
    # Positivos
    modalidade_mineracao: bool = False              # +4 — campo modalidade ou descrição identifica mineração
    mina_identificada: bool = False                  # +4 — mina/complexo/mineradora nomeada no local, fonte ou descrição
    material_mineral: bool = False                   # +5 — minério, rejeito, polpa mineral, estéril ou sedimento da operação
    insumo_estrutura_vinculada: bool = False          # +2 — nitrato de amônia, polímero, sump, cava, pilha, usina, barragem, sirene — COM vínculo confirmado
    municipio_minerador: bool = False                 # +1 — só como desempate, exige outra evidência direta já presente
    # Redutores (só se aplicam quando NÃO há evidência direta de vínculo —
    # a própria regra os define como "sem empresa/destino/operação mineral")
    produto_causa_nao_mineraria: bool = False          # -4
    acidente_rodoviario_comum: bool = False            # -3

    # ------------------------------------------------------------------
    # ADIÇÃO MINHA, fora da tabela literal de 7 regras do §8 — sinalizar
    # para a Rapha confirmar/ajustar antes de considerar definitivo.
    #
    # A carta tem um "caso limítrofe obrigatório" (§13, coque verde de
    # petróleo em São João del-Rei) que precisa terminar em revisão humana
    # (faixa 'provavel'), mas cuja descrição não acorda nenhuma das 7
    # regras pontuadas: não há modalidade/mina/material/insumo confirmado
    # (o documento não comprova vínculo), mas também não é "sem relação
    # nenhuma" (há relação com cadeia mineral/industrial) — não é
    # 'produto_causa_nao_mineraria' nem 'acidente_rodoviario_comum' no
    # sentido literal da regra. Sem um sinal próprio, esse caso cairia em
    # score=0/descartado, o que contradiz §13 ("não deve descartar
    # automaticamente"). Este sinal cobre exatamente essa lacuna: produto
    # ou carga claramente ligado a cadeia mineral/industrial, mas sem
    # confirmação documental de vínculo com mineradora/mina/operação.
    # Quando marcado (e nenhuma regra das 7 já classificou o caso como
    # 'confirmado'), força piso de 5 pontos (faixa 'provavel') — nunca
    # confirma, nunca descarta.
    cadeia_mineral_industrial_nao_confirmada: bool = False


def score_vinculo(sig: SignaisVinculo) -> Tuple[float, str, List[str]]:
    """Retorna (score, faixa, justificativa) — Carta M8 §8.

    faixa in {'confirmado' (8-10), 'provavel' (5-7), 'contextual' (2-4), 'descartado' (<2)}
    """
    pontos = 0.0
    justificativa: List[str] = []

    if sig.modalidade_mineracao:
        pontos += 4
        justificativa.append("modalidade declarada como mineração (+4)")
    if sig.mina_identificada:
        pontos += 4
        justificativa.append("mina/complexo/mineradora identificada (+4)")
    if sig.material_mineral:
        pontos += 5
        justificativa.append("material mineral da operação (+5)")
    if sig.insumo_estrutura_vinculada:
        pontos += 2
        justificativa.append("insumo/estrutura ligada à operação, vínculo confirmado (+2)")

    tem_evidencia_direta = any([
        sig.modalidade_mineracao, sig.mina_identificada,
        sig.material_mineral, sig.insumo_estrutura_vinculada,
    ])

    if sig.municipio_minerador:
        if tem_evidencia_direta:
            pontos += 1
            justificativa.append("município minerador, como desempate (+1)")
        else:
            justificativa.append("município minerador ignorado — não é prova suficiente sozinho (carta §8, M8-A05)")

    # Carta §8: "Os pontos positivos podem ser acumulados até 10" — teto
    # aplicado ANTES dos redutores.
    pontos = min(pontos, 10)

    # Redutores: a própria regra os define condicionados a ausência de
    # evidência direta ("sem empresa, destino ou operação mineral" /
    # "sem carga, destino ou empresa relacionados ao setor") — carta M8-A07
    # exige explicitamente que carga de minério confirmada não seja
    # descartada só pela modalidade rodoviária.
    if sig.produto_causa_nao_mineraria and not tem_evidencia_direta:
        pontos -= 4
        justificativa.append("produto/causa não minerária, sem empresa/destino/operação mineral (-4)")
    if sig.acidente_rodoviario_comum and not tem_evidencia_direta:
        pontos -= 3
        justificativa.append("acidente rodoviário comum, sem carga/destino/empresa do setor (-3)")

    if sig.cadeia_mineral_industrial_nao_confirmada and pontos < 5:
        pontos = 5
        justificativa.append(
            "carga/produto ligado a cadeia mineral ou industrial sem confirmação documental de "
            "vínculo — piso de revisão humana, não confirma nem descarta (carta §13; regra adicional, "
            "confirmar com a Rapha)"
        )

    if pontos >= 8:
        faixa = "confirmado"
    elif pontos >= 5:
        faixa = "provavel"
    elif pontos >= 2:
        faixa = "contextual"
    else:
        faixa = "descartado"

    return pontos, faixa, justificativa


# ============================================================================
# Score de gravidade (Carta §9) — só roda após vínculo confirmado/aprovado
# ============================================================================

@dataclass
class SignaisGravidade:
    atingiu_ou_pode_atingir_curso_dagua: bool = False              # +3
    ultrapassou_limites_operacao: bool = False                     # +2
    rejeito_ou_produto_perigoso_ou_volume_significativo: bool = False  # +2
    risco_estrutural_ou_interrupcao_abastecimento: bool = False    # +2
    comunicacao_mais_de_6_horas: bool = False                      # +1
    vitimas_evacuacao_bloqueio_ou_risco_comunidade: bool = False   # +1


def score_gravidade(sig: SignaisGravidade) -> Tuple[float, str]:
    """Retorna (score, nivel) — Carta M8 §9.

    nivel in {'alerta_imediato' (>=7), 'pauta_apuracao' (4-6),
              'registro_acompanhamento' (1-3), 'arquivo_contextual' (0)}
    """
    pontos = 0.0
    if sig.atingiu_ou_pode_atingir_curso_dagua:
        pontos += 3
    if sig.ultrapassou_limites_operacao:
        pontos += 2
    if sig.rejeito_ou_produto_perigoso_ou_volume_significativo:
        pontos += 2
    if sig.risco_estrutural_ou_interrupcao_abastecimento:
        pontos += 2
    if sig.comunicacao_mais_de_6_horas:
        pontos += 1
    if sig.vitimas_evacuacao_bloqueio_ou_risco_comunidade:
        pontos += 1

    if pontos >= 7:
        nivel = "alerta_imediato"
    elif pontos >= 4:
        nivel = "pauta_apuracao"
    elif pontos >= 1:
        nivel = "registro_acompanhamento"
    else:
        nivel = "arquivo_contextual"

    return pontos, nivel


def calcular_atraso_minutos(data_hora_ocorrencia, data_hora_comunicacao) -> int:
    """Carta §6/§8-A08: atraso entre ocorrência e comunicação, em minutos.
    Ambos os parâmetros devem ser datetime com timezone (aware)."""
    delta = data_hora_comunicacao - data_hora_ocorrencia
    return int(delta.total_seconds() // 60)

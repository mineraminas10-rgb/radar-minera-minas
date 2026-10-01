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

# ----------------------------------------------------------------------------
# Pesos documentados (extração pura dos números já usados dentro de
# score_vinculo/score_gravidade abaixo — não muda nenhum cálculo, só dá um
# nome endereçável a cada peso pra montar_memoria_calculo_* conseguir
# montar gatilhos_aplicados/redutores_aplicados sem duplicar a lógica de
# pontuação num segundo lugar). Adição de 28/09/2026, etapa "pipeline" da
# implementação do Escopo v2.8 — a fórmula em si (valores, faixas) não foi
# tocada.
# ----------------------------------------------------------------------------
PESOS_VINCULO = {
    "modalidade_mineracao": 4,
    "mina_identificada": 4,
    "material_mineral": 5,
    "insumo_estrutura_vinculada": 2,
    "municipio_minerador": 1,
}
REDUTORES_VINCULO = {
    "produto_causa_nao_mineraria": -4,
    "acidente_rodoviario_comum": -3,
}
PESOS_GRAVIDADE = {
    "atingiu_ou_pode_atingir_curso_dagua": 3,
    "ultrapassou_limites_operacao": 2,
    "rejeito_ou_produto_perigoso_ou_volume_significativo": 2,
    "risco_estrutural_ou_interrupcao_abastecimento": 2,
    "comunicacao_mais_de_6_horas": 1,
    "vitimas_evacuacao_bloqueio_ou_risco_comunidade": 1,
}

# Teto teórico usado só para normalizar score_bruto em score_normalizado
# (0-100) — NÃO é uma trava nova da fórmula (a fórmula/faixas continuam
# exatamente como a Carta M8 v1.0 define). score_gravidade é o score_bruto
# realmente gravado em event_scores (main.py só chama gravar_score() com
# score_gravidade, nunca com score_vinculo) — por isso o teto de
# normalização é a soma dos pesos positivos de PESOS_GRAVIDADE (11), não os
# 10 do vínculo. A carta não define um teto explícito pra gravidade (só
# define os limiares de nível) — esta é uma leitura minha para permitir
# ranking transversal comparável a outros módulos; confirmar com a Rapha
# antes de considerar definitiva.
TETO_NORMALIZACAO_GRAVIDADE = float(sum(PESOS_GRAVIDADE.values()))  # = 11.0


def calcular_score_normalizado(score_bruto: float, teto_teorico: float = TETO_NORMALIZACAO_GRAVIDADE) -> float:
    """Reescala score_bruto (escala própria do módulo) para 0-100, para
    permitir ranking transversal entre módulos (score_normalizado é o campo
    que a fila do editor usa para comparar eventos de módulos diferentes —
    nunca compare score_bruto entre módulos diretamente)."""
    if teto_teorico <= 0:
        return 0.0
    normalizado = (max(score_bruto, 0.0) / teto_teorico) * 100
    return round(min(normalizado, 100.0), 2)


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


def montar_memoria_calculo_vinculo(sig: SignaisVinculo, justificativa: List[str]) -> dict:
    """Extrai, dos sinais já calculados por score_vinculo (não recalcula
    nada), os gatilhos/redutores que estavam ativos — para popular
    event_scores.gatilhos_aplicados/redutores_aplicados (memória de cálculo
    auditável, Carta de Calibração M8/M9A, campo de normalização). Chamar
    DEPOIS de score_vinculo(sig), com a mesma justificativa que ele devolveu."""
    gatilhos = {campo: peso for campo, peso in PESOS_VINCULO.items() if getattr(sig, campo, False)}
    redutores = {campo: peso for campo, peso in REDUTORES_VINCULO.items() if getattr(sig, campo, False)}
    if sig.cadeia_mineral_industrial_nao_confirmada:
        gatilhos["cadeia_mineral_industrial_nao_confirmada_piso5"] = 5

    # ACHADO da auditoria de 28/09/2026, corrigido aqui: event_scores.
    # piso_aplicado/teto_aplicado são numeric(6,2) no banco, mas esta
    # função gravava a LISTA de texto da justificativa (não um número) —
    # isso teria estourado com IntegrityError/InvalidTextRepresentation em
    # qualquer evento real que disparasse o piso de §13 (não testado antes
    # porque nenhum caso de teste anterior tinha
    # cadeia_mineral_industrial_nao_confirmada=True). O valor correto é o
    # piso numérico que score_vinculo() de fato aplica (5), não o texto da
    # regra — detectamos SE ele disparou olhando a mesma justificativa que
    # score_vinculo() já produziu (não recalculamos pontos aqui).
    piso_disparado = any(j.startswith("carga/produto ligado") for j in justificativa)
    return {
        "gatilhos_aplicados": gatilhos,
        "redutores_aplicados": redutores,
        "piso_aplicado": 5.0 if piso_disparado else None,
        "teto_aplicado": None,  # vínculo só tem teto de acumulação (10), já refletido no próprio pontos
    }


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


def montar_memoria_calculo_gravidade(sig: SignaisGravidade) -> dict:
    """Idem à de vínculo, para score_gravidade — não tem redutores nem
    piso/teto semânticos na Carta §9 (só soma direta até o limiar de nível)."""
    gatilhos = {campo: peso for campo, peso in PESOS_GRAVIDADE.items() if getattr(sig, campo, False)}
    return {
        "gatilhos_aplicados": gatilhos,
        "redutores_aplicados": {},
        "piso_aplicado": None,
        "teto_aplicado": None,
    }


def calcular_atraso_minutos(data_hora_ocorrencia, data_hora_comunicacao) -> int:
    """Carta §6/§8-A08: atraso entre ocorrência e comunicação, em minutos.
    Ambos os parâmetros devem ser datetime com timezone (aware)."""
    delta = data_hora_comunicacao - data_hora_ocorrencia
    return int(delta.total_seconds() // 60)

"""
Decisão PRÉ-IA dos coletores (espelho em Python do gate de supabase/functions/_shared/gate.ts).

Fluxo obrigatório (nunca "fonte -> IA -> ver se era relevante"):
  FONTE -> CAPTURA -> NORMALIZAÇÃO -> HASH -> COMPARAÇÃO -> DEDUPLICAÇÃO -> FILTRO DE ESCOPO
  -> REGRAS DETERMINÍSTICAS -> TRAVAS -> DECISÃO SE IA É NECESSÁRIA -> IA -> SCORE -> EVIDÊNCIAS -> REVISÃO HUMANA

Este módulo é a "DECISÃO SE IA É NECESSÁRIA" do lado do coletor: quando o motivo de dispensa existe,
o coletor NEM FAZ a requisição ao executar-ai (zero chamada, zero token). O servidor repete a
mesma checagem (defesa em profundidade) e ainda faz a idempotência por hash.

Hoje os coletores M8/M9A não chamam IA (classificação por sinais/regex). Este módulo registra, em
cada rodada, quantos registros SERIAM elegíveis e quantos foram dispensados e por quê — é a base
das métricas do piloto — e é o único ponto por onde uma chamada futura poderá passar.
"""
from collections import Counter
from typing import Dict, Optional

# Mesma ordem e mesmos nomes de supabase/functions/_shared/gate.ts (CAMPOS_PRE_IA).
CAMPOS_PRE_IA = (
    "registro_identico",
    "hash_igual_ultimo_sucesso",
    "republicacao_literal",
    "fora_de_escopo",
    "descartado_por_regra_deterministica",
    "continuidade_sem_mudanca_material",
    "enriquecimento_ja_concluido",
    "bloqueado_por_falta_de_documento",
    "tarefa_sem_linguagem_natural",
)


def motivo_de_dispensa(flags: Dict[str, bool]) -> Optional[str]:
    """Primeiro motivo (na ordem do gate) que dispensa a IA; None = elegível."""
    for campo in CAMPOS_PRE_IA:
        if flags.get(campo) is True:
            return campo
    desconhecidos = set(flags) - set(CAMPOS_PRE_IA)
    if desconhecidos:
        raise ValueError(f"flags pré-IA desconhecidos: {sorted(desconhecidos)}")
    return None


# ---------------------------------------------------------------------------------------
# M8 — acidentes SEMAD
# ---------------------------------------------------------------------------------------
def flags_m8(*, extracao_falhou: bool, faixa_vinculo: Optional[str],
             hash_documento: Optional[str], hash_documento_anterior: Optional[str],
             ja_processado: bool = False, caso_ambiguo_elegivel: bool = False) -> Dict[str, bool]:
    """Regras de economia do M8:
      - documento idêntico (hash) ao já processado -> zero IA;
      - documento já processado -> zero IA;
      - falha de extração: a IA não inventa o documento ausente -> zero IA;
      - vínculo 'descartado' (acidente não minerário) -> zero IA;
      - só 'provavel'/'confirmado' (ou caso ambíguo explicitamente elegível) segue para análise cara.
    'contextual' fica no histórico sem alerta (Carta M8 §8): sem IA, a menos que seja marcado ambíguo."""
    f: Dict[str, bool] = {}
    if hash_documento and hash_documento_anterior and hash_documento == hash_documento_anterior:
        f["hash_igual_ultimo_sucesso"] = True
        f["registro_identico"] = True
    if ja_processado:
        f["enriquecimento_ja_concluido"] = True
    if extracao_falhou:
        # sem documento não há faixa confiável: o motivo real é a falta do documento
        f["bloqueado_por_falta_de_documento"] = True
        return f
    if faixa_vinculo == "descartado":
        f["descartado_por_regra_deterministica"] = True
    elif faixa_vinculo == "contextual" and not caso_ambiguo_elegivel:
        f["descartado_por_regra_deterministica"] = True
    elif faixa_vinculo not in ("provavel", "confirmado", "contextual", "descartado"):
        f["descartado_por_regra_deterministica"] = True   # faixa desconhecida: não gasta token
    return f


# ---------------------------------------------------------------------------------------
# M9A — movimentações ANM
# ---------------------------------------------------------------------------------------
def flags_m9a(*, fora_do_recorte: bool = False, ato_generico_nao_material: bool = False,
              republicacao_literal: bool = False, caso_sem_delta: bool = False,
              ja_enriquecido: bool = False) -> Dict[str, bool]:
    """Regras de economia do M9A:
      - protocolo, juntada, TAH, RAL, exigência genérica e famílias excluídas -> zero IA;
      - republicação literal -> zero IA;
      - ato já consolidado sem novo delta -> zero IA;
      - só mudança material segue para enriquecimento."""
    f: Dict[str, bool] = {}
    if fora_do_recorte:
        f["fora_de_escopo"] = True
    if ato_generico_nao_material:
        f["descartado_por_regra_deterministica"] = True
    if republicacao_literal:
        f["republicacao_literal"] = True
    if caso_sem_delta:
        f["continuidade_sem_mudanca_material"] = True
    if ja_enriquecido:
        f["enriquecimento_ja_concluido"] = True
    return f


# ---------------------------------------------------------------------------------------
# M9B (quando existir) — regras já fixadas aqui para não serem esquecidas
# ---------------------------------------------------------------------------------------
def flags_m9b(*, hash_estado_identico: bool = False, continuidade_sem_delta: bool = False,
              apenas_ausencia_simples: bool = False, delta_relevante: bool = False) -> Dict[str, bool]:
    """M9B: id_sigbm com hash_estado idêntico -> zero IA; continuidade sem delta -> zero IA; ausência
    simples NÃO autoriza interpretar descaracterização; IA só para delta relevante depois das regras."""
    f: Dict[str, bool] = {}
    if hash_estado_identico:
        f["registro_identico"] = True
    if continuidade_sem_delta:
        f["continuidade_sem_mudanca_material"] = True
    if apenas_ausencia_simples:
        f["descartado_por_regra_deterministica"] = True
    if not delta_relevante and not f:
        f["continuidade_sem_mudanca_material"] = True
    return f


class ContadorPreIa:
    """Métricas da rodada para o relatório do piloto. `chamadas_reais` fica 0 aqui: o coletor só
    DECIDE; quem chama (e conta tokens/custo) é a função executar-ai, em api_execucoes."""

    def __init__(self) -> None:
        self.coletados = 0
        self.dispensados = Counter()
        self.elegiveis = 0
        self.chamadas_reais = 0

    def registrar(self, flags: Dict[str, bool]) -> Optional[str]:
        self.coletados += 1
        motivo = motivo_de_dispensa(flags)
        if motivo:
            self.dispensados[motivo] += 1
        else:
            self.elegiveis += 1
        return motivo

    def resumo(self) -> Dict[str, object]:
        total_dispensados = sum(self.dispensados.values())
        return {
            "pre_ia_coletados": self.coletados,
            "pre_ia_dispensados": total_dispensados,
            "pre_ia_elegiveis": self.elegiveis,
            "pre_ia_por_motivo": dict(self.dispensados),
            "chamadas_ia": self.chamadas_reais,
            "chamadas_ia_evitadas": total_dispensados,
        }

"""
Gravação da criticidade no banco como NOVA VERSÃO de score (event_scores.versao_score = 'CRIT-V1.2').

Não existe segunda arquitetura: reaproveita event_scores. A linha antiga (SCORE-M9A-V0.2 / SCORE-M8-V1.0 /
notas manuais) NÃO é apagada nem alterada; apenas deixa de ser a vigente (vigente=false) — o índice único
uq_event_scores_vigente (event_id, estagio) WHERE vigente permite uma só vigente por estágio. A prioridade A-D
da linha nova é DERIVADA da criticidade (CRITICO=A, ALTA=B, MEDIA=C, BAIXA/ROTINA=D); NAO_AVALIAVEL e os estados
POTENCIAL_*_PENDENTE_EVIDENCIA ficam com prioridade nula (sem prioridade definitiva).

Reclassificação automática: gravar_criticidade compara a nova classificação com a vigente (nível, objeto, fase,
motivos, provisória, suficiência de evidência). Quando a evidência/tipo oficial entra e o resultado muda, a linha
antiga é preservada (vigente=false) e a nova passa a vigente; o histórico nunca é apagado.
"""
from typing import Optional

from criticidade import ResultadoCriticidade


def linha_score(event_id: str, res: ResultadoCriticidade, empresa_id: Optional[str] = None,
                estagio: str = "preliminar") -> dict:
    return {
        "event_id": event_id,
        "score_bruto": res.pontuacao,
        "score_normalizado": res.pontuacao,
        "versao_score": res.versao_regra,
        "prioridade": res.prioridade,
        "componentes": res.como_componentes(),
        "justificativa_score": res.resumo_motivos(),
        "gatilhos_aplicados": {r: 1 for r in res.reforcos},
        "redutores_aplicados": {},
        "piso_aplicado": None,
        "teto_aplicado": None,
        "vigente": True,
        "estagio": estagio,
        "empresa_id": empresa_id,
    }


def _mesma_classificacao(comp: Optional[dict], res: ResultadoCriticidade) -> bool:
    """Reexecutar o coletor com o mesmo resultado não deve empilhar linhas idênticas no histórico (a idade em
    dias muda todo dia, por isso não entra na comparação)."""
    if not comp:
        return False
    return (comp.get("criticidade") == res.nivel and comp.get("objeto") == res.objeto and comp.get("fase") == res.fase
            and comp.get("motivos") == res.motivos and comp.get("versao_parametros") == res.versao_parametros
            and bool(comp.get("provisoria")) == bool(res.provisoria)
            and comp.get("evidencia_suficiente", True) == res.evidencia_suficiente
            and comp.get("nivel_potencial") == res.nivel_potencial)


def gravar_criticidade(sb, event_id: str, res: ResultadoCriticidade, empresa_id: Optional[str] = None,
                       estagio: str = "preliminar") -> str:
    """Devolve 'gravado' ou 'inalterado'."""
    atual = (sb.table("event_scores").select("id,versao_score,componentes")
             .eq("event_id", event_id).eq("vigente", True).eq("estagio", estagio).execute().data or [])
    if atual and atual[0].get("versao_score") == res.versao_regra and _mesma_classificacao(atual[0].get("componentes"), res):
        return "inalterado"
    if atual:
        sb.table("event_scores").update({"vigente": False}).eq("event_id", event_id).eq("vigente", True) \
            .eq("estagio", estagio).execute()
    sb.table("event_scores").insert(linha_score(event_id, res, empresa_id, estagio)).execute()
    return "gravado"

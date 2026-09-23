"""
Módulo 9A — escrita no Supabase via service_role key. Mesmos padrões do
db_writer.py do M8 (upsert por id_evento, event_scores nunca sobrescrito,
auditoria_correcoes em toda mudança de campo existente) — ver comentários
lá para o raciocínio completo.

Diferença específica do M9A: os atos individuais vão para
timeline_processual (carta §5 regra 5 — "manter os atos individuais na
timeline, contar apenas um caso em Editorial"), e o caso consolidado tem
sua própria linha em m9a_movimentacao_estado.

Variáveis de ambiente esperadas: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

MODULO = "M9A_anm_movimentacoes"
VERSAO_COLETOR = "m9a-movimentacoes-v0.1"


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def buscar_fonte_id(sb: Client) -> str:
    """F14 na base real (confirmado ao vivo em 23/09/2026, ver LEIA-ME) —
    a fonte primária deste coletor é o SCM Microdados; SIGMINE (F15) e DOU
    entram só no enriquecimento §8, ainda não implementado."""
    r = sb.table("sources").select("id").eq(
        "url_base", "https://dadosabertos.anm.gov.br/SCM/microdados/"
    ).limit(1).execute()
    if not r.data:
        raise RuntimeError(
            "Fonte do M9A (SCM Microdados) não encontrada em sources — ela já existe na base "
            "real da Rapha (F14), então esse erro só deveria aparecer numa réplica de teste sem seed."
        )
    return r.data[0]["id"]


def criar_execucao(sb: Client, id_execucao: str, ambiente: str = "piloto") -> str:
    r = sb.table("execucoes").insert({
        "id_execucao": id_execucao,
        "inicio": datetime.now(timezone.utc).isoformat(),
        "ambiente": ambiente,
        "versao_coletor": VERSAO_COLETOR,
        "versao_score": {"m9a": "SCORE-M9A-V0.2"},
        "status_final": "parcial",
    }).execute()
    return r.data[0]["id"]


def finalizar_execucao(sb: Client, execucao_id: str, totais: dict, status_final: str = "concluída"):
    sb.table("execucoes").update({
        "fim": datetime.now(timezone.utc).isoformat(),
        "totais": totais,
        "status_final": status_final,
    }).eq("id", execucao_id).execute()


def buscar_evento_por_id_evento(sb: Client, id_evento: str) -> Optional[dict]:
    r = sb.table("events").select("*").eq("id_evento", id_evento).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_caso_editorial(sb: Client, id_evento: str, campos_evento: dict, execucao_id: str) -> tuple:
    existente = buscar_evento_por_id_evento(sb, id_evento)
    if existente is None:
        payload = {"id_evento": id_evento, "modulo": MODULO,
                   "execucao_criacao_id": execucao_id, **campos_evento}
        r = sb.table("events").insert(payload).execute()
        return r.data[0]["id"], True

    diffs = {}
    for campo, valor_novo in campos_evento.items():
        valor_anterior = existente.get(campo)
        if valor_anterior != valor_novo and valor_novo is not None:
            diffs[campo] = (valor_anterior, valor_novo)

    if diffs:
        sb.table("events").update(campos_evento).eq("id", existente["id"]).execute()
        for campo, (anterior, novo) in diffs.items():
            sb.table("auditoria_correcoes").insert({
                "event_id": existente["id"],
                "campo_alterado": campo,
                "valor_anterior": str(anterior) if anterior is not None else None,
                "valor_novo": str(novo) if novo is not None else None,
                "metodo_extracao": "coletor_automatico",
                "versao_regra": "SCORE-M9A-V0.2",
            }).execute()
    return existente["id"], False


def upsert_m9a_estado(sb: Client, event_id: str, familia_chave: str, estado: dict):
    payload = {"event_id": event_id, "familia_chave": familia_chave, **estado}
    sb.table("m9a_movimentacao_estado").upsert(payload, on_conflict="event_id").execute()


def gravar_ato_na_timeline(sb: Client, event_id: str, tipo_marco: str, data_marco: str,
                            trecho_literal: Optional[str] = None, url_documento: Optional[str] = None):
    """Carta §5 regra 5: atos individuais ficam na timeline mesmo quando
    consolidados em um único caso editorial."""
    sb.table("timeline_processual").insert({
        "event_id": event_id,
        "tipo_marco": tipo_marco,
        "data_marco": data_marco,
        "trecho_literal": trecho_literal,
        "url_documento": url_documento,
    }).execute()


def gravar_score(sb: Client, event_id: str, score_bruto: float, prioridade: str, componentes: dict,
                  versao_score: str = "SCORE-M9A-V0.2"):
    sb.table("event_scores").update({"vigente": False}).eq("event_id", event_id).eq("vigente", True).execute()
    sb.table("event_scores").insert({
        "event_id": event_id, "score_bruto": score_bruto, "versao_score": versao_score,
        "prioridade": prioridade, "componentes": componentes, "vigente": True,
    }).execute()


# ----------------------------------------------------------------------------
# Extensão — Checklist Completo de Enriquecimento e Pré-Release (mesma
# extensão feita no db_writer.py do M8; ver os comentários lá para o
# raciocínio de cada tabela). Diferenças específicas do M9A:
#   - Não existe `documentos` aqui nesta primeira versão: os campos vêm de
#     uma planilha (SCM Microdados), não de um documento aberto e lido
#     (SEI/DOU são enriquecimento §8, ainda não implementado) — criar uma
#     linha em `documentos` fingindo que abrimos um documento oficial
#     seria inventar proveniência que não existe. `evidencias` aqui
#     referencia documento_id=None (a tabela permite isso).
#   - Não existe `log_busca` aqui nesta primeira versão: o arquivo de
#     microdados é baixado pelo `curl` do workflow do GitHub Actions,
#     antes deste código rodar — o Python não faz a requisição HTTP, só lê
#     o arquivo já baixado, então não há uma URL própria pra logar aqui
#     (ver TODO no coletor_m9a.yml sobre a URL do SCM ainda não confirmada).
# ----------------------------------------------------------------------------

def gravar_evidencias_caso(sb: Client, event_id: str, evidencias: list):
    """`evidencias` é uma lista de {campo, trecho_literal} vinda dos
    valores literais do SCM (ex.: titular, substância, tipo de ato) — não
    é texto de documento (ver aviso no topo do arquivo), por isso
    documento_id sempre None e tipo_afirmacao='fato' (são valores oficiais
    da planilha, não inferência do coletor)."""
    for ev in evidencias:
        sb.table("evidencias").insert({
            "event_id": event_id,
            "documento_id": None,
            "trecho_literal": str(ev["trecho_literal"])[:2000],
            "resumo_extraido": f"campo: {ev['campo']}",
            "tipo_afirmacao": "fato",
            "metodo_extracao": "planilha_scm",
        }).execute()


def gravar_checklist_editorial(sb: Client, event_id: str, respostas: dict,
                                prioridade: Optional[str] = None):
    for numero, resposta in respostas.items():
        sb.table("checklist_editorial").upsert({
            "event_id": event_id,
            "pergunta_numero": numero,
            "resposta": resposta,
            "prioridade": prioridade,
        }, on_conflict="event_id,pergunta_numero").execute()


def buscar_antecedentes_m9a(sb: Client, id_evento_atual: str, titular: Optional[str]) -> list:
    """Checklist §Cruzamentos: casos anteriores da mesma empresa (critério
    mais fraco que CNPJ, que o SCM Microdados não traz como campo -- ver
    aviso equivalente em coletores/m8_acidentes/db_writer.py). Não afirma
    causalidade nem continuidade operacional, só relaciona."""
    if not titular:
        return []
    r = sb.table("events").select("id, id_evento").eq(
        "modulo", "M9A_anm_movimentacoes"
    ).eq("empresa", titular).neq("id_evento", id_evento_atual).execute()
    return [row["id"] for row in r.data]


def gravar_eventos_relacionados(sb: Client, event_id_atual: str, antecedentes: list,
                                 criterio_vinculo: str = "mesma_empresa"):
    for event_id_relacionado in antecedentes:
        sb.table("eventos_relacionados").upsert({
            "event_origem_id": event_id_atual,
            "event_relacionado_id": event_id_relacionado,
            "criterio_vinculo": criterio_vinculo,
            "status_relacao": "observado_automatico_requer_revisao",
            "confianca": None,
        }, on_conflict="event_origem_id,event_relacionado_id,criterio_vinculo").execute()


def gravar_job_enriquecimento(sb: Client, event_id: str, hash_entrada: str, status: str,
                               tempo_gasto_segundos: Optional[float] = None,
                               erro: Optional[str] = None,
                               versao_enriquecedor: str = "enriquecedor-m9a-v0.1"):
    existente = sb.table("job_enriquecimento").select("id, tentativas").eq(
        "event_id", event_id
    ).eq("hash_entrada", hash_entrada).eq("versao_enriquecedor", versao_enriquecedor).limit(1).execute()

    payload = {
        "status": status,
        "tempo_gasto_segundos": int(tempo_gasto_segundos) if tempo_gasto_segundos is not None else None,
        "erro": erro,
    }
    if existente.data:
        sb.table("job_enriquecimento").update({
            **payload, "tentativas": existente.data[0]["tentativas"] + 1,
        }).eq("id", existente.data[0]["id"]).execute()
    else:
        sb.table("job_enriquecimento").insert({
            "event_id": event_id, "hash_entrada": hash_entrada,
            "versao_enriquecedor": versao_enriquecedor, "tentativas": 1, **payload,
        }).execute()


def registrar_log_coleta(sb: Client, execucao_id: str, source_id: Optional[str], contagens: dict):
    sb.table("log_coleta").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        **contagens,
    }).execute()

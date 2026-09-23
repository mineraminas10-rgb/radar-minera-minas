"""
Módulo 8 — escrita no Supabase via service_role key (nunca a anon key —
o coletor roda em ambiente de confiança do GitHub Actions, não no
navegador). Segue os mesmos padrões já usados no resto do Radar:
  - events.id_evento é a chave de negócio estável, upsert por ela.
  - event_scores nunca é sobrescrito: recálculo marca vigente=false na
    linha antiga e insere uma nova vigente=true (mesmo padrão do
    recalcular_carteiras() em SQL).
  - toda alteração de campo já existente vira uma linha em
    auditoria_correcoes (padrão Anglo, carta M8 §7/§15).

Variáveis de ambiente esperadas (nunca hardcoded, nunca passam por mim):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

MODULO = "M8_acidentes_ambientais"
VERSAO_COLETOR = "m8-acidentes-v0.1"


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def buscar_fonte_id(sb: Client) -> str:
    r = sb.table("sources").select("id").eq(
        "url_base", "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"
    ).limit(1).execute()
    if not r.data:
        raise RuntimeError(
            "Fonte do M8 não encontrada em sources — rodar antes o SQL de schema "
            "(01_schema_m8_m9a.sql), que cadastra essa fonte."
        )
    return r.data[0]["id"]


def criar_execucao(sb: Client, id_execucao: str, ambiente: str = "piloto") -> str:
    r = sb.table("execucoes").insert({
        "id_execucao": id_execucao,
        "inicio": datetime.now(timezone.utc).isoformat(),
        "ambiente": ambiente,
        "versao_coletor": VERSAO_COLETOR,
        "versao_score": {"m8": "SCORE-M8-V1.0"},
        "status_final": "parcial",  # atualizado para 'concluída' só no fim do run (contrato §21)
    }).execute()
    return r.data[0]["id"]


def finalizar_execucao(sb: Client, execucao_id: str, totais: dict, status_final: str = "concluída"):
    sb.table("execucoes").update({
        "fim": datetime.now(timezone.utc).isoformat(),
        "totais": totais,
        "status_final": status_final,
    }).eq("id", execucao_id).execute()


def registrar_log_busca(sb: Client, execucao_id: str, source_id: str, url: str,
                         codigo_http: Optional[int], hash_conteudo: Optional[str],
                         erro: Optional[str] = None):
    sb.table("log_busca").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        "url_requisitada": url,
        "codigo_http": codigo_http,
        "hash_conteudo": hash_conteudo,
        "erro": erro,
    }).execute()


def registrar_log_coleta(sb: Client, execucao_id: str, source_id: str, contagens: dict):
    sb.table("log_coleta").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        **contagens,  # brutos, filtrados, analisados, identicos, atualizados, novos, duplicatas_bloqueadas, descartados, erros
    }).execute()


def buscar_evento_por_id_evento(sb: Client, id_evento: str) -> Optional[dict]:
    r = sb.table("events").select("*").eq("id_evento", id_evento).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_evento(sb: Client, id_evento: str, campos: dict, execucao_id: str) -> tuple:
    """Retorna (event_id, criado: bool). Se o evento já existe, registra
    diffs em auditoria_correcoes para cada campo que mudou (carta §7:
    'mesmo protocolo com novo hash: atualizar o evento... registrar os
    campos alterados')."""
    existente = buscar_evento_por_id_evento(sb, id_evento)
    if existente is None:
        payload = {
            "id_evento": id_evento, "modulo": MODULO,
            "execucao_criacao_id": execucao_id, **campos,
        }
        r = sb.table("events").insert(payload).execute()
        return r.data[0]["id"], True

    diffs = {}
    for campo, valor_novo in campos.items():
        valor_anterior = existente.get(campo)
        if valor_anterior != valor_novo and valor_novo is not None:
            diffs[campo] = (valor_anterior, valor_novo)

    if diffs:
        sb.table("events").update(campos).eq("id", existente["id"]).execute()
        for campo, (anterior, novo) in diffs.items():
            sb.table("auditoria_correcoes").insert({
                "event_id": existente["id"],
                "campo_alterado": campo,
                "valor_anterior": str(anterior) if anterior is not None else None,
                "valor_novo": str(novo) if novo is not None else None,
                "metodo_extracao": "coletor_automatico",
                "versao_regra": "SCORE-M8-V1.0",
            }).execute()
    return existente["id"], False


def upsert_m8_detalhe(sb: Client, event_id: str, protocolo: str, ano: int, detalhe: dict):
    payload = {"event_id": event_id, "protocolo_semad": protocolo, "ano": ano, **detalhe}
    sb.table("m8_acidentes_detalhe").upsert(payload, on_conflict="protocolo_semad,ano").execute()


def gravar_score(sb: Client, event_id: str, score_bruto: float, prioridade: str,
                  componentes: dict, versao_score: str = "SCORE-M8-V1.0"):
    """Nunca sobrescreve — marca a versão anterior vigente=false e insere
    uma nova linha vigente=true (mesmo padrão do resto do Radar)."""
    sb.table("event_scores").update({"vigente": False}).eq("event_id", event_id).eq("vigente", True).execute()
    sb.table("event_scores").insert({
        "event_id": event_id,
        "score_bruto": score_bruto,
        "versao_score": versao_score,
        "prioridade": prioridade,
        "componentes": componentes,
        "vigente": True,
    }).execute()


def gravar_evidencia(sb: Client, event_id: str, documento_id: Optional[str], trecho_literal: str,
                      pagina_secao: Optional[str] = None, metodo_extracao: str = "nativo",
                      confianca: Optional[float] = None):
    sb.table("evidencias").insert({
        "event_id": event_id,
        "documento_id": documento_id,
        "trecho_literal": trecho_literal,
        "pagina_secao": pagina_secao,
        "metodo_extracao": metodo_extracao,
        "confianca": confianca,
    }).execute()


# ----------------------------------------------------------------------------
# Extensão — Checklist Completo de Enriquecimento e Pré-Release (documento
# enviado pela Rapha em 23/09/2026). Cobre o que faltava pro M8 fechar o
# ciclo de rastreabilidade completo: documento com proveniência própria,
# evidência por campo (não só um bloco de texto), checklist editorial de
# 12 perguntas, eventos relacionados (antecedentes) e job de enriquecimento.
# ----------------------------------------------------------------------------

def gravar_documento(sb: Client, event_id: str, url: str, hash_documento: str,
                      tipo: str = "comunicado_acidente", orgao: str = "SEMAD",
                      status: str = "processado", paginas_ocr: Optional[int] = None,
                      versao: int = 1) -> str:
    """Checklist, seção 'Inventário de documentos e anexos': título, órgão,
    tipo documental, URL, hash e versão de cada documento aberto. O M8 tem
    um documento por comunicado (o PDF/imagem do próprio comunicado).
    `documentos` tem UNIQUE(url, hash_documento) — upsert por essa chave
    pra reprocessar o mesmo documento (mesmo conteúdo) sem duplicar."""
    r = sb.table("documentos").upsert({
        "event_id": event_id,
        "url": url,
        "hash_documento": hash_documento,
        "tipo": tipo,
        "orgao": orgao,
        "status": status,
        "paginas_ocr": paginas_ocr,
        "versao": versao,
    }, on_conflict="url,hash_documento").execute()
    return r.data[0]["id"]


def gravar_evidencias_campo(sb: Client, event_id: str, documento_id: Optional[str],
                             evidencias: list, metodo_extracao: str = "nativo"):
    """Grava uma linha em `evidencias` por sinal disparado (signals.py
    extrair_evidencias_vinculo/extrair_evidencias_gravidade). `evidencias`
    é a lista de {campo, trecho_literal, palavra_gatilho} que essas funções
    devolvem.

    NOTA — interpretação minha: a tabela `evidencias` não tem uma coluna
    própria para "qual campo esta evidência sustenta" (o checklist pede
    isso na seção 'Evidências e proveniência': 'campo sustentado'). Uso
    `resumo_extraido` pra guardar isso ("campo: <nome>"), que é o campo
    mais próximo disponível — se a Rapha preferir uma coluna dedicada
    (ex.: `campo_sustentado text`), é uma migration pequena depois."""
    for ev in evidencias:
        sb.table("evidencias").insert({
            "event_id": event_id,
            "documento_id": documento_id,
            "trecho_literal": ev["trecho_literal"][:2000],
            "resumo_extraido": f"campo: {ev['campo']}",
            "tipo_afirmacao": "fato",  # é o texto literal do comunicado oficial, não inferência do coletor
            "metodo_extracao": metodo_extracao,
        }).execute()


def gravar_checklist_editorial(sb: Client, event_id: str, respostas: dict,
                                prioridade: Optional[str] = None):
    """`respostas` é {numero_pergunta (1-12): resposta}, o retorno de
    checklist_editorial.derivar_checklist_m8(). Uma linha por pergunta —
    upsert por (event_id, pergunta_numero) pra reprocessamento não duplicar
    (checklist, seção 'Reprocessamento': recalcular só o que mudou, sem
    duplicar histórico)."""
    for numero, resposta in respostas.items():
        sb.table("checklist_editorial").upsert({
            "event_id": event_id,
            "pergunta_numero": numero,
            "resposta": resposta,
            "prioridade": prioridade,
        }, on_conflict="event_id,pergunta_numero").execute()


def buscar_antecedentes_m8(sb: Client, event_id_atual: str, empresa_citada: Optional[str],
                            mina_unidade: Optional[str]) -> list:
    """Checklist, seção 'Cruzamentos vínculos e antecedentes': procura
    fatos anteriores por empresa/estrutura. NÃO afirma causalidade — só
    relaciona pra revisão humana decidir ('Não usar mesmo CNPJ... como
    prova de causalidade', checklist §Cruzamentos). Critério aqui é
    puramente textual (nome da empresa/mina igual em outro comunicado já
    gravado), o mais fraco dos critérios que o checklist lista — cruzar
    por CNPJ exigiria ter o CNPJ, que a carta M8 não pede como campo
    obrigatório."""
    antecedentes = []
    if empresa_citada:
        r = sb.table("m8_acidentes_detalhe").select("event_id").eq(
            "empresa_citada", empresa_citada
        ).neq("event_id", event_id_atual).execute()
        antecedentes += [row["event_id"] for row in r.data]
    if mina_unidade:
        r = sb.table("m8_acidentes_detalhe").select("event_id").eq(
            "mina_unidade", mina_unidade
        ).neq("event_id", event_id_atual).execute()
        antecedentes += [row["event_id"] for row in r.data]
    return sorted(set(antecedentes))


def gravar_eventos_relacionados(sb: Client, event_id_atual: str, antecedentes: list,
                                 criterio_vinculo: str = "mesma_empresa_ou_mina"):
    """`eventos_relacionados` tem UNIQUE(event_origem_id, event_relacionado_id,
    criterio_vinculo) — upsert por essa chave pra reprocessar sem duplicar."""
    for event_id_relacionado in antecedentes:
        sb.table("eventos_relacionados").upsert({
            "event_origem_id": event_id_atual,
            "event_relacionado_id": event_id_relacionado,
            "criterio_vinculo": criterio_vinculo,
            "status_relacao": "observado_automatico_requer_revisao",
            "confianca": None,  # nunca reivindica causalidade sozinho — checklist §Cruzamentos
        }, on_conflict="event_origem_id,event_relacionado_id,criterio_vinculo").execute()


def gravar_job_enriquecimento(sb: Client, event_id: str, hash_entrada: str, status: str,
                               tempo_gasto_segundos: Optional[float] = None,
                               erro: Optional[str] = None,
                               versao_enriquecedor: str = "enriquecedor-m8-v0.1"):
    """Um registro por (event_id, hash_entrada, versao_enriquecedor) —
    é a UNIQUE real da tabela. Reprocessar o MESMO texto com a MESMA
    versão do enriquecedor incrementa `tentativas` na linha existente em
    vez de duplicar (checklist, seção 'Logs custo e reprodução': histórico
    de tentativas por job, não uma tentativa nova quando nada mudou)."""
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

"""
Módulo 6 (Outorgas de Recursos Hídricos do IGAM) — escrita no Supabase.

Mesmo padrão já usado em coletores/m8_acidentes/db_writer.py (events.id_evento
é a chave de negócio estável, upsert por ela; event_scores nunca é
sobrescrito — vigente=false na linha antiga + insert nova vigente=true;
diffs em campo já existente viram auditoria_correcoes). Repito aqui as
mesmas funções em vez de importar de m8_acidentes porque MODULO e as
versões de regra são diferentes — a duplicação é pequena e deixa cada
coletor sem depender silenciosamente do outro.

NÃO existe hoje `m6_outorgas_detalhe` (tabela específica, 1:1 com events,
no padrão de `m8_acidentes_detalhe`/`m9a_movimentacao_estado`). A auditoria
de 28/09/2026 já registrou isso como decisão adiada: "avaliar durante a
implementação do coletor M6, só se os campos específicos não couberem em
events+documentos+evidencias". Esta primeira versão não cria a tabela —
os campos do contrato de dados do M6 (processo, portaria, titular,
finalidade, vazão, modo de uso etc.) vão para `evidencias.campo_sustentado`
por campo, igual ao padrão já usado no reprocessamento do M9A
(830.649/2020). Se isso se mostrar insuficiente quando o coletor rodar
contra documento real, criar a tabela é um passo separado, não especulativo.

Variáveis de ambiente esperadas (nunca hardcoded, nunca passam por mim):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

MODULO = "M6_outorgas"
VERSAO_COLETOR = "m6-outorgas-v0.1"
VERSAO_SCORE = "SCORE-M6-V1"

OBSERVACAO_PADRAO_NAO_LOCALIZADO = "Procurado no documento/fonte disponível e não localizado nesta rodada."

def _escopo():
    """Importa comum/escopo.py (o db_writer também roda fora do main, nos testes locais)."""
    import sys
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    import escopo
    return escopo


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def buscar_fonte_id(sb: Client, url_base: str, empresa_id: Optional[str] = None, carteira_id: Optional[str] = None) -> dict:
    """Retorna {'id', 'empresa_id', 'carteira_id'}: fonte (M6F01, carta §44.2) + escopo da coleta.
    Mesma regra de M8/M9A (comum/escopo.py): empresa explícita se a fonte existe em várias, carteira
    da mesma empresa, falha clara em vez de adivinhar."""
    return _escopo().resolver_escopo(
        sb, url_base, empresa_id=empresa_id or os.environ.get("RADAR_EMPRESA_ID"),
        carteira_id=carteira_id or os.environ.get("RADAR_CARTEIRA_ID"), rotulo="M6")


def criar_execucao(sb: Client, id_execucao: str, ambiente: str = "piloto",
                    empresa_id: Optional[str] = None, carteira_id: Optional[str] = None) -> str:
    # Isolamento por empresa: toda execução nasce com empresa_id E carteira_id (o banco também exige).
    if not empresa_id or not carteira_id:
        raise RuntimeError("Execução sem empresa_id/carteira_id: o escopo da coleta precisa estar definido (veja comum/escopo.py).")
    r = sb.table("execucoes").insert({
        "id_execucao": id_execucao,
        "inicio": datetime.now(timezone.utc).isoformat(),
        "ambiente": ambiente,
        "versao_coletor": VERSAO_COLETOR,
        "versao_score": {"m6": VERSAO_SCORE},
        "status_final": "parcial",
        "empresa_id": empresa_id,
        "carteira_id": carteira_id,
    }).execute()
    return r.data[0]["id"]


def finalizar_execucao(sb: Client, execucao_id: str, totais: dict, status_final: str = "concluída"):
    sb.table("execucoes").update({
        "fim": datetime.now(timezone.utc).isoformat(),
        "totais": totais,
        "status_final": status_final,
    }).eq("id", execucao_id).execute()


def registrar_log_coleta(sb: Client, execucao_id: str, source_id: str, contagens: dict,
                          empresa_id: Optional[str] = None):
    """`contagens`: brutos, filtrados, analisados, identicos, atualizados,
    novos, duplicatas_bloqueadas, descartados, erros — mesma reconciliação
    (constraint de banco) usada por M8/M9A. 'descartados' aqui inclui os
    atos eliminados pelo filtro barato de vínculo mineral (signals.
    tem_vinculo_mineral), carta homologação M6 A08."""
    sb.table("log_coleta").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        "empresa_id": empresa_id,
        **contagens,
    }).execute()


def buscar_evento_por_id_evento(sb: Client, id_evento: str, empresa_id: str) -> Optional[dict]:
    """A chave lógica do evento é (empresa_id, id_evento): a mesma ocorrência pode existir em
    empresas diferentes, cada uma com seu estado editorial. Nunca buscar só por id_evento."""
    if not empresa_id:
        raise RuntimeError("buscar_evento_por_id_evento exige empresa_id (isolamento por empresa).")
    r = sb.table("events").select("*").eq("empresa_id", empresa_id).eq("id_evento", id_evento).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_evento(sb: Client, id_evento: str, campos: dict, execucao_id: str,
                   empresa_id: Optional[str] = None) -> tuple:
    """Retorna (event_id, criado: bool). Chave de negócio: carta §44.6,
    'a chave de correspondência deve combinar, por ordem de força,
    processo, portaria, CNPJ, empreendimento, município [...]' — quem
    monta `id_evento` (main.py) decide qual combinação usar; esta função
    só faz o upsert e registra diffs, igual ao M8."""
    existente = buscar_evento_por_id_evento(sb, id_evento, empresa_id)
    if existente is None:
        payload = {
            "id_evento": id_evento, "modulo": MODULO,
            "execucao_criacao_id": execucao_id, "empresa_id": empresa_id, **campos,
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
                "versao_regra": VERSAO_SCORE,
            }).execute()
    return existente["id"], False


def gravar_score(sb: Client, event_id: str, score_bruto: float, prioridade: str,
                  componentes: dict, versao_score: str = VERSAO_SCORE,
                  empresa_id: Optional[str] = None, score_normalizado: Optional[float] = None,
                  estagio: str = "preliminar"):
    """Nunca sobrescreve — vigente=false na antiga + insert nova vigente=
    true. `estagio` default 'preliminar' (não 'final'): a carta de
    Revisão/Calibração de Scores M8/M9A de 28/09/2026 deixou explícito que
    NENHUMA fórmula de score automático está homologada para produção
    ainda, e por decisão de 30/09/2026 isso foi estendido a todos os
    scores calculados do Radar até cada módulo ser homologado — M6 nasce
    já seguindo essa regra, em vez de precisar de uma correção depois."""
    sb.table("event_scores").update({"vigente": False}).eq("event_id", event_id).eq("vigente", True).execute()
    sb.table("event_scores").insert({
        "event_id": event_id,
        "score_bruto": score_bruto,
        "versao_score": versao_score,
        "score_normalizado": score_normalizado,
        "prioridade": prioridade,
        "componentes": componentes,
        "vigente": True,
        "empresa_id": empresa_id,
        "estagio": estagio,
    }).execute()


def gravar_evidencia(sb: Client, event_id: str, documento_id: Optional[str], trecho_literal: str,
                      campo_sustentado: Optional[str] = None, pagina_secao: Optional[str] = None,
                      metodo_extracao: str = "nativo", confianca: Optional[float] = None,
                      empresa_id: Optional[str] = None) -> str:
    r = sb.table("evidencias").insert({
        "event_id": event_id,
        "documento_id": documento_id,
        "trecho_literal": trecho_literal,
        "campo_sustentado": campo_sustentado,
        "pagina_secao": pagina_secao,
        "metodo_extracao": metodo_extracao,
        "confianca": confianca,
        "empresa_id": empresa_id,
    }).execute()
    return r.data[0]["id"]


def gravar_checklist_editorial(sb: Client, event_id: str, respostas: dict,
                                prioridade: Optional[str] = None, empresa_id: Optional[str] = None,
                                evidencia_padrao_id: Optional[str] = None,
                                observacoes_por_pergunta: Optional[dict] = None) -> dict:
    """Mesma trava que o M8 já corrigiu na auditoria de 28/09:
    'confirmado' exige evidencia_id (chk_confirmado_exige_evidencia),
    'nao_localizado' exige observacao (chk_nao_localizado_exige_observacao).
    Sem evidência real, a resposta é rebaixada para 'requer_apuracao_humana'
    — nunca grava 'confirmado' vazio só para não quebrar a constraint."""
    observacoes_por_pergunta = observacoes_por_pergunta or {}
    respostas_finais = {}
    for numero, resposta in respostas.items():
        evidencia_id = None
        observacao = None
        if resposta == "confirmado":
            evidencia_id = evidencia_padrao_id
            if evidencia_id is None:
                resposta = "requer_apuracao_humana"
        elif resposta == "nao_localizado":
            observacao = observacoes_por_pergunta.get(numero) or OBSERVACAO_PADRAO_NAO_LOCALIZADO

        respostas_finais[numero] = resposta
        sb.table("checklist_editorial").upsert({
            "event_id": event_id,
            "pergunta_numero": numero,
            "resposta": resposta,
            "prioridade": prioridade,
            "empresa_id": empresa_id,
            "evidencia_id": evidencia_id,
            "observacao": observacao,
        }, on_conflict="event_id,pergunta_numero").execute()
    return respostas_finais


def gravar_job_enriquecimento(sb: Client, event_id: str, hash_entrada: str, status: str,
                               tempo_gasto_segundos: Optional[float] = None,
                               erro: Optional[str] = None,
                               versao_enriquecedor: str = "enriquecedor-m6-v0.1",
                               empresa_id: Optional[str] = None):
    """Um registro por (event_id, hash_entrada, versao_enriquecedor) — a
    UNIQUE real da tabela garante idempotência no nível do banco: reexecutar
    os mesmos 3 documentos incrementa `tentativas`, nunca duplica (carta de
    homologação, execução obrigatória nº9/10: segunda execução = seis
    idênticos, zero novos, zero atualizados, zero duplicados)."""
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
        return existente.data[0]["id"], False
    else:
        r = sb.table("job_enriquecimento").insert({
            "event_id": event_id, "hash_entrada": hash_entrada,
            "versao_enriquecedor": versao_enriquecedor, "tentativas": 1,
            "empresa_id": empresa_id, **payload,
        }).execute()
        return r.data[0]["id"], True

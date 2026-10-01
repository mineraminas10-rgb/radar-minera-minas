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
import classificacao_scm as clsf

MODULO = "M9A_anm_movimentacoes"
VERSAO_COLETOR = "m9a-movimentacoes-v0.1"


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def buscar_fonte(sb: Client) -> dict:
    """Retorna {'id':..., 'empresa_id':...}. F14 na base real (confirmado
    ao vivo em 23/09/2026, ver LEIA-ME) — a fonte primária deste coletor é
    o SCM Microdados; SIGMINE (F15) e DOU entram só no enriquecimento §8,
    ainda não implementado.

    `empresa_id` vem de sources.empresa_id (isolamento por empresa,
    DRAFT_20260924) — mesmo padrão de coletores/m8_acidentes/db_writer.py.
    Achado da auditoria de 28/09/2026, a conferir com a Rapha: na réplica
    local esta fonte não existia em NENHUMA migration rastreada (só era
    citada em comentário de código como já existindo em produção) — se o
    mesmo valer para a produção real, vale conferir se sources.empresa_id
    da fonte SCM Microdados está preenchido lá também."""
    r = sb.table("sources").select("id, empresa_id").eq(
        "url_base", "https://dadosabertos.anm.gov.br/SCM/microdados/"
    ).limit(1).execute()
    if not r.data:
        raise RuntimeError(
            "Fonte do M9A (SCM Microdados) não encontrada em sources — ela já existe na base "
            "real da Rapha (F14), então esse erro só deveria aparecer numa réplica de teste sem seed."
        )
    return r.data[0]


def buscar_fonte_id(sb: Client) -> str:
    """Compatibilidade com chamadores existentes que só precisam do id."""
    return buscar_fonte(sb)["id"]


def buscar_regra_evento(sb: Client, fonte_id: str, tipo_evento: str,
                         subtipo_evento: Optional[str] = None) -> Optional[dict]:
    """Mesma função do M8 (ver docstring lá) — só leitura, não decide
    score. Retorna None quando não existe regra cadastrada ainda (não é
    bloqueante).

    `tipo_evento` aqui não tem um valor único natural como no M8 (um caso
    M9A pode agrupar atos de tipos diferentes — ver consolidacao.py regra
    4). Uso "movimentacao_scm_anm" como tipo_evento genérico do módulo até
    existir uma regras_evento real cadastrada que exija granularidade por
    tipo de ato — interpretação minha, a confirmar com a Rapha."""
    q = sb.table("regras_evento").select("id, versao").eq("fonte_id", fonte_id).eq(
        "tipo_evento", tipo_evento
    ).eq("ativo", True)
    q = q.is_("subtipo_evento", "null") if subtipo_evento is None else q.eq("subtipo_evento", subtipo_evento)
    r = q.order("versao", desc=True).limit(1).execute()
    return r.data[0] if r.data else None


def criar_execucao(sb: Client, id_execucao: str, ambiente: str = "piloto",
                    empresa_id: Optional[str] = None) -> str:
    r = sb.table("execucoes").insert({
        "id_execucao": id_execucao,
        "inicio": datetime.now(timezone.utc).isoformat(),
        "ambiente": ambiente,
        "versao_coletor": VERSAO_COLETOR,
        "versao_score": {"m9a": "SCORE-M9A-V0.2"},
        "status_final": "parcial",
        "empresa_id": empresa_id,
    }).execute()
    return r.data[0]["id"]


def finalizar_execucao(sb: Client, execucao_id: str, totais: dict, status_final: str = "concluída"):
    """`totais` pode carregar (quando existirem de verdade) as mesmas
    chaves de custo/processamento do M8 — execucoes.totais já é jsonb
    livre, nenhuma migration nova precisa. chamadas_ia/tokens_ia ficam 0
    hoje: este coletor classifica por sinais estruturados do SCM, sem
    nenhuma chamada de IA."""
    sb.table("execucoes").update({
        "fim": datetime.now(timezone.utc).isoformat(),
        "totais": totais,
        "status_final": status_final,
    }).eq("id", execucao_id).execute()


def buscar_evento_por_id_evento(sb: Client, id_evento: str) -> Optional[dict]:
    r = sb.table("events").select("*").eq("id_evento", id_evento).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_caso_editorial(sb: Client, id_evento: str, campos_evento: dict, execucao_id: str,
                           empresa_id: Optional[str] = None) -> tuple:
    existente = buscar_evento_por_id_evento(sb, id_evento)
    if existente is None:
        payload = {"id_evento": id_evento, "modulo": MODULO,
                   "execucao_criacao_id": execucao_id, "empresa_id": empresa_id, **campos_evento}
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


# ----------------------------------------------------------------------------
# Timeline processual — vocabulário fechado dos 10 tipos, o mesmo usado em
# coletores/m8_acidentes/db_writer.py (não é um enum novo no banco, é
# validado em código para evitar o mesmo tipo de drift já sofrido com
# modulo_semad ganhando ALTER TYPE... ADD VALUE direto em produção).
# ----------------------------------------------------------------------------
TIPOS_MARCO_TIMELINE = (
    "requerimento", "documento", "assinatura", "decisao", "publicacao",
    "ciencia", "recurso", "julgamento", "inicio_efeitos", "vencimento",
)

# Mapeamento interpretativo do TIPO OFICIAL de evento (DSEvento, dicionário
# Evento.txt — ver classificacao_scm.py) para o vocabulário fechado acima.
#
# ACHADO/correção de 28/09/2026 (2ª rodada): a primeira versão deste mapa
# comparava contra `ato.descricao` como texto livre bruto do SCM, sem
# declarar qual campo alimentava isso — o mesmo problema geral descrito em
# classificacao_scm.py (a variação "guia utilização" x "guia de
# utilização" fazia o mesmo ato cair no fallback "documento" ou não,
# dependendo de qual texto chegasse aqui). Agora `mapear_tipo_marco()"
# classifica sempre a partir da identidade oficial do evento (via
# classificacao_scm.classificar, mesma função usada em signals.py) e as
# chaves abaixo são comparadas já normalizadas (sem preposição/artigo) —
# por isso não repetem mais "decisao de decaimento"/"decisão de
# decaimento" como duas entradas, normalizar_termo() já trata as duas
# formas como iguais.
#
# Nomenclatura ainda não confirmada contra uma amostra representativa do
# dicionário para TODAS as famílias (decaimento/caducidade/cessão etc. —
# só guia de utilização/portaria/alvará foram checados contra Evento.txt
# real em 28/09/2026, ver ETAPA3_PLANO_ESCRITA_REPROCESSAMENTO) — a
# confirmar com a Rapha; qualquer ato não mapeado aqui cai no fallback
# "documento" (conservador: nunca inventa um marco processual mais forte
# do que o que sabemos).
_MAPEAMENTO_TIPO_MARCO = {
    # decisões administrativas que mudam o direito minerário
    "decaimento": "decisao",
    "caducidade": "decisao",
    "indisponibilidade": "decisao",
    "interdicao": "decisao",
    "renuncia": "decisao",
    "cessao": "decisao",
    "transferencia": "decisao",
    "concessao": "decisao",
    # atos que autorizam/publicam um novo direito ou uma aprovação —
    # exigem tipo.situacao == 'concluido' (ver mapear_tipo_marco), então
    # as chaves aqui não precisam mais repetir "requerimento"/"protocolado"
    "portaria lavra": "publicacao",
    "guia utilizacao": "publicacao",
    "alvara pesquisa": "publicacao",
    "relatorio aprovado": "publicacao",
    "reavaliacao aprovada": "publicacao",
    # comunicações formais que dão ciência à parte (a ANM intima/exige)
    "intimacao": "ciencia",
    "exigencia": "ciencia",
    # expediente/rotina processual — mais próximo de um requerimento/trâmite
    "protocolo": "requerimento",
    "juntada": "requerimento",
    "pagamento tah": "requerimento",
    "retificacao": "requerimento",
    "ral": "requerimento",
}


def mapear_tipo_marco(descricao: Optional[str], id_tipo_evento: Optional[int] = None) -> str:
    """Traduz o TIPO OFICIAL de um ato (identidade do dicionário
    Evento.txt, não texto narrativo livre) para o vocabulário fechado de
    TIPOS_MARCO_TIMELINE. `descricao` aqui deve ser o nome do dicionário
    (DSEvento — o mesmo texto que `ato.descricao` carrega desde a correção
    de 28/09/2026, ver consolidacao.py); passar texto narrativo livre
    reintroduziria o problema que esta correção resolveu.

    Fallback conservador: 'documento' quando o tipo não bate com nenhuma
    entrada conhecida do mapa acima, ou quando bate mas a situação (sufixo
    do dicionário) ainda está 'em_tramite'/'negativo' (um requerimento
    ainda não decidido não deveria virar 'publicacao' na timeline) — nunca
    lança exceção, porque o texto vem direto do SCM e não é controlado por
    este coletor."""
    tipo = clsf.classificar(id_tipo_evento, descricao)
    for chave, marco in _MAPEAMENTO_TIPO_MARCO.items():
        if tipo.contem(chave):
            if marco == "publicacao" and tipo.situacao not in ("concluido", "indefinido"):
                return "documento"
            return marco
    return "documento"


def gravar_ato_na_timeline(sb: Client, event_id: str, tipo_marco: str, data_marco: str,
                            trecho_literal: Optional[str] = None, url_documento: Optional[str] = None,
                            evidencia_id: Optional[str] = None, empresa_id: Optional[str] = None):
    """Carta §5 regra 5: atos individuais ficam na timeline mesmo quando
    consolidados em um único caso editorial.

    `tipo_marco` deve já vir traduzido pelo vocabulário fechado (ver
    mapear_tipo_marco acima) — esta função valida e rejeita qualquer valor
    fora de TIPOS_MARCO_TIMELINE, mesma trava do M8."""
    if tipo_marco not in TIPOS_MARCO_TIMELINE:
        raise ValueError(f"tipo_marco '{tipo_marco}' fora do vocabulário fechado {TIPOS_MARCO_TIMELINE}")
    sb.table("timeline_processual").insert({
        "event_id": event_id,
        "tipo_marco": tipo_marco,
        "data_marco": data_marco,
        "trecho_literal": trecho_literal,
        "url_documento": url_documento,
        "evidencia_id": evidencia_id,
        "confianca": None,  # mesma política do resto deste arquivo — nunca inventar
        "empresa_id": empresa_id,
    }).execute()


def gravar_score(sb: Client, event_id: str, score_bruto: float, prioridade: str, componentes: dict,
                  versao_score: str = "SCORE-M9A-V0.2", empresa_id: Optional[str] = None,
                  score_normalizado: Optional[float] = None,
                  regra_evento_id: Optional[str] = None, regra_evento_versao: Optional[int] = None,
                  gatilhos_aplicados: Optional[dict] = None, redutores_aplicados: Optional[dict] = None,
                  piso_aplicado=None, teto_aplicado=None,
                  confianca_evidencial: Optional[float] = None, estagio: str = "final"):
    """Mesma extensão feita em coletores/m8_acidentes/db_writer.py — ver
    docstring lá para o raciocínio completo de cada campo.
    confianca_evidencial fica None por padrão de propósito (decisão de
    28/09/2026, mesma regra do M8): ainda não existe critério objetivo e
    reproduzível para calculá-la."""
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
        "regra_evento_id": regra_evento_id,
        "regra_evento_versao": regra_evento_versao,
        "gatilhos_aplicados": gatilhos_aplicados,
        "redutores_aplicados": redutores_aplicados,
        "piso_aplicado": piso_aplicado,
        "teto_aplicado": teto_aplicado,
        "confianca_evidencial": confianca_evidencial,
        "estagio": estagio,
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

def gravar_evidencias_caso(sb: Client, event_id: str, evidencias: list,
                            empresa_id: Optional[str] = None) -> list:
    """`evidencias` é uma lista de {campo, trecho_literal} vinda dos
    valores literais do SCM (ex.: titular, substância, tipo de ato) — não
    é texto de documento (ver aviso no topo do arquivo), por isso
    documento_id sempre None e tipo_afirmacao='fato' (são valores oficiais
    da planilha, não inferência do coletor).

    A partir de 28/09/2026 usa `campo_sustentado` (migration
    DRAFT_20260928) em vez do workaround `resumo_extraido=f"campo: ..."`,
    mesma mudança feita no M8. `confianca` continua sempre None, mesma
    política documentada em coletores/m8_acidentes/db_writer.py
    (gravar_evidencias_campo) — nunca atribuir 1.0 só por existir valor
    literal. Retorna a lista de {id, campo} gravados, para o chamador
    poder linkar evidencia_id específica no checklist/timeline."""
    gravadas = []
    for ev in evidencias:
        r = sb.table("evidencias").insert({
            "event_id": event_id,
            "documento_id": None,
            "trecho_literal": str(ev["trecho_literal"])[:2000],
            "campo_sustentado": ev["campo"],
            "tipo_afirmacao": "fato",
            "metodo_extracao": "planilha_scm",
            "confianca": None,
            "empresa_id": empresa_id,
        }).execute()
        gravadas.append({"id": r.data[0]["id"], "campo": ev["campo"]})
    return gravadas


OBSERVACAO_PADRAO_NAO_LOCALIZADO = "Não localizado no texto/dado processado nesta coleta."


def gravar_checklist_editorial(sb: Client, event_id: str, respostas: dict,
                                prioridade: Optional[str] = None, empresa_id: Optional[str] = None,
                                evidencia_padrao_id: Optional[str] = None,
                                evidencias_por_pergunta: Optional[dict] = None,
                                observacoes_por_pergunta: Optional[dict] = None) -> dict:
    """Mesma correção feita em coletores/m8_acidentes/db_writer.py — ver
    docstring lá para o achado completo (chk_confirmado_exige_evidencia /
    chk_nao_localizado_exige_observacao, verificado como violação real de
    constraint, não teórica). Resolução idêntica: 'confirmado' sem
    evidência disponível é rebaixado para 'requer_apuracao_humana';
    'nao_localizado' sempre recebe uma observação (específica ou o texto
    padrão). Retorna {numero: resposta_final_gravada}."""
    evidencias_por_pergunta = evidencias_por_pergunta or {}
    observacoes_por_pergunta = observacoes_por_pergunta or {}
    respostas_finais = {}
    for numero, resposta in respostas.items():
        evidencia_id = None
        observacao = None
        if resposta == "confirmado":
            evidencia_id = evidencias_por_pergunta.get(numero) or evidencia_padrao_id
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
                                 criterio_vinculo: str = "mesma_empresa",
                                 empresa_id: Optional[str] = None):
    """evidencia_id (coluna nova, migration DRAFT_20260928) fica sempre
    None aqui — mesma razão documentada em coletores/m8_acidentes/
    db_writer.py: o critério é correspondência textual (mesma empresa),
    não uma evidência documental específica que comprove o vínculo."""
    for event_id_relacionado in antecedentes:
        sb.table("eventos_relacionados").upsert({
            "event_origem_id": event_id_atual,
            "event_relacionado_id": event_id_relacionado,
            "criterio_vinculo": criterio_vinculo,
            "status_relacao": "observado_automatico_requer_revisao",
            "confianca": None,
            "evidencia_id": None,
            "empresa_id": empresa_id,
        }, on_conflict="event_origem_id,event_relacionado_id,criterio_vinculo").execute()


def gravar_job_enriquecimento(sb: Client, event_id: str, hash_entrada: str, status: str,
                               tempo_gasto_segundos: Optional[float] = None,
                               erro: Optional[str] = None,
                               versao_enriquecedor: str = "enriquecedor-m9a-scm-v0.1",
                               empresa_id: Optional[str] = None):
    """ACHADO/correção de 28/09/2026: o default de `versao_enriquecedor`
    passou de 'enriquecedor-m9a-v0.1' para 'enriquecedor-m9a-scm-v0.1' —
    nome genérico demais sugeria (junto com o texto editorial legado do
    caso 830.649/2020, que fala em "enriquecimento ambiental") um escopo
    que este coletor não cobre. O que este job registra é SÓ a
    estruturação/enriquecimento via SCM Microdados (extração de campos,
    classificação de sinais, checklist, timeline) — SEMAD/FEAM
    (licenciamento ambiental) continua uma etapa separada, não executada
    por nenhum código deste pacote. `job_enriquecimento.status='concluido'`
    aqui não deve ser lido como "enriquecimento ambiental concluído"."""
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
            "versao_enriquecedor": versao_enriquecedor, "tentativas": 1,
            "empresa_id": empresa_id, **payload,
        }).execute()


def registrar_log_coleta(sb: Client, execucao_id: str, source_id: Optional[str], contagens: dict,
                          empresa_id: Optional[str] = None):
    sb.table("log_coleta").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        "empresa_id": empresa_id,
        **contagens,
    }).execute()

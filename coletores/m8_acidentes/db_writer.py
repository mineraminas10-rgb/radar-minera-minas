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


def buscar_fonte(sb: Client) -> dict:
    """Retorna {'id':..., 'empresa_id':...}. `empresa_id` vem de
    sources.empresa_id (isolamento por empresa, DRAFT_20260924) — é a
    fonte de verdade usada para popular empresa_id em events/event_scores/
    demais tabelas abaixo, em vez de deixá-las sempre NULL (achado da
    auditoria de 28/09/2026: nenhuma escrita deste coletor preenchia
    empresa_id até esta rodada, mesmo a coluna já existindo desde 24/09)."""
    r = sb.table("sources").select("id, empresa_id").eq(
        "url_base", "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"
    ).limit(1).execute()
    if not r.data:
        raise RuntimeError(
            "Fonte do M8 não encontrada em sources — rodar antes o SQL de schema "
            "(01_schema_m8_m9a.sql), que cadastra essa fonte."
        )
    return r.data[0]


def buscar_fonte_id(sb: Client) -> str:
    """Compatibilidade com chamadores existentes que só precisam do id."""
    return buscar_fonte(sb)["id"]


def buscar_regra_evento(sb: Client, fonte_id: str, tipo_evento: str,
                         subtipo_evento: Optional[str] = None) -> Optional[dict]:
    """Procura uma regras_evento ativa e vigente (maior versao) para esta
    fonte+tipo_evento (+subtipo, se houver) — só LEITURA, não decide nada
    de score: se existir, event_scores passa a registrar qual regra foi
    usada (regra_evento_id/regra_evento_versao), pura proveniência/
    rastreabilidade. Se não existir nenhuma regra cadastrada ainda para
    este (fonte, tipo_evento), retorna None e o pipeline segue normalmente
    sem vínculo de regra — não é bloqueante."""
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
        "versao_score": {"m8": "SCORE-M8-V1.0"},
        "status_final": "parcial",  # atualizado para 'concluída' só no fim do run (contrato §21)
        "empresa_id": empresa_id,
    }).execute()
    return r.data[0]["id"]


def finalizar_execucao(sb: Client, execucao_id: str, totais: dict, status_final: str = "concluída"):
    """`totais` é o dict de contagens do run (resumo em main.py). A partir
    de 28/09/2026 também aceita (quando existirem de verdade) as chaves de
    custo/processamento que o checklist pede — documentos_processados,
    paginas_ocr_total, chamadas_ia, tokens_ia, custo_estimado_reais — sem
    exigir nenhuma migration nova (execucoes.totais já é jsonb livre).
    Chamadas de IA/tokens ficam 0 hoje porque este coletor ainda não liga
    para nenhuma API de IA (classificação é 100% por sinais/regex,
    signals.py) — não é omissão, é o estado real do pipeline."""
    sb.table("execucoes").update({
        "fim": datetime.now(timezone.utc).isoformat(),
        "totais": totais,
        "status_final": status_final,
    }).eq("id", execucao_id).execute()


def registrar_log_busca(sb: Client, execucao_id: str, source_id: str, url: str,
                         codigo_http: Optional[int], hash_conteudo: Optional[str],
                         erro: Optional[str] = None, empresa_id: Optional[str] = None):
    sb.table("log_busca").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        "url_requisitada": url,
        "codigo_http": codigo_http,
        "hash_conteudo": hash_conteudo,
        "erro": erro,
        "empresa_id": empresa_id,
    }).execute()


def registrar_log_coleta(sb: Client, execucao_id: str, source_id: str, contagens: dict,
                          empresa_id: Optional[str] = None):
    sb.table("log_coleta").insert({
        "execucao_id": execucao_id,
        "source_id": source_id,
        "empresa_id": empresa_id,
        **contagens,  # brutos, filtrados, analisados, identicos, atualizados, novos, duplicatas_bloqueadas, descartados, erros
    }).execute()


def buscar_evento_por_id_evento(sb: Client, id_evento: str) -> Optional[dict]:
    r = sb.table("events").select("*").eq("id_evento", id_evento).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_evento(sb: Client, id_evento: str, campos: dict, execucao_id: str,
                   empresa_id: Optional[str] = None) -> tuple:
    """Retorna (event_id, criado: bool). Se o evento já existe, registra
    diffs em auditoria_correcoes para cada campo que mudou (carta §7:
    'mesmo protocolo com novo hash: atualizar o evento... registrar os
    campos alterados')."""
    existente = buscar_evento_por_id_evento(sb, id_evento)
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
                "versao_regra": "SCORE-M8-V1.0",
            }).execute()
    return existente["id"], False


def upsert_m8_detalhe(sb: Client, event_id: str, protocolo: str, ano: int, detalhe: dict):
    payload = {"event_id": event_id, "protocolo_semad": protocolo, "ano": ano, **detalhe}
    sb.table("m8_acidentes_detalhe").upsert(payload, on_conflict="protocolo_semad,ano").execute()


def gravar_score(sb: Client, event_id: str, score_bruto: float, prioridade: str,
                  componentes: dict, versao_score: str = "SCORE-M8-V1.0",
                  empresa_id: Optional[str] = None, score_normalizado: Optional[float] = None,
                  regra_evento_id: Optional[str] = None, regra_evento_versao: Optional[int] = None,
                  gatilhos_aplicados: Optional[dict] = None, redutores_aplicados: Optional[dict] = None,
                  piso_aplicado=None, teto_aplicado=None,
                  confianca_evidencial: Optional[float] = None, estagio: str = "preliminar"):
    """Nunca sobrescreve — marca a versão anterior vigente=false e insere
    uma nova linha vigente=true (mesmo padrão do resto do Radar).

    A partir de 28/09/2026 grava também os campos de memória de cálculo que
    já existiam em event_scores mas nunca eram preenchidos por este coletor
    (achado da auditoria de 28/09): score_normalizado (para ranking
    transversal — NUNCA compare score_bruto entre módulos, só
    score_normalizado), empresa_id, regra_evento_id/versao (proveniência,
    quando existir uma regras_evento cadastrada — None não bloqueia nada),
    gatilhos_aplicados/redutores_aplicados/piso_aplicado/teto_aplicado
    (vêm de scoring.montar_memoria_calculo_*, não recalculados aqui).

    confianca_evidencial fica None por padrão de propósito: ainda não
    existe uma regra objetiva e reproduzível para calculá-la (decisão de
    28/09/2026) — nunca atribuir um valor arbitrário só para preencher a
    coluna.

    estagio fica 'preliminar' por padrão (correção de 01/10/2026): nenhuma
    fórmula de score do Radar está homologada para produção — decisão de
    30/09/2026, mesma regra já aplicada em coletores/m6_outorgas/db_writer.py.
    Antes desta correção este coletor gravava 'final' por padrão, o que
    teria liberado automaticamente qualquer evento novo assim que o
    coletor encontrasse um real (o workflow já roda 2x/dia). Só passar
    estagio='final' explicitamente depois de uma homologação formal."""
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


def gravar_evidencia(sb: Client, event_id: str, documento_id: Optional[str], trecho_literal: str,
                      pagina_secao: Optional[str] = None, metodo_extracao: str = "nativo",
                      confianca: Optional[float] = None, campo_sustentado: Optional[str] = None,
                      empresa_id: Optional[str] = None):
    sb.table("evidencias").insert({
        "event_id": event_id,
        "documento_id": documento_id,
        "trecho_literal": trecho_literal,
        "pagina_secao": pagina_secao,
        "metodo_extracao": metodo_extracao,
        "confianca": confianca,
        "campo_sustentado": campo_sustentado,
        "empresa_id": empresa_id,
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
                      versao: int = 1, empresa_id: Optional[str] = None) -> str:
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
        "empresa_id": empresa_id,
    }, on_conflict="url,hash_documento").execute()
    return r.data[0]["id"]


def gravar_evidencias_campo(sb: Client, event_id: str, documento_id: Optional[str],
                             evidencias: list, metodo_extracao: str = "nativo",
                             empresa_id: Optional[str] = None):
    """Grava uma linha em `evidencias` por sinal disparado (signals.py
    extrair_evidencias_vinculo/extrair_evidencias_gravidade). `evidencias`
    é a lista de {campo, trecho_literal, palavra_gatilho} que essas funções
    devolvem.

    Até 28/09/2026 isto usava `resumo_extraido` como workaround pra "qual
    campo esta evidência sustenta" (não existia coluna própria). Agora usa
    `campo_sustentado` (migration DRAFT_20260928), e `resumo_extraido`
    volta a ficar livre para um resumo em texto de verdade — aqui fica None
    porque este coletor ainda não gera resumo, só grava o trecho literal.

    `confianca` fica sempre None (não gravado aqui de propósito): a regra
    (decisão de 28/09/2026, resposta à Rapha) é nunca atribuir 1.0
    automaticamente só porque existe trecho literal — confiança evidencial
    precisa de um critério objetivo e reproduzível que ainda não existe
    para M8/M9A. Preencher confianca aqui hoje seria inventar um número,
    não calculá-lo."""
    gravadas = []
    for ev in evidencias:
        r = sb.table("evidencias").insert({
            "event_id": event_id,
            "documento_id": documento_id,
            "trecho_literal": ev["trecho_literal"][:2000],
            "campo_sustentado": ev["campo"],
            "tipo_afirmacao": "fato",  # é o texto literal do comunicado oficial, não inferência do coletor
            "metodo_extracao": metodo_extracao,
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
    """`respostas` é {numero_pergunta (1-12): resposta}, o retorno de
    checklist_editorial.derivar_checklist_m8(). Uma linha por pergunta —
    upsert por (event_id, pergunta_numero) pra reprocessamento não duplicar
    (checklist, seção 'Reprocessamento': recalcular só o que mudou, sem
    duplicar histórico).

    ACHADO da auditoria de 28/09/2026, corrigido aqui: `checklist_editorial`
    já tem 2 constraints que este coletor nunca respeitava —
    chk_confirmado_exige_evidencia (resposta='confirmado' exige
    evidencia_id) e chk_nao_localizado_exige_observacao (resposta=
    'nao_localizado' exige observacao não vazia). Sem este ajuste, TODO
    insert com resposta='confirmado' seria rejeitado pelo banco (testado:
    é rejeição real, não teórica).

    Resolução:
      - 'confirmado': usa evidencias_por_pergunta[numero] quando existir
        (vínculo específico por pergunta — ainda não implementado em
        signals.py, que não nomeia campos alinhados 1:1 às 12 perguntas);
        senão usa evidencia_padrao_id (a evidência geral do evento, ex.: o
        trecho literal do comunicado). Se nem isso existir, a pergunta é
        REBAIXADA para 'requer_apuracao_humana' — nunca grava 'confirmado'
        sem nenhuma evidência real por trás, mesmo que isso signifique não
        respeitar a resposta que derivar_checklist_m8() calculou.
      - 'nao_localizado': usa observacoes_por_pergunta[numero] quando
        existir, senão usa um texto padrão honesto (não inventa detalhe).

    Retorna {numero: resposta_final_gravada} — para o chamador saber se
    alguma resposta foi rebaixada."""
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


# ----------------------------------------------------------------------------
# Timeline processual — achado da auditoria de 28/09/2026: M8 nunca
# gravava nenhuma linha em timeline_processual (só a data única
# m8_acidentes_detalhe.data_hora_ocorrencia/data_hora_comunicacao). O M8 é
# um módulo de comunicados de acidente, não de processo administrativo, e
# por isso não tem naturalmente marcos como "requerimento"/"julgamento" —
# mapeio aqui só os dois marcos que fazem sentido pro que este coletor
# conhece: a ocorrência documentada (tipo_marco='documento') e a
# comunicação à SEMAD (tipo_marco='ciencia', no sentido de "quando o órgão
# tomou ciência"). Interpretação minha — confirmar com a Rapha se prefere
# outro rótulo; o vocabulário fechado dos 10 tipos é o mesmo do M9A (ver
# coletores/m9a_movimentacoes/db_writer.py).
# ----------------------------------------------------------------------------
TIPOS_MARCO_TIMELINE = (
    "requerimento", "documento", "assinatura", "decisao", "publicacao",
    "ciencia", "recurso", "julgamento", "inicio_efeitos", "vencimento",
)


def gravar_marco_timeline(sb: Client, event_id: str, tipo_marco: str, data_marco,
                           trecho_literal: Optional[str] = None, evidencia_id: Optional[str] = None,
                           empresa_id: Optional[str] = None):
    if tipo_marco not in TIPOS_MARCO_TIMELINE:
        raise ValueError(f"tipo_marco '{tipo_marco}' fora do vocabulário fechado {TIPOS_MARCO_TIMELINE}")
    sb.table("timeline_processual").insert({
        "event_id": event_id,
        "tipo_marco": tipo_marco,
        "data_marco": data_marco,
        "trecho_literal": trecho_literal,
        "evidencia_id": evidencia_id,
        "confianca": None,  # mesma política de confianca do resto deste arquivo — nunca inventar
        "empresa_id": empresa_id,
    }).execute()


def gravar_eventos_relacionados(sb: Client, event_id_atual: str, antecedentes: list,
                                 criterio_vinculo: str = "mesma_empresa_ou_mina",
                                 empresa_id: Optional[str] = None):
    """`eventos_relacionados` tem UNIQUE(event_origem_id, event_relacionado_id,
    criterio_vinculo) — upsert por essa chave pra reprocessar sem duplicar.

    evidencia_id (coluna nova, migration DRAFT_20260928) fica sempre None
    aqui: o critério é uma correspondência textual entre eventos (mesma
    empresa/mina citada em dois comunicados), não uma evidência documental
    específica que comprove o vínculo — linkar uma evidencia_id aqui seria
    sugerir uma prova que não existe. confianca também continua None, pelo
    mesmo motivo já documentado (checklist §Cruzamentos: nunca reivindica
    causalidade sozinho)."""
    for event_id_relacionado in antecedentes:
        sb.table("eventos_relacionados").upsert({
            "event_origem_id": event_id_atual,
            "event_relacionado_id": event_id_relacionado,
            "criterio_vinculo": criterio_vinculo,
            "status_relacao": "observado_automatico_requer_revisao",
            "confianca": None,  # nunca reivindica causalidade sozinho — checklist §Cruzamentos
            "evidencia_id": None,  # correspondência textual, não documental — ver docstring
            "empresa_id": empresa_id,
        }, on_conflict="event_origem_id,event_relacionado_id,criterio_vinculo").execute()


def gravar_job_enriquecimento(sb: Client, event_id: str, hash_entrada: str, status: str,
                               tempo_gasto_segundos: Optional[float] = None,
                               erro: Optional[str] = None,
                               versao_enriquecedor: str = "enriquecedor-m8-v0.1",
                               empresa_id: Optional[str] = None):
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
            "versao_enriquecedor": versao_enriquecedor, "tentativas": 1,
            "empresa_id": empresa_id, **payload,
        }).execute()

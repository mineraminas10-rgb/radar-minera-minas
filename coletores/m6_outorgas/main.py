"""
Módulo 6 — orquestrador do coletor (Carta M6 v0.8 §44.3 fluxo técnico;
Carta de Homologação M6-V1.0 §6 "Execuções obrigatórias"). Pensado para
rodar via agendamento (diário/semanal/mensal, carta §44.4), nunca no
ambiente do Claude.

IMPORTANTE — leia antes de rodar contra a fonte real:
1. discovery.py (índice de publicações) e extractor.py (conversão/
   segmentação de DOC/PDF) NÃO foram validados contra os arquivos reais
   do IGAM (sandbox sem acesso de rede — mesmo estado em que M8 está
   hoje). signals.py e scoring.py estão testados e corretos contra o
   texto/gabarito que a própria Carta de Homologação M6-V1.0 fornece
   (ver test_regressao_m6.py) — é isso que prova a arquitetura, não uma
   execução real ainda.
2. Por segurança, todo evento criado por este coletor entra com
   status_editorial que nunca pula direto para 'publicado' — mineral
   com score calculado entra 'em_apuracao'; fora de escopo entra
   'descartado'; verbo indeterminado entra 'em_apuracao' com checklist
   todo 'requer_apuracao_humana' (nunca um default silencioso).
3. event_scores.estagio nasce 'preliminar' (não 'final') — nenhuma
   fórmula do Radar está homologada para produção hoje (decisão de
   30/09/2026, ver db_writer.gravar_score).
"""
from dataclasses import dataclass, field
from typing import Optional

import checklist_editorial
import db_writer
import signals
import scoring


@dataclass
class AtoParaProcessar:
    """Um ato já segmentado (extractor.segmentar_em_atos) e com os
    metadados que o extrator/humano identificou nele. `componentes_score`
    só é obrigatório se o ato tiver vínculo mineral confirmado — é a
    atribuição de pontos por componente (0..máximo), com justificativa,
    seguindo a régua da carta §43.3 (ver aviso em scoring.py sobre por
    que isso não é um cálculo 100% automático)."""
    processo_ou_portaria: str
    titular: str
    trecho_decisorio: str  # o trecho exato de onde se extrai o verbo — NUNCA o cabeçalho/título do arquivo
    municipio: Optional[str] = None
    data_decisao: Optional[str] = None
    finalidade_uso: Optional[str] = None
    atividade_associada: Optional[str] = None
    vazao_volume_documentado: bool = False
    url_documento: Optional[str] = None
    documento_id: Optional[str] = None
    componentes_score: Optional[dict] = None  # {nome: scoring.ComponenteScore}
    travas_score: Optional[scoring.TravasM6] = None
    tem_cronologia_anterior: bool = False
    recurso_ou_reconsideracao_pendente: Optional[bool] = None


def construir_id_evento(processo_ou_portaria: str) -> str:
    """Chave de negócio (carta §44.6: 'processo, portaria, CNPJ,
    empreendimento [...] por ordem de força') — nesta primeira versão,
    sempre o identificador de processo/portaria do próprio ato, nunca
    titular+data+município (mesma trava que o M8 aplica para o caso
    Vale, ver coletores/m8_acidentes/main.py::construir_id_evento)."""
    chave = processo_ou_portaria.strip().lower().replace("/", "-").replace(" ", "-").replace(".", "")
    return f"igam-m6-{chave}"


def processar_ato(sb, execucao_id: str, ato: AtoParaProcessar, empresa_id: Optional[str] = None) -> dict:
    """Processa um ato já segmentado. Retorna um resumo da ação tomada
    (para a reconciliação do log_coleta em run())."""
    id_evento = construir_id_evento(ato.processo_ou_portaria)

    tipo_evento = signals.classificar_ato(ato.trecho_decisorio)

    sinais_vinculo = signals.SinaisVinculoMineral(
        titular=ato.titular, finalidade_uso=ato.finalidade_uso or "",
        atividade_associada=ato.atividade_associada or "", texto_livre=ato.trecho_decisorio,
    )
    status_vinculo, motivo_vinculo = signals.tem_vinculo_mineral(sinais_vinculo)

    # Carta de Homologação M6-V1.0 §5 (caso Codemig): "indeterminado" não é
    # o mesmo que "confirmado não-mineral" — o primeiro fica em apuração
    # (status_editorial='em_apuracao', sem score), o segundo é descartado
    # de verdade (critério M6 A08). Nenhum dos dois é 'descartado' só por
    # tipo_evento=='indeterminado' (verbo não identificado) virar também
    # 'em_apuracao', nunca promovido a 'descartado' por omissão.
    if status_vinculo == signals.VINCULO_NAO_MINERAL_CONFIRMADO:
        status_editorial = "descartado"
    else:
        status_editorial = "em_apuracao"

    campos_evento = {
        "titulo_fato": f"{ato.titular} — {tipo_evento}",
        "empresa": ato.titular,
        "municipio": ato.municipio,
        "processo": ato.processo_ou_portaria,
        "tipo_evento": tipo_evento,
        "data_evento": ato.data_decisao,
        "status_editorial": status_editorial,
        "url_oficial": ato.url_documento,
    }
    event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id, empresa_id=empresa_id)

    # Evidência do verbo decisório literal — sempre gravada, mineral ou não
    # (é a prova de PORQUE a classificação foi essa, carta §23.1).
    db_writer.gravar_evidencia(
        sb, event_id, ato.documento_id, ato.trecho_decisorio,
        campo_sustentado="verbo_decisorio_literal", empresa_id=empresa_id,
    )

    if status_vinculo == signals.VINCULO_NAO_MINERAL_CONFIRMADO:
        respostas = checklist_editorial.derivar_checklist_m6(fora_de_escopo=True, tipo_evento_normalizado=tipo_evento)
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id)
        # Nenhum score é calculado nem gravado para um ato confirmado como
        # não-mineral — é eliminado ANTES da chamada cara de IA (M6 A08),
        # não "zerado depois". Nada é inserido em event_scores aqui.
        return {"processo_ou_portaria": ato.processo_ou_portaria, "acao": "descartado",
                "motivo": motivo_vinculo, "criado": criado, "event_id": event_id}

    if status_vinculo == signals.VINCULO_INDETERMINADO:
        respostas = checklist_editorial.derivar_checklist_m6(fora_de_escopo=False, tipo_evento_normalizado=tipo_evento)
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id)
        return {"processo_ou_portaria": ato.processo_ou_portaria, "acao": "requer_apuracao_humana",
                "motivo": motivo_vinculo, "criado": criado, "event_id": event_id}

    if tipo_evento == "indeterminado":
        # Vínculo mineral confirmado, mas o verbo decisório não foi
        # identificado — carta §23: "elementos posteriores nunca podem
        # prevalecer sobre o verbo decisório expresso". Fica em apuração,
        # nunca um default de score.
        respostas = checklist_editorial.derivar_checklist_m6(fora_de_escopo=False, tipo_evento_normalizado=tipo_evento)
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id)
        return {"processo_ou_portaria": ato.processo_ou_portaria, "acao": "requer_apuracao_humana",
                "motivo": "verbo decisório não identificado", "criado": criado, "event_id": event_id}

    if ato.componentes_score is None:
        raise ValueError(
            f"ato {ato.processo_ou_portaria}: vínculo mineral confirmado mas componentes_score "
            "não foi atribuído — scoring.py exige julgamento editorial explícito por componente, "
            "não calcula score sem ele (ver docstring de scoring.py)."
        )

    score_total, faixa, memoria = scoring.calcular_score_m6(
        ato.componentes_score, travas=ato.travas_score, fora_de_escopo=False,
    )
    prioridade = faixa if faixa in ("A", "B", "C", "D") else None

    evidencia_padrao_id = db_writer.gravar_evidencia(
        sb, event_id, ato.documento_id, ato.processo_ou_portaria,
        campo_sustentado="processo", empresa_id=empresa_id,
    )

    respostas = checklist_editorial.derivar_checklist_m6(
        fora_de_escopo=False, tipo_evento_normalizado=tipo_evento,
        titular=ato.titular, municipio=ato.municipio, data_decisao=ato.data_decisao,
        processo_ou_portaria=ato.processo_ou_portaria,
        vazao_volume_documentado=ato.vazao_volume_documentado,
        finalidade_uso=ato.finalidade_uso, score_calculado=True,
        tem_cronologia_anterior=ato.tem_cronologia_anterior,
        recurso_ou_reconsideracao_pendente=ato.recurso_ou_reconsideracao_pendente,
    )
    respostas_finais = db_writer.gravar_checklist_editorial(
        sb, event_id, respostas, prioridade=prioridade, empresa_id=empresa_id,
        evidencia_padrao_id=evidencia_padrao_id,
    )
    grau_completude = checklist_editorial.calcular_grau_completude(respostas_finais)
    db_writer.upsert_evento(sb, id_evento, {"grau_completude": grau_completude}, execucao_id, empresa_id=empresa_id)

    db_writer.gravar_score(sb, event_id, score_bruto=score_total, prioridade=prioridade,
                            componentes=memoria, score_normalizado=score_total, empresa_id=empresa_id)

    import hashlib
    hash_entrada = hashlib.sha256(f"{ato.processo_ou_portaria}|{tipo_evento}".encode()).hexdigest()
    job_id, job_criado = db_writer.gravar_job_enriquecimento(
        sb, event_id, hash_entrada, status="concluido", empresa_id=empresa_id,
    )

    return {"processo_ou_portaria": ato.processo_ou_portaria, "acao": "processado" if criado else "atualizado",
            "tipo_evento": tipo_evento, "faixa": faixa, "score": score_total, "criado": criado,
            "job_novo": job_criado, "event_id": event_id}


def run(sb, atos: list, execucao_id: str, source_id: str, empresa_id: Optional[str] = None) -> dict:
    """Processa uma lista de AtoParaProcessar (já descobertos e
    segmentados por fora desta função — discovery.py/extractor.py, ou,
    na homologação, o gabarito oficial da carta) e reconcilia os totais
    para log_coleta (carta de homologação, execução obrigatória nº12)."""
    resumo = {"brutos": len(atos), "filtrados": 0, "analisados": 0, "novos": 0,
              "atualizados": 0, "identicos": 0, "duplicatas_bloqueadas": 0,
              "descartados": 0, "erros": 0}
    resultados = []
    for ato in atos:
        r = processar_ato(sb, execucao_id, ato, empresa_id=empresa_id)
        resultados.append(r)
        if r["acao"] == "descartado":
            resumo["descartados"] += 1
        elif r["acao"] == "processado":
            resumo["novos"] += 1
            resumo["filtrados"] += 1
            resumo["analisados"] += 1
        elif r["acao"] == "atualizado":
            if r.get("job_novo") is False:
                resumo["identicos"] += 1
            else:
                resumo["atualizados"] += 1
            resumo["filtrados"] += 1
            resumo["analisados"] += 1
        elif r["acao"] == "requer_apuracao_humana":
            resumo["filtrados"] += 1
            resumo["analisados"] += 1

    db_writer.registrar_log_coleta(sb, execucao_id, source_id, resumo, empresa_id=empresa_id)
    return {"resumo": resumo, "resultados": resultados}

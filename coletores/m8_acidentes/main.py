"""
Módulo 8 — orquestrador do coletor (Carta M8 §5 fluxo técnico obrigatório
completo). Pensado para rodar via GitHub Actions (ver
.github/workflows/coletor_m8.yml), nunca no ambiente do Claude.

IMPORTANTE — leia antes de rodar contra a fonte real:
1. discovery.py (seletores HTML) e signals.py (heurística de palavras-chave)
   NÃO foram validados contra a página/documento reais (sandbox sem acesso
   de rede — ver avisos nos dois arquivos). scoring.py está testado e
   correto; db_writer.py segue os padrões já usados no resto do Radar.
2. Por segurança, TODO evento criado ou atualizado por este coletor entra
   com revisao_humana='Pendente' e status_editorial='em_apuracao' —
   mesmo os classificados como faixa_vinculo='confirmado'. Nada é
   publicado automaticamente (carta §14 já exige isso; aqui é reforçado
   no código, não só na regra).
3. Rodar primeiro em ambiente='piloto' contra uma amostra pequena e revisar
   manualmente antes de apontar para produção de verdade.
"""
import argparse
import sys
import time
from datetime import datetime, timezone

import discovery
import extractor
import signals
import scoring
import checklist_editorial
import db_writer


def processar_item(sb, execucao_id: str, source_id: str, item: discovery.ItemInventario) -> dict:
    """Processa um item novo/alterado do inventário. Retorna um resumo da
    ação tomada para o relatório de execução."""
    t0 = time.monotonic()
    resultado_extracao = extractor.extrair(item.url_detalhe)

    db_writer.registrar_log_busca(
        sb, execucao_id, source_id, item.url_detalhe,
        codigo_http=200 if resultado_extracao.status_processamento != "falha_extracao" else None,
        hash_conteudo=resultado_extracao.hash_documento,
        erro=resultado_extracao.motivo_falha,
    )

    id_evento = f"semad-m8-{item.protocolo.replace('/', '-')}"

    if resultado_extracao.status_processamento == "falha_extracao":
        # Carta §16: documento não abre -> preservar alerta básico, não
        # descartar o evento, encaminhar à fila manual.
        event_id, criado = db_writer.upsert_evento(sb, id_evento, {
            "titulo_fato": item.titulo_fonte,
            "municipio": item.municipio,
            "status_editorial": "em_apuracao",
            "revisao_humana": "Pendente",
            "status_enriquecimento": f"[falha de extração] {resultado_extracao.motivo_falha}",
        }, execucao_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, {
            "url_lista": discovery.URL_PAGINA_ANUAL,
            "url_detalhe": item.url_detalhe,
            "status_processamento": "falha_extracao",
            "motivo_descarte": resultado_extracao.motivo_falha,
            "score_vinculo": 0,
            "faixa_vinculo": "contextual",
        })
        # Checklist: documento não abriu -> as 12 perguntas ficam todas
        # 'requer_apuracao_humana' (nunca "não localizado" — não chegamos
        # nem a procurar no texto; checklist §Regra central).
        respostas = checklist_editorial.derivar_checklist_m8(extracao_falhou=True, faixa_vinculo="contextual")
        db_writer.gravar_checklist_editorial(sb, event_id, respostas)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=item.hash_linha, status="pendente_revisao",
            tempo_gasto_segundos=time.monotonic() - t0,
            erro=resultado_extracao.motivo_falha,
        )
        return {"protocolo": item.protocolo, "acao": "falha_extracao", "criado": criado}

    sig_vinculo = signals.extrair_signais_vinculo(resultado_extracao.texto, item.municipio or "")
    score_v, faixa_v, justificativa_v = scoring.score_vinculo(sig_vinculo)

    campos_evento = {
        "titulo_fato": item.titulo_fonte,
        "municipio": item.municipio,
        "status_editorial": "em_apuracao",
        "revisao_humana": "Pendente",  # nunca automático — carta §14, reforçado aqui
        "url_oficial": item.url_detalhe,
        "hash_versao": resultado_extracao.hash_documento,
    }

    detalhe_m8 = {
        "url_lista": discovery.URL_PAGINA_ANUAL,
        "url_detalhe": item.url_detalhe,
        "hash_documento": resultado_extracao.hash_documento,
        "score_vinculo": score_v,
        "faixa_vinculo": faixa_v,
        "justificativa_vinculo": "; ".join(justificativa_v),
        "metodo_extracao": resultado_extracao.metodo_extracao,
        "qualidade_ocr": resultado_extracao.qualidade_ocr,
        "status_processamento": "processado" if faixa_v != "descartado" else "descartado",
        "versao_regra_score": scoring.VERSAO_REGRA_SCORE,
        "data_ultima_verificacao": datetime.now(timezone.utc).isoformat(),
    }

    # Checklist §Inventário de documentos: um `documentos` por comunicado,
    # com proveniência própria (URL, hash, páginas) — não só o hash solto
    # dentro do detalhe do M8. Só dá pra gravar depois que o evento existe
    # (documentos.event_id referencia events.id), por isso vira uma função
    # chamada depois de cada upsert_evento abaixo, não uma linha solta aqui.
    def _finalizar_evidencias_e_checklist(event_id: str):
        documento_id = db_writer.gravar_documento(
            sb, event_id, url=item.url_detalhe, hash_documento=resultado_extracao.hash_documento,
            status="processado", paginas_ocr=resultado_extracao.paginas_processadas,
        )
        evidencias = signals.extrair_evidencias_vinculo(resultado_extracao.texto, item.municipio or "")
        if faixa_v in ("provavel", "confirmado"):
            evidencias += signals.extrair_evidencias_gravidade(resultado_extracao.texto)
        if resultado_extracao.texto:
            evidencias.append({
                "campo": "descricao_literal",
                "trecho_literal": resultado_extracao.texto[:800],
                "palavra_gatilho": None,
            })
        db_writer.gravar_evidencias_campo(sb, event_id, documento_id, evidencias,
                                           metodo_extracao=resultado_extracao.metodo_extracao)

    if faixa_v == "descartado":
        detalhe_m8["motivo_descarte"] = "; ".join(justificativa_v) or "score de vínculo abaixo de 2"
        event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8)
        _finalizar_evidencias_e_checklist(event_id)
        respostas = checklist_editorial.derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo=faixa_v,
            empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
            descricao_literal=(resultado_extracao.texto or None),
        )
        db_writer.gravar_checklist_editorial(sb, event_id, respostas)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
            tempo_gasto_segundos=time.monotonic() - t0,
        )
        return {"protocolo": item.protocolo, "acao": "descartado", "faixa": faixa_v, "criado": criado}

    # faixa 'contextual' fica no histórico sem alerta automático (carta §8);
    # 'provavel'/'confirmado' seguem para score de gravidade (carta §5 passo 9).
    if faixa_v in ("provavel", "confirmado"):
        sig_gravidade = signals.extrair_signais_gravidade(resultado_extracao.texto)
        score_g, nivel_g = scoring.score_gravidade(sig_gravidade)
        detalhe_m8["score_gravidade"] = score_g
        detalhe_m8["nivel_gravidade"] = nivel_g

        prioridade = {"alerta_imediato": "A", "pauta_apuracao": "B",
                       "registro_acompanhamento": "C", "arquivo_contextual": "D"}[nivel_g]

        event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8)
        db_writer.gravar_score(sb, event_id, score_bruto=score_g, prioridade=prioridade,
                                componentes={"score_vinculo": score_v, "faixa_vinculo": faixa_v,
                                             "score_gravidade": score_g, "nivel_gravidade": nivel_g})
        _finalizar_evidencias_e_checklist(event_id)

        antecedentes = db_writer.buscar_antecedentes_m8(
            sb, event_id, empresa_citada=None, mina_unidade=None,
        )  # TODO: empresa_citada/mina_unidade ainda não vêm de discovery/signals — ver aviso no topo de discovery.py
        if antecedentes:
            db_writer.gravar_eventos_relacionados(sb, event_id, antecedentes)

        respostas = checklist_editorial.derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo=faixa_v,
            empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
            descricao_literal=(resultado_extracao.texto or None),
            score_gravidade_calculado=True, teve_antecedentes=bool(antecedentes),
        )
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, prioridade=prioridade)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
            tempo_gasto_segundos=time.monotonic() - t0,
        )
        return {"protocolo": item.protocolo, "acao": "processado", "faixa": faixa_v,
                "prioridade": prioridade, "criado": criado}

    # contextual
    event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id)
    db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8)
    _finalizar_evidencias_e_checklist(event_id)
    respostas = checklist_editorial.derivar_checklist_m8(
        extracao_falhou=False, faixa_vinculo=faixa_v,
        empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
        descricao_literal=(resultado_extracao.texto or None),
    )
    db_writer.gravar_checklist_editorial(sb, event_id, respostas)
    db_writer.gravar_job_enriquecimento(
        sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
        tempo_gasto_segundos=time.monotonic() - t0,
    )
    return {"protocolo": item.protocolo, "acao": "contextual", "faixa": faixa_v, "criado": criado}


def run(ambiente: str = "piloto", limite: int = None):
    sb = db_writer.get_client()
    source_id = db_writer.buscar_fonte_id(sb)

    id_execucao = f"M8-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente)

    resumo = {"brutos": 0, "novos": 0, "atualizados": 0, "identicos": 0,
              "descartados": 0, "erros": 0, "processados": 0}
    resultados = []

    try:
        resp = discovery.buscar_pagina(discovery.URL_PAGINA_ANUAL)
        inventario = discovery.parse_inventario(resp.text)
        resumo["brutos"] = len(inventario)

        # TODO: carregar hashes_anteriores real de m8_acidentes_detalhe
        # (select protocolo_semad, ano, hash_documento) em vez de {} —
        # {} força tudo a ser tratado como novo na primeira rodada, o que
        # é o comportamento certo só na carga inicial.
        hashes_anteriores = {}
        comparacao = discovery.comparar_com_inventario_anterior(inventario, hashes_anteriores)

        itens_a_processar = comparacao["novos"] + comparacao["alterados"]
        if limite:
            itens_a_processar = itens_a_processar[:limite]

        for item in itens_a_processar:
            try:
                r = processar_item(sb, execucao_id, source_id, item)
                resultados.append(r)
                if r["acao"] == "falha_extracao":
                    resumo["erros"] += 1
                elif r["acao"] == "descartado":
                    resumo["descartados"] += 1
                else:
                    resumo["processados"] += 1
                resumo["novos" if r.get("criado") else "atualizados"] += 1
            except Exception as e:
                resumo["erros"] += 1
                resultados.append({"protocolo": item.protocolo, "acao": "erro", "erro": str(e)})

        resumo["identicos"] = len(comparacao["identicos"])

        db_writer.registrar_log_coleta(sb, execucao_id, source_id, {
            "brutos": resumo["brutos"], "filtrados": len(itens_a_processar),
            "analisados": len(itens_a_processar), "novos": resumo["novos"],
            "atualizados": resumo["atualizados"], "identicos": resumo["identicos"],
            "descartados": resumo["descartados"], "erros": resumo["erros"],
        })
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="concluída")

    except Exception as e:
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="falha")
        raise

    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M8 — Acidentes SEMAD")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite", type=int, default=None, help="processar só os N primeiros itens novos/alterados (teste)")
    args = parser.parse_args()

    resultado = run(ambiente=args.ambiente, limite=args.limite)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

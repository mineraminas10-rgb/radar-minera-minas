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
import os
import re
import sys
import time
from datetime import datetime, timezone
from dataclasses import replace
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))

import acesso
import diagnostico
import log_busca
import pre_ia
import rotas
import discovery
import extractor
import signals
import scoring
import checklist_editorial
import db_writer

from dateutil import parser as dateutil_parser


def construir_id_evento(protocolo: str) -> str:
    """Chave de negócio do evento M8 — SEMPRE pelo protocolo do comunicado
    (carta §3: 'identificado prioritariamente por protocolo e endereço
    permanente do documento'), nunca por empresa+data+município.

    Isso não é só estilo: é a trava que impede reproduzir o erro do caso
    Vale apontado pela Carta de Revisão/Calibração de Scores M8/M9A (score
    87 indevidamente combinando dois acidentes distintos do mesmo dia —
    Mina de Fábrica e Mina de Viga, mesma empresa, mesma data, estruturas e
    consequências diferentes). Como cada comunicado da SEMAD tem seu
    próprio protocolo, dois acidentes nunca colapsam no mesmo id_evento
    só por coincidirem em empresa/data/município — ver
    test_identidade_evento.py."""
    return f"semad-m8-{protocolo.replace('/', '-')}"


def _parse_data_segura(texto: str):
    """Tenta interpretar `texto` (data crua de fonte HTML, formato não
    garantido) como data real. Retorna None em vez de arriscar gravar uma
    data errada — nunca deduz "atraso" ou datas a partir de texto ambíguo
    (mesma régua de "não atribuir sem prova" usada no resto do projeto)."""
    try:
        return dateutil_parser.parse(texto, dayfirst=True, fuzzy=True).date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return None


def resolver_protocolo(sb, item, texto: str, empresa_id: str, execucao_id=None):
    """O protocolo oficial está no texto do comunicado ("Nº Protocolo: 204/2026"). Quando a lista só deu o
    identificador provisório `arq<id>`, troca pelo protocolo lido do texto — sem duplicar eventos já criados
    com o provisório. Leitura ausente/duvidosa ou protocolo de outro arquivo: mantém o provisório (nunca chuta)."""
    if item.protocolo_origem != "id_do_arquivo":
        return item
    achado = discovery.extrair_protocolo_do_comunicado(texto, item.ano)
    if not achado:
        print(f"[M8] aviso: protocolo não lido no texto de {item.protocolo}; mantido o identificador provisório")
        return item
    protocolo, ano = achado
    situacao = db_writer.resolver_protocolo_provisorio(
        sb, empresa_id, item.protocolo, protocolo, ano, item.id_arquivo,
        construir_id_evento(item.protocolo), construir_id_evento(protocolo), execucao_id)
    if situacao == "conflito":
        print(f"[M8] aviso: protocolo {protocolo}/{ano} lido em {item.protocolo} já pertence a outro arquivo; mantido o provisório")
        return item
    print(f"[M8] protocolo {item.protocolo} -> {protocolo}/{ano} ({situacao})")
    return replace(item, protocolo=protocolo, ano=ano, protocolo_origem="texto_do_comunicado")


def processar_item(sb, execucao_id: str, source_id: str, item: discovery.ItemInventario,
                    empresa_id: Optional[str] = None, acessador=None) -> dict:
    """Processa um item novo/alterado do inventário. Retorna um resumo da
    ação tomada para o relatório de execução."""
    t0 = time.monotonic()
    resultado_extracao = extractor.extrair(item.url_detalhe, acessador=acessador)

    if acessador is None:
        # caminho legado (sem Acessador): registro mínimo. Com Acessador, cada requisição já foi
        # registrada por completo em log_busca (status, MIME, tamanho, hash, URL final, resultado).
        db_writer.registrar_log_busca(
            sb, execucao_id, source_id, item.url_detalhe,
            codigo_http=200 if resultado_extracao.status_processamento != "falha_extracao" else None,
            hash_conteudo=resultado_extracao.hash_documento,
            erro=resultado_extracao.motivo_falha,
            empresa_id=empresa_id,
        )

    id_evento = construir_id_evento(item.protocolo)

    if resultado_extracao.status_processamento == "falha_extracao":
        # Carta §16: documento não abre -> preservar alerta básico, não
        # descartar o evento, encaminhar à fila manual.
        event_id, criado = db_writer.upsert_evento(sb, id_evento, {
            "titulo_fato": item.titulo_fonte,
            "municipio": item.municipio,
            "status_editorial": "em_apuracao",
            "revisao_humana": "Pendente",
            "status_enriquecimento": f"[falha de extração] {resultado_extracao.motivo_falha}",
        }, execucao_id, empresa_id=empresa_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, {
            "url_lista": discovery.URL_PAGINA_ANUAL,
            "url_detalhe": item.url_detalhe,
            "status_processamento": "falha_extracao",
            "motivo_descarte": resultado_extracao.motivo_falha,
            "score_vinculo": 0,
            "faixa_vinculo": "contextual",
        }, empresa_id=empresa_id)
        # Checklist: documento não abriu -> as 12 perguntas ficam todas
        # 'requer_apuracao_humana' (nunca "não localizado" — não chegamos
        # nem a procurar no texto; checklist §Regra central). Nenhuma é
        # 'confirmado'/'nao_localizado', então não precisa de evidencia_id/
        # observacao aqui.
        respostas = checklist_editorial.derivar_checklist_m8(extracao_falhou=True, faixa_vinculo="contextual")
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id)
        # grau_completude explícito: 'Baixa' sempre que a extração falhou —
        # não pode nascer do tamanho do texto (não há texto nenhum aqui).
        db_writer.upsert_evento(sb, id_evento, {"grau_completude": "Baixa"}, execucao_id, empresa_id=empresa_id)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=item.hash_linha, status="pendente_revisao",
            tempo_gasto_segundos=time.monotonic() - t0,
            erro=resultado_extracao.motivo_falha, empresa_id=empresa_id,
        )
        return {"protocolo": item.protocolo, "acao": "falha_extracao", "criado": criado,
                "paginas_ocr": resultado_extracao.paginas_processadas or 0}

    item = resolver_protocolo(sb, item, resultado_extracao.texto, empresa_id, execucao_id)
    id_evento = construir_id_evento(item.protocolo)

    sig_vinculo = signals.extrair_signais_vinculo(resultado_extracao.texto, item.municipio or "")
    score_v, faixa_v, justificativa_v = scoring.score_vinculo(sig_vinculo)

    # Regra utilizada (proveniência) — só leitura, não decide o score:
    # se já existir uma regras_evento cadastrada para esta fonte+tipo de
    # evento, event_scores registra qual foi usada. Tipo de evento deste
    # módulo é sempre "comunicado_acidente_ambiental" (não varia por item,
    # diferente do M9A onde cada ato tem seu próprio tipo textual do SCM).
    regra = db_writer.buscar_regra_evento(sb, source_id, "comunicado_acidente_ambiental")

    campos_evento = {
        "titulo_fato": item.titulo_fonte,
        "municipio": item.municipio,
        "status_editorial": "em_apuracao",
        "revisao_humana": "Pendente",  # nunca automático — carta §14, reforçado aqui
        "url_oficial": item.url_detalhe,
        "hash_versao": resultado_extracao.hash_documento,
        "tipo_evento": "comunicado_acidente_ambiental",
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
    def _finalizar_evidencias_e_checklist(event_id: str) -> str:
        """Grava documento + evidências, escreve a timeline (achado da
        auditoria: M8 nunca gravava timeline_processual) e devolve o id da
        evidência "geral" (descricao_literal) para o checklist poder
        satisfazer chk_confirmado_exige_evidencia sem inventar vínculo por
        campo específico (ver docstring de gravar_checklist_editorial)."""
        documento_id = db_writer.gravar_documento(
            sb, event_id, url=item.url_detalhe, hash_documento=resultado_extracao.hash_documento,
            status="processado", paginas_ocr=resultado_extracao.paginas_processadas,
            empresa_id=empresa_id,
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
        gravadas = db_writer.gravar_evidencias_campo(sb, event_id, documento_id, evidencias,
                                                       metodo_extracao=resultado_extracao.metodo_extracao,
                                                       empresa_id=empresa_id)
        evidencia_geral = next((g for g in gravadas if g["campo"] == "descricao_literal"), None)
        evidencia_padrao_id = evidencia_geral["id"] if evidencia_geral else (
            gravadas[0]["id"] if gravadas else None
        )

        # Timeline (marco 'documento' — ver TIPOS_MARCO_TIMELINE em
        # db_writer.py). item.data_publicada é texto cru "como aparece na
        # página" (discovery.py), não garantidamente um formato de data
        # parseável — nunca grava um valor que não conseguimos interpretar
        # com confiança como data real (evita `date` inválido silencioso
        # no banco).
        if item.data_publicada:
            data_marco = _parse_data_segura(item.data_publicada)
            if data_marco:
                db_writer.gravar_marco_timeline(
                    sb, event_id, tipo_marco="documento", data_marco=data_marco,
                    trecho_literal=(resultado_extracao.texto[:500] if resultado_extracao.texto else None),
                    evidencia_id=evidencia_padrao_id, empresa_id=empresa_id,
                )

        return evidencia_padrao_id

    if faixa_v == "descartado":
        detalhe_m8["motivo_descarte"] = "; ".join(justificativa_v) or "score de vínculo abaixo de 2"
        event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id, empresa_id=empresa_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8, empresa_id=empresa_id)
        evidencia_padrao_id = _finalizar_evidencias_e_checklist(event_id)
        respostas = checklist_editorial.derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo=faixa_v,
            empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
            descricao_literal=(resultado_extracao.texto or None),
        )
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id,
                                              evidencia_padrao_id=evidencia_padrao_id)
        db_writer.upsert_evento(sb, id_evento, {
            "grau_completude": checklist_editorial.calcular_grau_completude(respostas),
        }, execucao_id, empresa_id=empresa_id)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
            tempo_gasto_segundos=time.monotonic() - t0, empresa_id=empresa_id,
        )
        return {"protocolo": item.protocolo, "acao": "descartado", "faixa": faixa_v, "criado": criado,
                "paginas_ocr": resultado_extracao.paginas_processadas or 0}

    # faixa 'contextual' fica no histórico sem alerta automático (carta §8);
    # 'provavel'/'confirmado' seguem para score de gravidade (carta §5 passo 9).
    if faixa_v in ("provavel", "confirmado"):
        sig_gravidade = signals.extrair_signais_gravidade(resultado_extracao.texto)
        score_g, nivel_g = scoring.score_gravidade(sig_gravidade)
        detalhe_m8["score_gravidade"] = score_g
        detalhe_m8["nivel_gravidade"] = nivel_g

        prioridade = {"alerta_imediato": "A", "pauta_apuracao": "B",
                       "registro_acompanhamento": "C", "arquivo_contextual": "D"}[nivel_g]

        event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id, empresa_id=empresa_id)
        db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8, empresa_id=empresa_id)

        memoria_vinculo = scoring.montar_memoria_calculo_vinculo(sig_vinculo, justificativa_v)
        memoria_gravidade = scoring.montar_memoria_calculo_gravidade(sig_gravidade)
        db_writer.gravar_score(
            sb, event_id, score_bruto=score_g, prioridade=prioridade,
            componentes={"score_vinculo": score_v, "faixa_vinculo": faixa_v,
                         "score_gravidade": score_g, "nivel_gravidade": nivel_g},
            empresa_id=empresa_id,
            score_normalizado=scoring.calcular_score_normalizado(score_g),
            regra_evento_id=regra["id"] if regra else None,
            regra_evento_versao=regra["versao"] if regra else None,
            # gatilhos/redutores/piso/teto: gravidade não tem redutor/piso/teto
            # próprio (Carta §9), então combino os dois blocos de memória —
            # gatilhos_aplicados junta vínculo+gravidade (as duas pontuações
            # que compõem esta decisão), o resto vem só de gravidade.
            gatilhos_aplicados={**memoria_vinculo["gatilhos_aplicados"], **memoria_gravidade["gatilhos_aplicados"]},
            redutores_aplicados=memoria_vinculo["redutores_aplicados"],
            piso_aplicado=memoria_vinculo["piso_aplicado"],
            teto_aplicado=memoria_vinculo["teto_aplicado"],
        )
        evidencia_padrao_id = _finalizar_evidencias_e_checklist(event_id)

        antecedentes = db_writer.buscar_antecedentes_m8(
            sb, event_id, empresa_citada=None, mina_unidade=None,
        )  # TODO: empresa_citada/mina_unidade ainda não vêm de discovery/signals — ver aviso no topo de discovery.py
        if antecedentes:
            db_writer.gravar_eventos_relacionados(sb, event_id, antecedentes, empresa_id=empresa_id)

        respostas = checklist_editorial.derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo=faixa_v,
            empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
            descricao_literal=(resultado_extracao.texto or None),
            score_gravidade_calculado=True, teve_antecedentes=bool(antecedentes),
        )
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, prioridade=prioridade, empresa_id=empresa_id,
                                              evidencia_padrao_id=evidencia_padrao_id)
        db_writer.upsert_evento(sb, id_evento, {
            "grau_completude": checklist_editorial.calcular_grau_completude(respostas),
        }, execucao_id, empresa_id=empresa_id)
        db_writer.gravar_job_enriquecimento(
            sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
            tempo_gasto_segundos=time.monotonic() - t0, empresa_id=empresa_id,
        )
        return {"protocolo": item.protocolo, "acao": "processado", "faixa": faixa_v,
                "prioridade": prioridade, "criado": criado,
                "paginas_ocr": resultado_extracao.paginas_processadas or 0}

    # contextual
    event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id, empresa_id=empresa_id)
    db_writer.upsert_m8_detalhe(sb, event_id, item.protocolo, item.ano, detalhe_m8, empresa_id=empresa_id)
    evidencia_padrao_id = _finalizar_evidencias_e_checklist(event_id)
    respostas = checklist_editorial.derivar_checklist_m8(
        extracao_falhou=False, faixa_vinculo=faixa_v,
        empresa_citada=None, local_descrito=item.municipio, municipio=item.municipio,
        descricao_literal=(resultado_extracao.texto or None),
    )
    db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id,
                                          evidencia_padrao_id=evidencia_padrao_id)
    db_writer.upsert_evento(sb, id_evento, {
        "grau_completude": checklist_editorial.calcular_grau_completude(respostas),
    }, execucao_id, empresa_id=empresa_id)
    db_writer.gravar_job_enriquecimento(
        sb, event_id, hash_entrada=resultado_extracao.hash_documento, status="concluido",
        tempo_gasto_segundos=time.monotonic() - t0, empresa_id=empresa_id,
    )
    return {"protocolo": item.protocolo, "acao": "contextual", "faixa": faixa_v, "criado": criado,
            "paginas_ocr": resultado_extracao.paginas_processadas or 0}


PROCESSADOS_FINAIS = ("processado", "descartado")


def carregar_processados(sb, empresa_id: str) -> set:
    """(protocolo, ano) já processados com documento e hash gravados. Esses itens NÃO são baixados nem
    reanalisados de novo (zero requisição, zero OCR, zero IA) — só falhas/pendências voltam à fila."""
    # só o que foi processado PARA ESTA EMPRESA conta: o que outra empresa já processou não dispensa a coleta daqui
    r = sb.table("m8_acidentes_detalhe").select("protocolo_semad, ano, status_processamento, hash_documento, url_detalhe").eq("empresa_id", empresa_id).execute()
    saida = set()
    for x in (r.data or []):
        if str(x.get("protocolo_semad") or "").startswith("arq"):
            continue    # protocolo ainda provisório: volta à fila para o protocolo real ser lido do texto
        if x.get("status_processamento") in PROCESSADOS_FINAIS and x.get("hash_documento"):
            saida.add((x["protocolo_semad"], x["ano"]))
            # a lista pode continuar oferecendo o comunicado só pelo id do arquivo (identificador provisório):
            # o id está na url_detalhe, então o item continua reconhecido como já processado
            m_id = re.search(r"view_file/(\d+)", x.get("url_detalhe") or "")
            if m_id:
                saida.add((f"arq{m_id.group(1)}", x["ano"]))
    return saida


def separar_conhecidos(itens, processados: set):
    novos, conhecidos = [], []
    for it in itens:
        (conhecidos if (it.protocolo, it.ano) in processados else novos).append(it)
    return novos, conhecidos


def _flags_do_resultado(r: dict) -> dict:
    return pre_ia.flags_m8(extracao_falhou=(r["acao"] == "falha_extracao"), faixa_vinculo=r.get("faixa") or "contextual",
                           hash_documento=None, hash_documento_anterior=None)


def contagens_log_coleta(resumo: dict, resultados: list, filtrados: int) -> dict:
    """Linha do log_coleta. O banco exige (chk_analisados_soma): analisados = identicos + atualizados + novos
    + duplicatas + descartados. Por isso os baldes são DISJUNTOS, calculados do resultado de cada item
    (falha/erro ficam só em `erros`, fora de `analisados`; `resumo["novos"]/["atualizados"]` não servem
    porque também contam descartados e falhas de extração)."""
    novos = atualizados = descartados = 0
    for r in resultados:
        acao = r.get("acao")
        if acao in ("falha_extracao", "erro") or "erro" in r:
            continue
        if acao == "descartado":
            descartados += 1
        elif r.get("criado"):
            novos += 1
        else:
            atualizados += 1
    identicos = resumo["identicos"]
    return {"brutos": resumo["brutos"], "filtrados": filtrados,
            "analisados": identicos + atualizados + novos + descartados,
            "novos": novos, "atualizados": atualizados, "identicos": identicos,
            "descartados": descartados, "erros": resumo["erros"]}


def run(ambiente: str = "piloto", limite: int = None, reverificar: bool = False, sb=None,
        sessao_http=None, env=None, empresa_id: str = None, carteira_id: str = None):
    etapas = diagnostico.Etapas("M8")
    contador = pre_ia.ContadorPreIa()
    resumo = {"brutos": 0, "novos": 0, "atualizados": 0, "identicos": 0,
              "descartados": 0, "erros": 0, "processados": 0,
              # Custo/processamento — este coletor não chama IA (classificação por sinais/regex);
              # os contadores pre_ia_* dizem quantos registros SERIAM elegíveis e por que os demais foram dispensados.
              "documentos_processados": 0, "paginas_ocr_total": 0,
              "chamadas_ia": 0, "tokens_ia": 0, "custo_estimado_reais": 0.0}
    resultados = []
    execucao_id = None
    acessador = None

    def finalizar(status):
        nonlocal execucao_id
        resumo.update(contador.resumo())
        resumo["diagnostico_etapas"] = etapas.registro
        resumo["barreiras_de_acesso"] = acessador.barreiras if acessador is not None else []
        if execucao_id:
            try:
                db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final=status)
            except Exception as e:   # não esconde a causa original
                print(f"[M8] aviso: não consegui finalizar a execução: {e}")
        etapas.gravar_resumo_job()

    try:
        with etapas.etapa("ambiente"):
            print("[M8] ambiente:", diagnostico.checar_ambiente(env))
        with etapas.etapa("conexao_supabase"):
            if sb is None:
                try:
                    sb = db_writer.get_client()
                except Exception as e:
                    dica = " (a versão antiga do pacote 'supabase' recusa chaves sb_secret_; usar supabase>=2.15)" if "Invalid API key" in str(e) else ""
                    raise RuntimeError(f"{e}{dica}")
        with etapas.etapa("cadastro_de_fontes"):
            fonte = db_writer.buscar_fonte(sb, empresa_id=empresa_id, carteira_id=carteira_id)
            source_id, empresa_id, carteira_id = fonte["id"], fonte["empresa_id"], fonte["carteira_id"]
            print(f"[M8] escopo: empresa={empresa_id} carteira={carteira_id}")
            print("[M8] rota:", rotas.descricao_da_rota("M8"))
        with etapas.etapa("criar_execucao"):
            id_execucao = f"M8-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente, empresa_id=empresa_id, carteira_id=carteira_id)

        def sink(reg):
            reg["versao_rotas"] = rotas.VERSAO_ROTAS
            try:
                log_busca.gravar(sb, reg, execucao_id, source_id, empresa_id)
            except Exception as e:
                print(f"[M8] aviso: log_busca não gravado ({e})")

        acessador = acesso.Acessador("M8", source_id=source_id, sink=sink, session=sessao_http)

        with etapas.etapa("descoberta"):
            resp = acessador.get(discovery.URL_PAGINA_ANUAL, metodo_acesso="m8_descoberta")
            print(f"[M8] página anual: status={resp.status} mime={resp.content_type} bytes={len(resp.corpo)} url_final={resp.url_final}")
            inventario = discovery.parse_inventario(resp.texto, base_url=resp.url_final)
            if not inventario:
                trecho = " ".join(resp.texto[:600].split())[:200]
                raise diagnostico.ErroEtapa(
                    "descoberta", "a página foi aberta mas nenhum comunicado (cartão com protocolo/link) foi reconhecido",
                    f"a estrutura da página mudou ou a resposta não é a lista; discovery.py precisa ser revisto. Início da página: {trecho!r}")
            total = discovery.total_informado(resp.texto)
            outras = discovery.urls_outras_paginas(resp.texto, base_url=resp.url_final)
            print(f"[M8] página 1: {len(inventario)} comunicados; a SEMAD informa {total} no total; {len(outras)} outras páginas")
            # Com `limite` (piloto) não percorre a lista inteira: abre mais páginas só enquanto faltarem itens
            # ainda não processados para completar o limite. Sem limite, percorre todas (a lista é pequena).
            processados_previos = set() if reverificar else carregar_processados(sb, empresa_id)
            def pendentes(inv):
                return sum(1 for it in inv if (it.protocolo, it.ano) not in processados_previos)
            vistos_chaves = {(it.protocolo, it.ano) for it in inventario}
            for url_p in outras:
                if limite and pendentes(inventario) >= limite:
                    break
                try:
                    rp = acessador.get(url_p, metodo_acesso="m8_descoberta")
                except Exception as e:
                    print(f"[M8] aviso: página da lista não abriu ({e}); sigo com o que já foi lido")
                    break
                novos_p = [it for it in discovery.parse_inventario(rp.texto, base_url=rp.url_final)
                           if (it.protocolo, it.ano) not in vistos_chaves]
                vistos_chaves.update((it.protocolo, it.ano) for it in novos_p)
                inventario.extend(novos_p)
            resumo["brutos"] = len(inventario)
            print(f"[M8] inventário: {len(inventario)} comunicados lidos ({pendentes(inventario)} ainda não processados)")

        with etapas.etapa("comparacao_e_deduplicacao"):
            comparacao = discovery.comparar_com_inventario_anterior(inventario, {})
            processados = processados_previos
            a_proc, conhecidos = separar_conhecidos(comparacao["novos"] + comparacao["alterados"], processados)
            for _ in conhecidos:
                contador.registrar(pre_ia.flags_m8(extracao_falhou=False, faixa_vinculo="provavel", hash_documento=None,
                                                   hash_documento_anterior=None, ja_processado=True))
            itens_a_processar = a_proc[:limite] if limite else a_proc
            resumo["identicos"] = len(comparacao["identicos"]) + len(conhecidos)

        with etapas.etapa("processamento"):
            for item in itens_a_processar:
                try:
                    r = processar_item(sb, execucao_id, source_id, item, empresa_id=empresa_id, acessador=acessador)
                    resultados.append(r)
                    contador.registrar(_flags_do_resultado(r))
                    if r["acao"] == "falha_extracao":
                        resumo["erros"] += 1
                    elif r["acao"] == "descartado":
                        resumo["descartados"] += 1
                    else:
                        resumo["processados"] += 1
                    resumo["novos" if r.get("criado") else "atualizados"] += 1
                    resumo["documentos_processados"] += 1
                    if r.get("paginas_ocr"):
                        resumo["paginas_ocr_total"] += r["paginas_ocr"]
                except Exception as e:
                    resumo["erros"] += 1
                    resultados.append({"protocolo": item.protocolo, "acao": "erro", "erro": str(e)})
                if acessador.barreiras and acessador.barreiras[-1]["status_http"] in (401, 403, 429):
                    # barreira em requisição desta rodada: não insistir nos demais itens da mesma fonte
                    print("[M8] barreira de acesso detectada; interrompendo a rodada sem contornar")
                    break

        with etapas.etapa("registro_final"):
            db_writer.registrar_log_coleta(sb, execucao_id, source_id,
                                           contagens_log_coleta(resumo, resultados, len(itens_a_processar)),
                                           empresa_id=empresa_id)
        finalizar("concluída")

    except Exception as e:
        resumo["falha"] = str(e)
        finalizar("falha")
        print(f"[M8] FALHA: {e}")
        raise

    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M8 — Acidentes SEMAD")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite", type=int, default=None, help="processar só os N primeiros itens novos/alterados (teste)")
    parser.add_argument("--reverificar", action="store_true", help="reabrir também os comunicados já processados")
    parser.add_argument("--empresa-id", default=os.environ.get("RADAR_EMPRESA_ID"), help="empresa dona desta coleta (obrigatório se a fonte existir em mais de uma)")
    parser.add_argument("--carteira-id", default=os.environ.get("RADAR_CARTEIRA_ID"), help="carteira da empresa (padrão: a única que usa a fonte)")
    args = parser.parse_args()

    resultado = run(ambiente=args.ambiente, limite=args.limite, reverificar=args.reverificar,
                    empresa_id=args.empresa_id, carteira_id=args.carteira_id)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

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
import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))

import checklist_editorial
import db_writer
import discovery
import extractor
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
    # Texto usado SÓ no filtro de vínculo mineral. Quando preenchido, não contém nome do titular nem CNPJ
    # (nome de empresa nunca decide vínculo — carta §44.9). Vazio = usa o próprio trecho decisório.
    texto_para_vinculo: Optional[str] = None


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
        atividade_associada=ato.atividade_associada or "",
        texto_livre=ato.texto_para_vinculo if ato.texto_para_vinculo is not None else ato.trecho_decisorio,
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
        # Vínculo mineral confirmado e verbo identificado, mas o score do M6 exige julgamento editorial explícito
        # por componente (ver scoring.py) — este coletor não usa IA nem inventa componentes. O evento fica em
        # apuração, sem score, esperando a etapa de IA/editor. Nunca um score default.
        respostas = checklist_editorial.derivar_checklist_m6(fora_de_escopo=False, tipo_evento_normalizado=tipo_evento)
        db_writer.gravar_checklist_editorial(sb, event_id, respostas, empresa_id=empresa_id)
        return {"processo_ou_portaria": ato.processo_ou_portaria, "acao": "aguardando_score",
                "tipo_evento": tipo_evento, "motivo": "vínculo mineral confirmado; score depende de julgamento editorial/IA",
                "criado": criado, "event_id": event_id}

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


def contagens_log_coleta(resultados: list, brutos: int, identicos: int = 0) -> dict:
    """Linha do log_coleta. O banco exige (chk_analisados_soma): analisados = identicos + atualizados + novos
    + duplicatas + descartados — baldes DISJUNTOS calculados do resultado de cada ato. Erros ficam só em
    `erros` (fora de `analisados`). Atos em apuração/aguardando score contam como novos ou atualizados."""
    novos = atualizados = descartados = erros = 0
    for r in resultados:
        acao = r.get("acao")
        if acao == "erro" or "erro" in r:
            erros += 1
        elif acao == "descartado":
            descartados += 1
        elif r.get("criado"):
            novos += 1
        else:
            atualizados += 1
    analisados = identicos + atualizados + novos + descartados
    return {"brutos": brutos, "filtrados": novos + atualizados, "analisados": analisados, "novos": novos,
            "atualizados": atualizados, "identicos": identicos, "duplicatas_bloqueadas": 0,
            "descartados": descartados, "erros": erros}


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

    db_writer.registrar_log_coleta(sb, execucao_id, source_id,
                                   contagens_log_coleta(resultados, resumo["brutos"], resumo["identicos"]), empresa_id=empresa_id)
    return {"resumo": resumo, "resultados": resultados}


# ============================================================================================
# Coleta real (GitHub Actions, manual): índice -> documentos novos -> texto -> atos -> eventos.
# SEM IA. Todo evento nasce 'em_apuracao'/'descartado' com revisao_humana='Pendente'; nada é publicado.
# ============================================================================================
def _ato_para_processar(a: "extractor.AtoIgam", url_documento: str) -> AtoParaProcessar:
    return AtoParaProcessar(
        processo_ou_portaria=a.processo_ou_portaria, titular=a.titular, trecho_decisorio=a.trecho_decisorio,
        municipio=a.municipio, data_decisao=discovery.data_iso(a.data_decisao or ""), finalidade_uso=a.finalidade_uso,
        url_documento=url_documento, texto_para_vinculo=a.texto_para_vinculo)


def documentos_ja_processados(sb, empresa_id: str) -> set:
    """URLs de documento que já geraram eventos para esta empresa (events.url_oficial). Não são baixados de novo."""
    r = (sb.table("events").select("url_oficial").eq("empresa_id", empresa_id)
         .like("url_oficial", "%/arquivos/ptp%").limit(20000).execute())
    return {x["url_oficial"] for x in (r.data or []) if x.get("url_oficial")}


def coletar(ambiente: str = "piloto", limite: int = None, reverificar: bool = False, sb=None, sessao_http=None,
            env=None, empresa_id: str = None, carteira_id: str = None) -> dict:
    import acesso
    import diagnostico
    import log_busca
    import rotas
    etapas = diagnostico.Etapas("M6")
    resumo = {"brutos": 0, "documentos_no_indice": 0, "documentos_lidos": 0, "documentos_sem_atos": 0,
              "documentos_ja_processados": 0, "erros": 0, "chamadas_ia": 0, "tokens_ia": 0, "custo_estimado_reais": 0.0}
    resultados, execucao_id, acessador, id_execucao = [], None, None, None

    def finalizar(status):
        resumo["diagnostico_etapas"] = etapas.registro
        resumo["barreiras_de_acesso"] = acessador.barreiras if acessador is not None else []
        if execucao_id:
            try:
                db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final=status)
            except Exception as e:
                print(f"[M6] aviso: não consegui finalizar a execução: {e}")
        etapas.gravar_resumo_job()

    try:
        with etapas.etapa("ambiente"):
            print("[M6] ambiente:", diagnostico.checar_ambiente(env))
        with etapas.etapa("conexao_supabase"):
            if sb is None:
                try:
                    sb = db_writer.get_client()
                except Exception as e:
                    dica = " (versão antiga do pacote 'supabase' recusa chaves sb_secret_; usar supabase>=2.15)" if "Invalid API key" in str(e) else ""
                    raise RuntimeError(f"{e}{dica}")
        with etapas.etapa("cadastro_de_fontes"):
            fonte = db_writer.buscar_fonte_id(sb, discovery.URL_INDICE, empresa_id=empresa_id, carteira_id=carteira_id)
            source_id, empresa_id, carteira_id = fonte["id"], fonte["empresa_id"], fonte["carteira_id"]
            print(f"[M6] escopo: empresa={empresa_id} carteira={carteira_id}")
            print("[M6] rota:", rotas.descricao_da_rota("M6"))
        with etapas.etapa("criar_execucao"):
            id_execucao = f"M6-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente, empresa_id=empresa_id, carteira_id=carteira_id)

        def sink(reg):
            reg["versao_rotas"] = rotas.VERSAO_ROTAS
            try:
                log_busca.gravar(sb, reg, execucao_id, source_id, empresa_id)
            except Exception as e:
                print(f"[M6] aviso: log_busca não gravado ({e})")

        acessador = acesso.Acessador("M6", source_id=source_id, sink=sink, session=sessao_http)

        with etapas.etapa("descoberta"):
            resp = acessador.get(discovery.URL_INDICE, metodo_acesso="m6_descoberta")
            print(f"[M6] índice: status={resp.status} mime={resp.content_type} bytes={len(resp.corpo)} url_final={resp.url_final}")
            indice = discovery.parse_indice(resp.texto, base_url=resp.url_final)
            resumo["documentos_no_indice"] = len(indice)
            if not indice:
                trecho = " ".join(resp.texto[:400].split())[:200]
                raise diagnostico.ErroEtapa("descoberta", "a página abriu mas nenhuma publicação (link + 'publicada(s) em') foi reconhecida",
                                            f"o layout do índice pode ter mudado. Início da página: {trecho!r}")
            print(f"[M6] {len(indice)} publicações no índice; a mais recente: {indice[0].nome_arquivo} ({indice[0].data_listada})")

        with etapas.etapa("selecao_de_documentos"):
            ja = set() if reverificar else documentos_ja_processados(sb, empresa_id)
            novos = [i for i in indice if i.url_documento not in ja]
            resumo["documentos_ja_processados"] = len(indice) - len(novos)
            a_ler = novos[:limite] if limite else novos
            print(f"[M6] {len(novos)} documentos ainda não processados; lendo {len(a_ler)} (mais recentes primeiro)")

        with etapas.etapa("processamento"):
            for doc in a_ler:
                try:
                    r = acessador.get(doc.url_documento, metodo_acesso="m6_documento")
                    texto = extractor.extrair_texto(r.corpo)
                    resumo["documentos_lidos"] += 1
                    atos = extractor.segmentar_documento(texto)
                    print(f"[M6] {doc.nome_arquivo}: formato={extractor.detectar_formato(r.corpo)} caracteres={len(texto)} atos={len(atos)}")
                    if not atos:
                        resumo["documentos_sem_atos"] += 1
                        resultados.append({"acao": "erro", "documento": doc.nome_arquivo,
                                           "erro": "documento convertido, mas nenhum ato foi reconhecido (layout novo?)"})
                        continue
                    for a in atos:
                        try:
                            res = processar_ato(sb, execucao_id, _ato_para_processar(a, doc.url_documento), empresa_id=empresa_id)
                        except Exception as e:
                            res = {"acao": "erro", "processo_ou_portaria": a.processo_ou_portaria, "erro": str(e)}
                        res["documento"] = doc.nome_arquivo
                        resultados.append(res)
                except Exception as e:
                    resultados.append({"acao": "erro", "documento": doc.nome_arquivo, "erro": str(e)})
                if acessador.barreiras and acessador.barreiras[-1]["status_http"] in (401, 403, 429):
                    print("[M6] barreira de acesso detectada; interrompendo a rodada sem contornar")
                    break

        with etapas.etapa("registro_final"):
            contagens = contagens_log_coleta(resultados, brutos=len(resultados), identicos=0)
            resumo["brutos"] = contagens["brutos"]
            resumo["erros"] = contagens["erros"]
            resumo.update({k: contagens[k] for k in ("novos", "atualizados", "descartados")})
            db_writer.registrar_log_coleta(sb, execucao_id, source_id, contagens, empresa_id=empresa_id)
        finalizar("concluída")
    except Exception as e:
        resumo["falha"] = str(e)
        finalizar("falha")
        print(f"[M6] FALHA: {e}")
        raise
    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M6 — Outorgas IGAM (sem IA)")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite", type=int, default=None, help="ler só os N documentos novos mais recentes (teste)")
    parser.add_argument("--reverificar", action="store_true", help="reabrir também os documentos já processados")
    parser.add_argument("--empresa-id", default=os.environ.get("RADAR_EMPRESA_ID"))
    parser.add_argument("--carteira-id", default=os.environ.get("RADAR_CARTEIRA_ID"))
    args = parser.parse_args()
    saida = coletar(ambiente=args.ambiente, limite=args.limite, reverificar=args.reverificar,
                    empresa_id=args.empresa_id, carteira_id=args.carteira_id)
    print(f"Execução {saida['id_execucao']}: {saida['resumo']}")
    for r in saida["resultados"]:
        print(" -", r)
    if saida["resumo"]["erros"] > 0:
        sys.exit(1)

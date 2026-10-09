"""
Módulo 9A — orquestrador do coletor (Carta M9A §16 ordem de implementação).
Pensado para rodar via GitHub Actions (ver .github/workflows/coletor_m9a.yml).

IMPORTANTE — leia antes de rodar contra a fonte real:
1. ingestao_scm.py (nomes de coluna do SCM) e signals.py (mapeamento
   evento_tipo -> sinais) NÃO foram validados contra um arquivo real do
   SCM (sandbox sem acesso de rede). scoring.py e consolidacao.py estão
   testados e corretos contra a lógica da carta.
2. Todo caso criado/atualizado entra com revisao_humana='Pendente' — nada
   é publicado automaticamente. estado_editorial em
   m9a_movimentacao_estado é um dos três estados da carta §9, nunca
   'Liberado para pré-release' automaticamente sem que
   empreendimento_confirmado passe por enriquecimento (que este coletor
   não faz sozinho — carta §8 é uma etapa separada, de enriquecimento
   obrigatório, não coberta neste primeiro pacote).
3. Rodar primeiro em ambiente='piloto' contra um recorte pequeno (ex.: só
   os 5 casos de controle, se a Rapha conseguir isolar essas linhas no
   arquivo real) antes de apontar para produção de verdade.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))

import diagnostico
import log_busca
import pre_ia
import rotas
import ingestao_scm
import consolidacao
import signals
import scoring
import checklist_editorial
import db_writer


def gerar_id_evento(chave_caso: str) -> str:
    return f"anm-m9a-{chave_caso[:16]}"


def processar_caso(sb, execucao_id: str, atos: list, empresa_id=None, fonte_id=None,
                    universo_atos: Optional[list] = None) -> dict:
    t0 = time.monotonic()
    primeiro = atos[0]
    contagem_municipios = len({a.municipio for a in atos if a.municipio})

    # sinais agregados do caso: OR entre os atos (se qualquer ato do caso
    # dispara um sinal, o caso todo carrega esse sinal — ex.: um dos dois
    # processos Kinross ter 'dimensao_objetiva' vale para o caso inteiro)
    sig_agregado = scoring.SignaisM9A()
    # Uma lista de evidências POR ato (não uma lista achatada única) —
    # achado/correção de 28/09/2026: quando um caso agrupa mais de um ato
    # (ex.: emissão 2023 + prorrogação 2026 da mesma guia, ver regra 4b em
    # consolidacao.py), cada marco de timeline precisa apontar para a
    # evidência DO SEU PRÓPRIO ato, não para uma evidência genérica do
    # primeiro ato do caso — senão o ato histórico (2023) ficaria só com o
    # trecho_literal do ato central (2026) como "prova", o que seria
    # fundir os fatos, exatamente o que não queríamos.
    evidencias_por_ato = []
    for ato in atos:
        # ACHADO/correção de 28/09/2026: `evento_tipo` (narrativa livre,
        # OBEvento/DSPublicacaoDOU) só entra aqui como evidência/trecho
        # literal. Classificação (signals.py) usa `descricao_tipo_evento`
        # (nome do dicionário Evento.txt = ato.descricao, desde a correção
        # em consolidacao.py) + `id_tipo_evento` — nunca a narrativa. Ver
        # classificacao_scm.py.
        linha = {
            "processo": ato.processo,
            "evento_tipo": ato.texto_narrativo or ato.descricao,
            "descricao_tipo_evento": ato.descricao,
            "id_tipo_evento": ato.id_tipo_evento,
            "substancia": ato.substancia,
            "titular": ato.empresa,
            "municipio": ato.municipio,
            "data_evento": ato.data_evento,
            "area_ha": ato.area_ha,
        }
        sig_ato = signals.extrair_signais_m9a(linha, contagem_municipios_processo=contagem_municipios)
        for campo in sig_agregado.__dataclass_fields__:
            if getattr(sig_ato, campo):
                setattr(sig_agregado, campo, True)
        evidencias_por_ato.append(signals.extrair_evidencias_campo(linha))
    evidencias_caso = [ev for grupo in evidencias_por_ato for ev in grupo]

    score, faixa, justificativa = scoring.score_m9a(sig_agregado)
    prioridade = faixa  # já é A/B/C/D

    chave_caso = consolidacao.chave_caso_editorial(primeiro)
    id_evento = gerar_id_evento(chave_caso)

    # "movimentacao_scm_anm" é um tipo_evento genérico do módulo — ver
    # docstring de buscar_regra_evento em db_writer.py sobre por que não
    # há um valor único natural por ato aqui ainda.
    regra = db_writer.buscar_regra_evento(sb, fonte_id, "movimentacao_scm_anm") if fonte_id else None

    processos_envolvidos = sorted({a.processo for a in atos})
    campos_evento = {
        "processo": "; ".join(processos_envolvidos),
        "titulo_fato": primeiro.texto_narrativo or primeiro.descricao,
        "empresa": primeiro.empresa,
        "municipio": "; ".join(sorted({a.municipio for a in atos if a.municipio})),
        "status_editorial": "em_apuracao",
        "revisao_humana": "Pendente",
        "tipo_evento": "movimentacao_scm_anm",
    }

    event_id, criado = db_writer.upsert_caso_editorial(sb, id_evento, campos_evento, execucao_id,
                                                         empresa_id=empresa_id)

    # Checklist Completo de Enriquecimento — evidências por campo (achado
    # de 28/09/2026: passam a usar campo_sustentado e retornar os ids
    # gravados, para linkar evidencia_id específica na timeline e no
    # checklist, mesma extensão feita no M8).
    evidencias_gravadas = db_writer.gravar_evidencias_caso(sb, event_id, evidencias_caso, empresa_id=empresa_id)
    evidencia_padrao_id = evidencias_gravadas[0]["id"] if evidencias_gravadas else None

    # Reconstituir, por ato, o id da evidência de 'evento_tipo' (narrativa)
    # que pertence especificamente a ELE — gravar_evidencias_caso devolve
    # na mesma ordem em que evidencias_caso foi montado (achatamento de
    # evidencias_por_ato), então dá para recortar por offset.
    evidencia_id_por_ato = []
    _offset = 0
    for grupo in evidencias_por_ato:
        fatia = evidencias_gravadas[_offset:_offset + len(grupo)]
        _offset += len(grupo)
        ev_evento_tipo = next((e["id"] for e in fatia if e["campo"] == "evento_tipo"), None)
        evidencia_id_por_ato.append(ev_evento_tipo or evidencia_padrao_id)

    for ato, evidencia_id_ato in zip(atos, evidencia_id_por_ato):
        tipo_marco = db_writer.mapear_tipo_marco(ato.descricao, ato.id_tipo_evento)
        db_writer.gravar_ato_na_timeline(
            sb, event_id, tipo_marco=tipo_marco, data_marco=ato.data_evento,
            trecho_literal=ato.texto_narrativo or ato.descricao,
            evidencia_id=evidencia_id_ato, empresa_id=empresa_id,
        )

    # Carta §9: por padrão o caso fica travado para documento até
    # enriquecimento confirmar empreendimento/vínculo geográfico — este
    # coletor não faz o enriquecimento (etapa separada, carta §8), então
    # o estado inicial conservador é sempre 'Travado para documento',
    # nunca 'Liberado para pré-release' automaticamente.
    efeito_operacional = None  # carta §10 — só vira comprovado/não comprovado no enriquecimento §8
    db_writer.upsert_m9a_estado(sb, event_id, familia_chave=chave_caso, estado={
        "estado_editorial": "Travado para documento",
        "efeito_operacional": efeito_operacional,
        "pendencia_apuracao": "Enriquecimento obrigatório da carta §8 ainda não executado por este coletor.",
        "versao_regra_score": scoring.VERSAO_REGRA_SCORE,
    })

    memoria = scoring.montar_memoria_calculo(sig_agregado, justificativa)
    db_writer.gravar_score(
        sb, event_id, score_bruto=score, prioridade=prioridade,
        componentes={"score_m9a": score, "faixa": faixa, "justificativa": justificativa,
                     "processos": processos_envolvidos},
        empresa_id=empresa_id,
        score_normalizado=scoring.calcular_score_normalizado(score),
        regra_evento_id=regra["id"] if regra else None,
        regra_evento_versao=regra["versao"] if regra else None,
        gatilhos_aplicados=memoria["gatilhos_aplicados"],
        redutores_aplicados=memoria["redutores_aplicados"],
        piso_aplicado=memoria["piso_aplicado"],
        teto_aplicado=memoria["teto_aplicado"],
    )

    # Pergunta 11 do checklist ('histórico relevante') — achado/correção de
    # 28/09/2026: busca em DUAS camadas, não só na tabela `events` (que só
    # tem o que já foi processado e publicado antes). Registrada com
    # critério distinto por camada, para o `eventos_relacionados` deixar
    # claro qual busca achou o quê.
    antecedentes_editorial = db_writer.buscar_antecedentes_m9a(sb, id_evento, titular=primeiro.empresa)
    if antecedentes_editorial:
        db_writer.gravar_eventos_relacionados(sb, event_id, antecedentes_editorial,
                                               criterio_vinculo="mesma_empresa_editorial", empresa_id=empresa_id)

    processos_antecedentes_universo = []
    if universo_atos:
        processos_antecedentes_universo = consolidacao.buscar_processos_por_titular_no_universo(
            universo_atos, titular=primeiro.empresa, processo_atual=primeiro.processo,
        )
        # gravar_eventos_relacionados espera IDs de `events`, e um processo
        # do universo pode ainda não ter virado evento — aqui só contamos
        # para o checklist (teve_antecedentes) e deixamos registrado; ligar
        # em eventos_relacionados só é possível para os que já têm event_id.
    antecedentes = antecedentes_editorial or processos_antecedentes_universo

    respostas = checklist_editorial.derivar_checklist_m9a(
        titular=primeiro.empresa, municipio=primeiro.municipio, data_evento=primeiro.data_evento,
        descricao=primeiro.descricao, efeito_operacional=efeito_operacional,
        quantidade_processos_no_caso=len(processos_envolvidos), teve_antecedentes=bool(antecedentes),
    )
    respostas_finais = db_writer.gravar_checklist_editorial(
        sb, event_id, respostas, prioridade=prioridade, empresa_id=empresa_id,
        evidencia_padrao_id=evidencia_padrao_id,
    )

    grau = checklist_editorial.calcular_grau_completude(respostas)
    db_writer.upsert_caso_editorial(sb, id_evento, {"grau_completude": grau}, execucao_id, empresa_id=empresa_id)

    hash_entrada = consolidacao.chave_caso_editorial(primeiro)  # muda só quando o caso muda de identidade
    db_writer.gravar_job_enriquecimento(
        sb, event_id, hash_entrada=hash_entrada, status="concluido",
        tempo_gasto_segundos=time.monotonic() - t0, empresa_id=empresa_id,
    )

    return {"id_evento": id_evento, "processos": processos_envolvidos, "score": score,
            "faixa": faixa, "criado": criado, "grau_completude": grau,
            "checklist_respostas_finais": respostas_finais}


def _flags_caso(atos_do_caso, processo_ja_conhecido: bool = False) -> dict:
    """Pré-IA do M9A: a classificação por dicionário (classificacao_scm) já decide sem IA. Aqui só se marca
    o que SERIA dispensado de qualquer chamada futura: ato genérico/não material sem delta."""
    import classificacao_scm as clsf
    from signals import EVENTOS_MUDANCA_MATERIAL, EVENTOS_AUTORIZACAO_EXTRACAO, EVENTOS_AVANCO_PESQUISA_APROVADO
    material = False
    for a in atos_do_caso:
        t = clsf.classificar(a.id_tipo_evento, a.descricao)
        if t.contem(*EVENTOS_MUDANCA_MATERIAL, *EVENTOS_AUTORIZACAO_EXTRACAO, *EVENTOS_AVANCO_PESQUISA_APROVADO):
            material = True
            break
    return pre_ia.flags_m9a(ato_generico_nao_material=not material, ja_enriquecido=processo_ja_conhecido)


def run(caminho_microdados: str, ambiente: str = "piloto", limite_casos: int = None,
        max_linhas_evento: int = None, tamanho_bloco: int = 500_000, registro_download: dict = None,
        sb=None, env=None, empresa_id: str = None, carteira_id: str = None):
    etapas = diagnostico.Etapas("M9A")
    contador = pre_ia.ContadorPreIa()
    resumo = {"brutos": 0, "dentro_recorte": 0, "casos_consolidados": 0,
              "novos": 0, "atualizados": 0, "erros": 0,
              "chamadas_ia": 0, "tokens_ia": 0, "custo_estimado_reais": 0.0}
    resultados = []
    execucao_id = None

    def finalizar(status):
        resumo.update(contador.resumo())
        resumo["diagnostico_etapas"] = etapas.registro
        if execucao_id:
            try:
                db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final=status)
            except Exception as e:
                print(f"[M9A] aviso: não consegui finalizar a execução: {e}")
        etapas.gravar_resumo_job()

    try:
        with etapas.etapa("ambiente"):
            print("[M9A] ambiente:", diagnostico.checar_ambiente(env))
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
            print(f"[M9A] escopo: empresa={empresa_id} carteira={carteira_id}")
            print("[M9A] rota:", rotas.descricao_da_rota("M9A"))
        with etapas.etapa("criar_execucao"):
            id_execucao = f"M9A-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente, empresa_id=empresa_id, carteira_id=carteira_id)
        if registro_download:
            registro_download["versao_rotas"] = rotas.VERSAO_ROTAS
            try:
                log_busca.gravar(sb, registro_download, execucao_id, source_id, empresa_id)
            except Exception as e:
                print(f"[M9A] aviso: log_busca do download não gravado ({e})")

        with etapas.etapa("leitura_em_blocos_e_recorte"):
            df_recorte, est = ingestao_scm.carregar_recorte_m9a_em_blocos(
                caminho_microdados, tamanho_bloco=tamanho_bloco, max_linhas_evento=max_linhas_evento)
            resumo["brutos"], resumo["dentro_recorte"] = est["brutos"], est["dentro_recorte"]
            resumo["ingestao"] = est
            print(f"[M9A] eventos lidos={est['brutos']} fora de MG={est['fora_de_mg']} "
                  f"família fora do escopo={est['fora_por_familia']} no recorte={est['dentro_recorte']}"
                  + (" (AMOSTRA)" if est["amostra"] else ""))

        with etapas.etapa("consolidacao"):
            # ACHADO/correção de 28/09/2026: `descricao` vem de `descricao_tipo_evento` (DSEvento) e a
            # narrativa vira `texto_narrativo` (só evidência). `row.get` porque colunas opcionais podem faltar.
            atos = [
                consolidacao.Ato(
                    processo=row["processo"], descricao=row.get("descricao_tipo_evento") or row["evento_tipo"],
                    data_evento=row["data_evento"], empresa=row.get("titular"),
                    substancia=row.get("substancia"), municipio=row.get("municipio"),
                    id_tipo_evento=row.get("id_tipo_evento"),
                    texto_narrativo=row.get("evento_tipo"),
                    area_ha=row.get("area_ha"),
                )
                for _, row in df_recorte.iterrows()
            ]
            casos = consolidacao.consolidar_atos(atos)
            resumo["casos_consolidados"] = len(casos)
            itens = list(casos.values())
            if limite_casos:
                itens = itens[:limite_casos]

        with etapas.etapa("processamento"):
            for atos_do_caso in itens:
                contador.registrar(_flags_caso(atos_do_caso))
                try:
                    r = processar_caso(sb, execucao_id, atos_do_caso, empresa_id=empresa_id, fonte_id=source_id,
                                        universo_atos=atos)
                    resultados.append(r)
                    resumo["novos" if r.get("criado") else "atualizados"] += 1
                except Exception as e:
                    resumo["erros"] += 1
                    resultados.append({"erro": str(e)})

        with etapas.etapa("registro_final"):
            db_writer.registrar_log_coleta(sb, execucao_id, source_id, {
                "brutos": resumo["brutos"], "filtrados": resumo["dentro_recorte"],
                "analisados": resumo["casos_consolidados"], "novos": resumo["novos"],
                "atualizados": resumo["atualizados"], "erros": resumo["erros"],
            }, empresa_id=empresa_id)
        finalizar("concluída")

    except Exception as e:
        resumo["falha"] = str(e)
        finalizar("falha")
        print(f"[M9A] FALHA: {e}")
        raise

    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M9A — Movimentações ANM")
    parser.add_argument("--microdados", required=True,
                         help="diretório com os .txt do dump relacional do SCM já descompactado "
                              "(Processo.txt, ProcessoEvento.txt, Evento.txt etc. — ver ingestao_scm.py)")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite-casos", type=int, default=None)
    parser.add_argument("--max-linhas-evento", type=int, default=None,
                         help="modo amostra: lê só as N primeiras linhas de ProcessoEvento.txt (primeiro teste pequeno)")
    parser.add_argument("--tamanho-bloco", type=int, default=500_000)
    parser.add_argument("--registro-download", default=None, help="JSON do baixar_scm.py (vai para o log_busca)")
    parser.add_argument("--empresa-id", default=os.environ.get("RADAR_EMPRESA_ID"), help="empresa dona desta coleta (obrigatório se a fonte existir em mais de uma)")
    parser.add_argument("--carteira-id", default=os.environ.get("RADAR_CARTEIRA_ID"), help="carteira da empresa (padrão: a única que usa a fonte)")
    args = parser.parse_args()

    reg = None
    if args.registro_download and os.path.exists(args.registro_download):
        with open(args.registro_download) as f:
            reg = json.load(f)
    resultado = run(args.microdados, ambiente=args.ambiente, limite_casos=args.limite_casos,
                    max_linhas_evento=args.max_linhas_evento, tamanho_bloco=args.tamanho_bloco, registro_download=reg,
                    empresa_id=args.empresa_id, carteira_id=args.carteira_id)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

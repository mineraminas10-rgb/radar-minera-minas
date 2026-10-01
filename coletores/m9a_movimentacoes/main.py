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
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

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


def run(caminho_microdados: str, ambiente: str = "piloto", limite_casos: int = None):
    sb = db_writer.get_client()
    fonte = db_writer.buscar_fonte(sb)
    source_id, empresa_id = fonte["id"], fonte.get("empresa_id")
    id_execucao = f"M9A-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente, empresa_id=empresa_id)

    resumo = {"brutos": 0, "dentro_recorte": 0, "casos_consolidados": 0,
              "novos": 0, "atualizados": 0, "erros": 0,
              "chamadas_ia": 0, "tokens_ia": 0, "custo_estimado_reais": 0.0}
    resultados = []

    try:
        df = ingestao_scm.carregar_microdados_scm(caminho_microdados)
        resumo["brutos"] = len(df)

        df_recorte = ingestao_scm.aplicar_recorte_m9a(df)
        resumo["dentro_recorte"] = len(df_recorte)

        # ACHADO/correção de 28/09/2026: `descricao` passa a vir de
        # `descricao_tipo_evento` (DSEvento, dicionário Evento.txt — nome
        # ESTÁVEL do tipo de evento) em vez de `evento_tipo` (narrativa
        # livre) — ver classificacao_scm.py e consolidacao.py. A narrativa
        # vira `texto_narrativo` (só para evidência/instrumento). `row.get`
        # (não `row[...]`) para os campos novos porque `ingestao_scm.py`
        # ainda não foi validado contra uma amostra real de arquivo (ver
        # aviso lá) — não travar a ingestão inteira se alguma dessas
        # colunas específicas não vier.
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

        for atos_do_caso in itens:
            try:
                r = processar_caso(sb, execucao_id, atos_do_caso, empresa_id=empresa_id, fonte_id=source_id,
                                    universo_atos=atos)
                resultados.append(r)
                resumo["novos" if r.get("criado") else "atualizados"] += 1
            except Exception as e:
                resumo["erros"] += 1
                resultados.append({"erro": str(e)})

        db_writer.registrar_log_coleta(sb, execucao_id, source_id, {
            "brutos": resumo["brutos"], "filtrados": resumo["dentro_recorte"],
            "analisados": resumo["casos_consolidados"], "novos": resumo["novos"],
            "atualizados": resumo["atualizados"], "erros": resumo["erros"],
        }, empresa_id=empresa_id)
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="concluída")

    except Exception:
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="falha")
        raise

    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M9A — Movimentações ANM")
    parser.add_argument("--microdados", required=True,
                         help="diretório com os .txt do dump relacional do SCM já descompactado "
                              "(Processo.txt, ProcessoEvento.txt, Evento.txt etc. — ver ingestao_scm.py)")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite-casos", type=int, default=None)
    args = parser.parse_args()

    resultado = run(args.microdados, ambiente=args.ambiente, limite_casos=args.limite_casos)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

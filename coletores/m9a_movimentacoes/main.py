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

import ingestao_scm
import consolidacao
import signals
import scoring
import checklist_editorial
import db_writer


def gerar_id_evento(chave_caso: str) -> str:
    return f"anm-m9a-{chave_caso[:16]}"


def processar_caso(sb, execucao_id: str, atos: list) -> dict:
    t0 = time.monotonic()
    primeiro = atos[0]
    contagem_municipios = len({a.municipio for a in atos if a.municipio})

    # sinais agregados do caso: OR entre os atos (se qualquer ato do caso
    # dispara um sinal, o caso todo carrega esse sinal — ex.: um dos dois
    # processos Kinross ter 'dimensao_objetiva' vale para o caso inteiro)
    sig_agregado = scoring.SignaisM9A()
    evidencias_caso = []
    for ato in atos:
        linha = {"processo": ato.processo, "evento_tipo": ato.descricao, "substancia": ato.substancia,
                  "titular": ato.empresa, "municipio": ato.municipio, "data_evento": ato.data_evento}
        sig_ato = signals.extrair_signais_m9a(linha, contagem_municipios_processo=contagem_municipios)
        for campo in sig_agregado.__dataclass_fields__:
            if getattr(sig_ato, campo):
                setattr(sig_agregado, campo, True)
        evidencias_caso += signals.extrair_evidencias_campo(linha)

    score, faixa, justificativa = scoring.score_m9a(sig_agregado)
    prioridade = faixa  # já é A/B/C/D

    chave_caso = consolidacao.chave_caso_editorial(primeiro)
    id_evento = gerar_id_evento(chave_caso)

    processos_envolvidos = sorted({a.processo for a in atos})
    campos_evento = {
        "processo": "; ".join(processos_envolvidos),
        "titulo_fato": atos[0].descricao,
        "empresa": primeiro.empresa,
        "municipio": "; ".join(sorted({a.municipio for a in atos if a.municipio})),
        "status_editorial": "em_apuracao",
        "revisao_humana": "Pendente",
    }

    event_id, criado = db_writer.upsert_caso_editorial(sb, id_evento, campos_evento, execucao_id)

    for ato in atos:
        db_writer.gravar_ato_na_timeline(sb, event_id, tipo_marco=ato.descricao, data_marco=ato.data_evento)

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

    db_writer.gravar_score(sb, event_id, score_bruto=score, prioridade=prioridade,
                            componentes={"score_m9a": score, "faixa": faixa, "justificativa": justificativa,
                                         "processos": processos_envolvidos})

    # Checklist Completo de Enriquecimento — evidências por campo,
    # checklist editorial de 12 perguntas, eventos relacionados e job de
    # enriquecimento (ver db_writer.py e checklist_editorial.py, mesma
    # extensão feita no M8).
    db_writer.gravar_evidencias_caso(sb, event_id, evidencias_caso)

    antecedentes = db_writer.buscar_antecedentes_m9a(sb, id_evento, titular=primeiro.empresa)
    if antecedentes:
        db_writer.gravar_eventos_relacionados(sb, event_id, antecedentes)

    respostas = checklist_editorial.derivar_checklist_m9a(
        titular=primeiro.empresa, municipio=primeiro.municipio, data_evento=primeiro.data_evento,
        descricao=primeiro.descricao, efeito_operacional=efeito_operacional,
        quantidade_processos_no_caso=len(processos_envolvidos), teve_antecedentes=bool(antecedentes),
    )
    db_writer.gravar_checklist_editorial(sb, event_id, respostas, prioridade=prioridade)

    hash_entrada = consolidacao.chave_caso_editorial(primeiro)  # muda só quando o caso muda de identidade
    db_writer.gravar_job_enriquecimento(
        sb, event_id, hash_entrada=hash_entrada, status="concluido",
        tempo_gasto_segundos=time.monotonic() - t0,
    )

    return {"id_evento": id_evento, "processos": processos_envolvidos, "score": score,
            "faixa": faixa, "criado": criado}


def run(caminho_microdados: str, ambiente: str = "piloto", limite_casos: int = None):
    sb = db_writer.get_client()
    source_id = db_writer.buscar_fonte_id(sb)
    id_execucao = f"M9A-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    execucao_id = db_writer.criar_execucao(sb, id_execucao, ambiente=ambiente)

    resumo = {"brutos": 0, "dentro_recorte": 0, "casos_consolidados": 0,
              "novos": 0, "atualizados": 0, "erros": 0}
    resultados = []

    try:
        df = ingestao_scm.carregar_microdados_scm(caminho_microdados)
        resumo["brutos"] = len(df)

        df_recorte = ingestao_scm.aplicar_recorte_m9a(df)
        resumo["dentro_recorte"] = len(df_recorte)

        atos = [
            consolidacao.Ato(
                processo=row["processo"], descricao=row["evento_tipo"],
                data_evento=row["data_evento"], empresa=row.get("titular"),
                substancia=row.get("substancia"), municipio=row.get("municipio"),
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
                r = processar_caso(sb, execucao_id, atos_do_caso)
                resultados.append(r)
                resumo["novos" if r.get("criado") else "atualizados"] += 1
            except Exception as e:
                resumo["erros"] += 1
                resultados.append({"erro": str(e)})

        db_writer.registrar_log_coleta(sb, execucao_id, source_id, {
            "brutos": resumo["brutos"], "filtrados": resumo["dentro_recorte"],
            "analisados": resumo["casos_consolidados"], "novos": resumo["novos"],
            "atualizados": resumo["atualizados"], "erros": resumo["erros"],
        })
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="concluída")

    except Exception:
        db_writer.finalizar_execucao(sb, execucao_id, totais=resumo, status_final="falha")
        raise

    return {"id_execucao": id_execucao, "resumo": resumo, "resultados": resultados}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor M9A — Movimentações ANM")
    parser.add_argument("--microdados", required=True, help="caminho do arquivo de microdados SCM baixado")
    parser.add_argument("--ambiente", default="piloto", choices=["piloto", "homologacao", "producao"])
    parser.add_argument("--limite-casos", type=int, default=None)
    args = parser.parse_args()

    resultado = run(args.microdados, ambiente=args.ambiente, limite_casos=args.limite_casos)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

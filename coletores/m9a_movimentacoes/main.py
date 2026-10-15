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
import criticidade as crit_mod
import criticidade_db
import criticidade_caso
import recalcular_criticidade
from datetime import date


def gerar_id_evento(chave_caso: str) -> str:
    return f"anm-m9a-{chave_caso[:16]}"


def processar_caso(sb, execucao_id: str, atos: list, empresa_id=None, fonte_id=None,
                    universo_atos: Optional[list] = None, crit=None) -> dict:
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
    # Régua de criticidade CRIT-V1.0: NOVA versão de score (a linha legada acima NÃO é apagada; só deixa de
    # ser a vigente). A prioridade A-D passa a ser derivada da criticidade.
    crit_gravacao = None
    if crit is not None:
        crit_gravacao = criticidade_db.gravar_criticidade(sb, event_id, crit, empresa_id=empresa_id)
        prioridade = crit.prioridade or prioridade

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
            "criticidade": crit.nivel if crit is not None else None, "criticidade_gravacao": crit_gravacao,
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


def _limpo(v):
    """Valor de célula do SCM -> None quando ausente (NaN/NA/None/vazio/'nan'); senão o próprio valor."""
    try:
        import pandas as pd
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str) and v.strip().lower() in ("", "nan", "none", "<na>"):
        return None
    return v


def run(caminho_microdados: str, ambiente: str = "piloto", limite_casos: int = None,
        max_linhas_evento: int = None, tamanho_bloco: int = 500_000, registro_download: dict = None,
        sb=None, env=None, empresa_id: str = None, carteira_id: str = None,
        janela_dias: Optional[int] = None, piso_criticidade: Optional[str] = "PADRAO", hoje: Optional[date] = None,
        parametros: Optional[dict] = None, recalcular_pendentes: bool = True, somente_existentes: bool = False):
    """janela_dias: None = parâmetro versionado (m9a.janela_leitura_dias); 0 = sem filtro de data.
    piso_criticidade: 'PADRAO' = piso_selecao dos parâmetros (MEDIA); um nível ('ROTINA', 'BAIXA'...) = aceita esse
    nível ou acima; None = não aplica régua nenhuma (comportamento legado, sem gravar CRIT).
    recalcular_pendentes: ao final, reclassifica deterministicamente (mesma régua, sem IA) os M9A provisórios/pendentes
    de evidência cujo tipo oficial/evidência estruturada já entrou; os que passam migram sozinhos para SELECIONAVEL_AGORA.
    somente_existentes: só atualiza casos que JÁ existem no banco (mesma chave id_evento); caso novo é ignorado e
    contado em `ignorados_por_nao_existirem`. Nenhum evento é criado nesse modo."""
    par = parametros or crit_mod.carregar_parametros()
    referencia = hoje or date.today()
    if somente_existentes:
        # Atualizar o que já existe NÃO depende da idade nem da criticidade de hoje: sem janela de data e sem piso
        # (a leitura é limitada aos processos dos casos existentes, então continua rápida). Valores explícitos valem.
        if janela_dias is None:
            janela_dias = 0
        if piso_criticidade == "PADRAO":
            piso_criticidade = "ROTINA"
    aplica_regua = piso_criticidade is not None
    if piso_criticidade == "PADRAO":
        niveis_aceitos = set(par["piso_selecao"])
    elif piso_criticidade:
        niveis_aceitos = set(par["niveis"][par["niveis"].index(piso_criticidade):])
    else:
        niveis_aceitos = set(par["niveis"])
    etapas = diagnostico.Etapas("M9A")
    contador = pre_ia.ContadorPreIa()
    resumo = {"brutos": 0, "dentro_recorte": 0, "casos_consolidados": 0,
              "novos": 0, "atualizados": 0, "erros": 0,
              "chamadas_ia": 0, "tokens_ia": 0, "custo_estimado_reais": 0.0,
              "versao_regra_criticidade": par["versao_regra"] if aplica_regua else None,
              "versao_parametros_criticidade": par["versao_parametros"] if aplica_regua else None,
              "criticidade_dos_casos": {}, "dispensados_por_criticidade": {}}
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
            data_minima = criticidade_caso.janela_data_minima(par, referencia, janela_dias) if aplica_regua else None
            processos_permitidos = None
            if somente_existentes:
                processos_permitidos = db_writer.listar_processos_eventos_m9a(sb, empresa_id)
                resumo["processos_dos_existentes"] = len(processos_permitidos)
                print(f"[M9A] somente existentes: lendo só {len(processos_permitidos)} processo(s) dos casos já no banco "
                      f"(janela de data: {data_minima or 'sem filtro'})")
            df_recorte, est = ingestao_scm.carregar_recorte_m9a_em_blocos(
                caminho_microdados, tamanho_bloco=tamanho_bloco, max_linhas_evento=max_linhas_evento,
                data_minima=data_minima, processos_permitidos=processos_permitidos)
            resumo["brutos"], resumo["dentro_recorte"] = est["brutos"], est["dentro_recorte"]
            resumo["ingestao"] = est
            print(f"[M9A] eventos lidos={est['brutos']} fora da janela de data (>= {data_minima})={est.get('fora_por_data', 0)} fora de MG={est['fora_de_mg']} "
                  f"família fora do escopo={est['fora_por_familia']} no recorte={est['dentro_recorte']}"
                  + (" (AMOSTRA)" if est["amostra"] else ""))

        with etapas.etapa("consolidacao"):
            # ACHADO/correção de 28/09/2026: `descricao` vem de `descricao_tipo_evento` (DSEvento) e a
            # narrativa vira `texto_narrativo` (só evidência). `row.get` porque colunas opcionais podem faltar.
            atos, descartados = [], 0
            for _, row in df_recorte.iterrows():
                processo, data_evento = _limpo(row.get("processo")), _limpo(row.get("data_evento"))
                if not processo or not data_evento:     # sem processo/data não há como identificar o ato
                    descartados += 1
                    continue
                atos.append(consolidacao.Ato(
                    processo=processo,
                    # Valor ausente no SCM chega do pandas como NaN (float, e NaN é "verdadeiro" em Python):
                    # `nan or x` devolvia NaN e quebrava a normalização de texto. `_limpo` troca por None.
                    descricao=_limpo(row.get("descricao_tipo_evento")) or _limpo(row.get("evento_tipo")) or "",
                    data_evento=data_evento, empresa=_limpo(row.get("titular")),
                    substancia=_limpo(row.get("substancia")), municipio=_limpo(row.get("municipio")),
                    id_tipo_evento=_limpo(row.get("id_tipo_evento")),
                    texto_narrativo=_limpo(row.get("evento_tipo")),
                    area_ha=_limpo(row.get("area_ha")),
                ))
            resumo["atos_descartados_sem_chave"] = descartados
            casos = consolidacao.consolidar_atos(atos)
            resumo["casos_consolidados"] = len(casos)
            itens = list(casos.values())
            crits = {}
            if aplica_regua:
                # Ordem determinística ANTES do limite: criticidade (maior primeiro) > ato mais recente >
                # primeira chave do caso (estável). Sem isso, --limite-casos pegaria os casos na ordem do arquivo.
                for i, a_caso in enumerate(itens):
                    crits[i] = criticidade_caso.criticidade_do_caso(a_caso, par, referencia)
                ordem = sorted(range(len(itens)), key=lambda i: (
                    -(par["niveis"].index(crits[i].nivel) if crits[i].nivel in par["niveis"] else -1), -crits[i].pontuacao,
                    (crits[i].idade_dias if crits[i].idade_dias is not None else 10 ** 9),
                    consolidacao.chave_caso_editorial(itens[i][0])))
                itens_ord, crits_ord = [itens[i] for i in ordem], [crits[i] for i in ordem]
                dist, dispensados, aceitos, aceitos_crit = {}, {}, [], []
                for a_caso, c in zip(itens_ord, crits_ord):
                    dist[c.nivel] = dist.get(c.nivel, 0) + 1
                    if c.nivel in niveis_aceitos:
                        aceitos.append(a_caso)
                        aceitos_crit.append(c)
                    else:
                        dispensados[c.nivel] = dispensados.get(c.nivel, 0) + 1
                resumo["criticidade_dos_casos"], resumo["dispensados_por_criticidade"] = dist, dispensados
                itens, crits_lista = aceitos, aceitos_crit
                print(f"[M9A] criticidade dos casos consolidados={dist} dispensados abaixo do piso={dispensados}")
            else:
                crits_lista = [None] * len(itens)
            if somente_existentes:
                existentes = db_writer.listar_ids_evento_m9a(sb, empresa_id)
                ids_casos = [gerar_id_evento(consolidacao.chave_caso_editorial(a_caso[0])) for a_caso in itens]
                resumo["existentes_no_banco"] = len(existentes)
                try:    # diagnóstico: para 4 eventos antigos, mostra os atos de hoje do MESMO processo e a chave que cada um gera
                    amostra = db_writer.amostra_processos_eventos_m9a(sb, empresa_id, sorted(existentes)[:4])
                    for id_antigo, procs in amostra.items():
                        for proc in procs[:1]:
                            do_proc = [a for a in atos if a.processo == proc][:3]
                            print(f"[M9A] diag evento antigo {id_antigo} processo={proc}: {len(do_proc)} ato(s) de hoje (até 3)")
                            for a in do_proc:
                                print(f"[M9A]   ato: desc={a.descricao[:60]!r} data={a.data_evento!r} empresa={a.empresa!r} "
                                      f"subst={a.substancia!r} mun={a.municipio!r} chave_hoje={consolidacao.chave_caso_editorial(a)[:16]}")
                except Exception as exc:    # diagnóstico nunca derruba a coleta
                    print(f"[M9A] diag evento antigo: falhou ({type(exc).__name__}: {exc})")
                resumo["existentes_com_id_atual"] = len(existentes & set(ids_casos))
                print(f"[M9A] diagnóstico: empresa={empresa_id}; eventos M9A listados no banco={len(existentes)}; "
                      f"exemplos no banco={sorted(existentes)[:3]}; exemplos de id gerado={ids_casos[:3]}")
                manter = [i for i, a_caso in enumerate(itens)
                          if gerar_id_evento(consolidacao.chave_caso_editorial(a_caso[0])) in existentes]
                resumo["ignorados_por_nao_existirem"] = len(itens) - len(manter)
                itens, crits_lista = [itens[i] for i in manter], [crits_lista[i] for i in manter]
                print(f"[M9A] somente existentes: {len(manter)} casos já no banco serão atualizados; "
                      f"{resumo['ignorados_por_nao_existirem']} casos novos ignorados (nenhum evento será criado)")
            if limite_casos:
                itens, crits_lista = itens[:limite_casos], crits_lista[:limite_casos]

        with etapas.etapa("processamento"):
            for atos_do_caso, crit_caso in zip(itens, crits_lista):
                contador.registrar(_flags_caso(atos_do_caso))
                try:
                    r = processar_caso(sb, execucao_id, atos_do_caso, empresa_id=empresa_id, fonte_id=source_id,
                                        universo_atos=atos, crit=crit_caso)
                    resultados.append(r)
                    resumo["novos" if r.get("criado") else "atualizados"] += 1
                except Exception as e:
                    resumo["erros"] += 1
                    resultados.append({"erro": str(e)})

        if aplica_regua and recalcular_pendentes and sb is not None:
            with etapas.etapa("recalculo_pendentes"):
                try:
                    rec = recalcular_criticidade.recalcular_pendentes(sb, par, referencia)
                    resumo["recalculo_pendentes"] = {k: rec[k] for k in ("examinados", "gravados", "inalterados", "erros")}
                    resumo["recalculo_pendentes"]["mudancas"] = rec.get("mudancas", [])
                except Exception as e:  # o recálculo nunca derruba a coleta; o erro fica visível no resumo
                    resumo["recalculo_pendentes"] = {"erro": str(e)}
                    print(f"[M9A] recálculo de pendentes não executado: {e}")

        with etapas.etapa("registro_final"):
            db_writer.registrar_log_coleta(sb, execucao_id, source_id, {
                "brutos": resumo["brutos"], "filtrados": resumo["dentro_recorte"],
                # Regra do banco (chk_analisados_soma): analisados = identicos + atualizados + novos + duplicatas
                # + descartados. Aqui só contam os casos EFETIVAMENTE processados (com --limite-casos são menos que
                # os consolidados; o total consolidado fica em `execucoes.totais.casos_consolidados`). Erros ficam à parte.
                "analisados": resumo["novos"] + resumo["atualizados"], "novos": resumo["novos"],
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
    parser.add_argument("--janela-dias", type=int, default=None,
                         help="só lê eventos dos últimos N dias (padrão: parâmetro versionado, 1095; 0 = sem filtro de data)")
    parser.add_argument("--piso-criticidade", default="PADRAO", choices=["PADRAO", "ROTINA", "BAIXA", "MEDIA", "ALTA", "CRITICO", "NENHUM"],
                         help="PADRAO = piso_selecao dos parâmetros (MEDIA, ALTA, CRITICO); NENHUM = desliga a régua (legado)")
    parser.add_argument("--somente-existentes", action="store_true",
                        help="só atualiza casos que já existem no banco; não cria nenhum evento novo")
    parser.add_argument("--hoje", default=None, help="data de referência AAAA-MM-DD (padrão: hoje; útil em testes)")
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
                    empresa_id=args.empresa_id, carteira_id=args.carteira_id,
                    janela_dias=args.janela_dias,
                    piso_criticidade=None if args.piso_criticidade == "NENHUM" else args.piso_criticidade,
                    somente_existentes=args.somente_existentes,
                    hoje=date.fromisoformat(args.hoje) if args.hoje else None)
    print(f"Execução {resultado['id_execucao']}: {resultado['resumo']}")
    for r in resultado["resultados"]:
        print(" -", r)
    if resultado["resumo"]["erros"] > 0:
        sys.exit(1)

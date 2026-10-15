"""
Simulação (SOMENTE LEITURA, offline) da régua CRIT-V1.2 sobre um dump da base.

Entrada: dois JSON exportados do Supabase (M9A e M8) com as colunas usadas abaixo.
Saída: CSV com TODOS os eventos (classificação nova x antiga + motivos, quatro grupos de seleção e justificativa)
e um JSON de resumo. Grupos: SELECIONAVEL_AGORA, PENDENTE_DE_EVIDENCIA, NAO_AVALIAVEL, FORA_DA_SELECAO.
Não grava nada em banco nenhum.

Uso:  python simular_criticidade.py --m9a m9a_dump.json --m8 m8_dump.json --hoje 2026-10-14 --saida ./saida
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criticidade as c

ORDEM_PRIO = {"A": 0, "B": 1, "C": 2, "D": 3, None: 4}


def _evidencia(row: dict) -> bool:
    """Evidência = linhas reais em `evidencias` (nev). A url_oficial genérica do portal de microdados da ANM NÃO conta:
    os 4 casos curados têm só essa URL e 0 evidências, e o portão pré-IA do servidor os bloqueia por falta de documento."""
    return bool((row.get("nev") or 0) > 0)


def entrada_m9a(row: dict) -> dict:
    tipo_scm = row.get("tipo_scm")
    n_mun = len([m for m in re.split(r"[;/]", row.get("municipio") or "") if m.strip()])
    texto_livre = " ".join(filter(None, [row.get("tipo_evento"), row.get("decisao")]))
    subst_texto = " ".join(filter(None, [row.get("atividade"), row.get("palavras_chave"), row.get("titulo_fato")]))
    area = None
    if row.get("area_scm") not in (None, ""):
        try:
            area = float(row["area_scm"])
        except ValueError:
            area = None
    if area is None and not tipo_scm:
        area = c.area_de_texto(row.get("impacto_dimensionado"), row.get("titulo_fato"))
    return {
        "tipo_scm": tipo_scm, "tipo_texto": texto_livre,
        "data_ato": row.get("dt_scm") or row.get("data_evento"),
        "titular": row.get("titular_scm") or row.get("empresa"),
        "substancia": row.get("subst_scm"), "substancia_texto": None if row.get("subst_scm") else subst_texto,
        "area_ha": area, "n_municipios": n_mun, "tem_evidencia": _evidencia(row), "evidencia_usada": None,
    }


_GATILHO_TEXTUAL = {
    "curso_dagua": "atingiu_ou_pode_atingir_curso_dagua",
    "rejeito": "rejeito_ou_produto_perigoso_ou_volume_significativo",
    "risco_estrutural": "risco_estrutural_ou_interrupcao_abastecimento",
    "vitimas_ou_comunidade": "vitimas_evacuacao_bloqueio_ou_risco_comunidade",
    "ultrapassou_limites": "ultrapassou_limites_operacao",
}


def entrada_m8(row: dict) -> dict:
    gat = row.get("gatilhos_aplicados") or {}
    m = re.search(r"(\d{2}/\d{2}/\d{4})", row.get("titulo_fato") or "")
    return {
        "status_processamento": row.get("status_processamento"), "faixa_vinculo": row.get("faixa_vinculo"),
        "data_ocorrencia": row.get("data_hora_ocorrencia") or (m.group(1) if m else None),
        "confirmados": {k: row.get(k) for k in ("vitimas", "risco_estrutura", "risco_abastecimento",
                                                 "atingiu_curso_agua", "saiu_limite_operacao")},
        "sinais_textuais": {nome: (chave in gat) for nome, chave in _GATILHO_TEXTUAL.items()},
        "score_gravidade": row.get("score_gravidade"),
        "motivo_falha": row.get("motivo_falha"),
        "tem_evidencia": row.get("status_processamento") in ("processado", "descartado") or (row.get("nev") or 0) > 0 and
        row.get("status_processamento") != "falha_extracao",
    }


def qualidade_evidencia(row: dict) -> int:
    return {"Alta": 3, "Media": 2, "Baixa": 1}.get(row.get("gc"), 0)


G1, G2, G3, G4 = c.SELECIONAVEL_AGORA, c.PENDENTE_DE_EVIDENCIA, c.NAO_AVALIAVEL, c.FORA_DA_SELECAO


def grupo_selecao(row: dict, res: c.ResultadoCriticidade, par: dict) -> tuple:
    """Delegado à regra única (criticidade.grupo_selecao); aqui só se extrai o estado do evento da linha do dump."""
    el = row.get("el") or {}
    return c.grupo_selecao(res, par, row.get("status_editorial"), bool(el.get("ia_sucesso_previo")))


def elegivel_novo(row: dict, res: c.ResultadoCriticidade, par: dict = None) -> bool:
    return grupo_selecao(row, res, par or c.carregar_parametros())[0] == G1


_ROTULO_REFORCO = {"empresa_relevante": "empresa relevante", "mineral_estrategico": "mineral estratégico",
                   "varios_municipios": "vários municípios", "curso_dagua": "curso d'água (palavra-chave)",
                   "rejeito": "rejeito (palavra-chave)", "risco_estrutural": "risco estrutural (palavra-chave)",
                   "vitimas_ou_comunidade": "vítimas/comunidade (palavra-chave)", "ultrapassou_limites": "limites ultrapassados (palavra-chave)"}


def _fmt_reforcos(res) -> str:
    if not res.reforcos:
        return "nenhum"
    return ", ".join(_ROTULO_REFORCO.get(x, x.replace("_", " ")) for x in res.reforcos)


def justificar(r: dict, res, par: dict, grupo: str) -> tuple:
    """Texto de justificativa determinística (a partir dos próprios campos da régua, sem IA) e o que falta."""
    mod = r.get("modulo")
    lim = par[mod.lower()]["atualidade_dias"] if mod in ("M9A", "M8") else {}
    ref_nivel = res.nivel_potencial or res.nivel_antes_idade or res.nivel
    idade = f"{res.idade_dias} d" if res.idade_dias is not None else "data desconhecida"
    limite = f", dentro do limite de {lim[ref_nivel]} d para {ref_nivel}" if ref_nivel in lim and res.idade_dias is not None and res.idade_dias <= lim[ref_nivel] else ""
    if mod == "M9A":
        base = (f"Objeto {res.objeto}, fase {res.fase}; ato de {entrada_m9a(r)['data_ato']} ({idade}{limite}). "
                f"Reforços: {_fmt_reforcos(res)}. Evidência: {descrever_evidencia(r, res)}. ")
    else:
        base = (f"Comunicado SEMAD, vínculo {res.fase}; ocorrência de {entrada_m8(r)['data_ocorrencia'] or 'data desconhecida'} ({idade}{limite}). "
                f"Sinais textuais: {_fmt_reforcos(res)}. Evidência: {descrever_evidencia(r, res)}. ")
    if grupo == G1:
        return base + f"Resultado: {res.nivel} ({res.prioridade}), classificação consolidada, apta à seleção.", ""
    falta = {"tipo_oficial_e_evidencia_estruturada": "tipo oficial do SCM (descricao_tipo_evento) e evidência estruturada em `evidencias`",
             "tipo_oficial_scm": "tipo oficial do SCM (descricao_tipo_evento) em `evidencias`",
             "evidencia_estruturada": "evidência estruturada em `evidencias`",
             "confirmacao_estruturada_do_agravante": "confirmação do agravante em campo estruturado (por exemplo, atingiu_curso_agua) a partir do comunicado"}.get(res.pendencia or "", "")
    sufixo = " Recalculada automaticamente pela mesma régua quando o que falta entrar; o histórico é preservado." if falta else ""
    res_txt = f"Resultado: {res.nivel}" + (f" (nível potencial {res.nivel_potencial})" if res.nivel_potencial else "") + \
        (", classificação provisória" if res.provisoria else "") + "."
    return base + res_txt + (f" Falta: {falta}." if falta else "") + sufixo, falta


def descrever_evidencia(r: dict, res) -> str:
    nev = r.get("nev") or 0
    if r.get("modulo") == "M9A":
        if res.origem_classificacao == "curada":
            return f"nenhuma linha em evidencias ({nev}); classificação provisória por texto livre curado (url_oficial é só o portal de microdados)"
        return f"{nev} evidências SCM (microdados_scm); tipo oficial DSEvento='{r.get('tipo_scm')}'"
    st = r.get("status_processamento")
    if st == "falha_extracao":
        return "nenhuma: documento não aberto (" + str(r.get("motivo_falha") or "falha") + ")"
    return f"comunicado SEMAD lido por OCR; {nev} evidências; vínculo={r.get('faixa_vinculo')}"


def simular(m9a_rows, m8_rows, par, referencia):
    out = []
    for modulo, rows, f in (("M9A", m9a_rows, entrada_m9a), ("M8", m8_rows, entrada_m8)):
        for r in rows:
            r = dict(r, modulo=modulo)
            res = c.classificar(modulo, f(r), par, referencia)
            res.evidencia_usada = descrever_evidencia(r, res)
            antes = r.get("prioridade_atual")
            nova = res.prioridade
            if antes is None:
                mov = "sem_prioridade_antes"
            elif nova is None:
                mov = "sem_prioridade_definitiva"
            elif ORDEM_PRIO[nova] < ORDEM_PRIO[antes]:
                mov = "subiu"
            elif ORDEM_PRIO[nova] > ORDEM_PRIO[antes]:
                mov = "desceu"
            else:
                mov = "igual"
            nova_ord = ORDEM_PRIO[nova]
            ab_d = antes in ("A", "B") and nova == "D"
            grupo, motivo_grupo = grupo_selecao(r, res, par)
            justificativa, falta = justificar(r, res, par, grupo)
            el = r.get("el") or {}
            out.append({
                "modulo": modulo, "id_evento": r["id_evento"], "uid": r["uid"], "titulo": (r.get("titulo_fato") or "")[:90],
                "empresa": r.get("empresa") or r.get("empresa_citada") or "", "municipio": r.get("municipio") or "",
                "tipo_scm": r.get("tipo_scm") or r.get("tipo_evento") or "", "data_ato": entrada_m9a(r)["data_ato"] if modulo == "M9A" else entrada_m8(r)["data_ocorrencia"],
                "versao_score_antes": r.get("versao_score") or "", "prioridade_antes": antes or "",
                "score_antes": r.get("score_bruto"), "score_norm_antes": r.get("score_norm"),
                "criticidade": res.nivel, "prioridade_depois": nova, "pontuacao": res.pontuacao, "idade_dias": res.idade_dias,
                "objeto": res.objeto, "fase": res.fase, "reforcos": "+".join(res.reforcos), "motivos": res.resumo_motivos(),
                "selecionavel": res.selecionavel, "avaliavel": res.avaliavel,
                "elegivel_pre_ia_antes": bool(el.get("elegivel")), "ja_analisado_ia": bool(el.get("ia_sucesso_previo")),
                "elegivel_novo": grupo == G1, "movimento": mov, "ab_para_d": ab_d,
                "grupo": grupo, "motivo_grupo": motivo_grupo, "bloqueios": "+".join(res.bloqueios),
                "nivel_potencial": res.nivel_potencial or "", "nivel_antes_idade": res.nivel_antes_idade or "",
                "evidencia_suficiente": res.evidencia_suficiente, "pendencia": res.pendencia or "",
                "o_que_falta": falta, "justificativa": justificativa,
                "qualidade_evidencia": qualidade_evidencia(r), "status_editorial": r.get("status_editorial"),
                "origem_classificacao": res.origem_classificacao, "provisoria": res.provisoria,
                "n_evidencias_banco": r.get("nev") or 0, "evidencia_usada": descrever_evidencia(r, res),
                "ja_passou_por_ia": bool(el.get("ia_sucesso_previo")), "prioridade_antiga_ordem": ORDEM_PRIO[antes],
                "prioridade_nova_ordem": nova_ord,
            })
    # ordem dentro de cada grupo (grupos 1 e 2 usam a ordem determinística da régua) e marcação do corte de até N
    limite = par["limite_selecao_padrao"]
    for g in (G1, G2, G3, G4):
        membros = sorted([l for l in out if l["grupo"] == g], key=chave)
        for i, l in enumerate(membros, 1):
            l["ordem_no_grupo"] = i
            l["dentro_do_teto"] = (g == G1 and i <= limite)
    return out


def chave(l):
    return c.chave_ordenacao({"nivel": l["criticidade"], "nivel_potencial": l.get("nivel_potencial") or None,
                              "prioridade": l["prioridade_depois"], "pontuacao": l["pontuacao"],
                              "idade_dias": l["idade_dias"], "qualidade_evidencia": l["qualidade_evidencia"],
                              "id_evento": l["id_evento"]})


def resumo(linhas, par):
    niveis = par["niveis"]
    res = {"distribuicao": {}, "transicoes": {}, "selecao": {}}
    for mod in ("M9A", "M8", "TOTAL"):
        ls = [l for l in linhas if mod == "TOTAL" or l["modulo"] == mod]
        res["distribuicao"][mod] = {n: sum(1 for l in ls if l["criticidade"] == n) for n in list(reversed(niveis)) + list(c.ESTADOS_FORA_DA_ESCALA)}
    for mod in ("M9A", "M8"):
        ls = [l for l in linhas if l["modulo"] == mod]
        res["transicoes"][mod] = dict(Counter(f'{l["prioridade_antes"] or "-"}->{l["prioridade_depois"]}' for l in ls).most_common())
        pool = sorted([l for l in ls if l["grupo"] == G1], key=chave)
        escolhidos = pool[: par["limite_selecao_padrao"]]
        cortados = pool[par["limite_selecao_padrao"]:]
        pendentes = sorted([l for l in ls if l["grupo"] == G2], key=chave)
        abaixo = sorted([l for l in ls if l["grupo"] == G4 and l["avaliavel"] and not l["ja_analisado_ia"]
                         and l["status_editorial"] not in ("descartado", "publicado", "pronto_para_publicar")], key=chave)
        res["selecao"][mod] = {"escolhidos": escolhidos, "cortados_por_limite": cortados, "pendentes_de_evidencia": pendentes,
                               "abaixo_do_piso_top10": abaixo[:10]}
    res["grupos"] = {g: {mod: sum(1 for l in linhas if l["grupo"] == g and (mod == "TOTAL" or l["modulo"] == mod))
                         for mod in ("M9A", "M8", "TOTAL")} for g in (G1, G2, G3, G4)}
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--m9a", required=True)
    ap.add_argument("--m8", required=True)
    ap.add_argument("--hoje", default=date.today().isoformat())
    ap.add_argument("--saida", required=True)
    ap.add_argument("--parametros", default=None)
    ap.add_argument("--objetos-propostos", action="store_true",
                    help="what-if: ativa os objetos propostos (m9a.usar_objetos_propostos) SEM alterar o arquivo de parâmetros")
    a = ap.parse_args()
    par = c.carregar_parametros(a.parametros)
    if a.objetos_propostos:
        par["m9a"]["usar_objetos_propostos"] = True
    ref = date.fromisoformat(a.hoje)
    m9a = json.load(open(a.m9a, encoding="utf-8"))
    m8 = json.load(open(a.m8, encoding="utf-8"))
    linhas = simular(m9a, m8, par, ref)
    os.makedirs(a.saida, exist_ok=True)
    nome_csv = "simulacao_criticidade_v1_2_objetos_propostos.csv" if a.objetos_propostos else "simulacao_criticidade_v1_2.csv"
    with open(os.path.join(a.saida, nome_csv), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    r = resumo(linhas, par)
    json.dump({"referencia": a.hoje, "versao_regra": par["versao_regra"], "versao_parametros": par["versao_parametros"], **r},
              open(os.path.join(a.saida, nome_csv.replace(".csv", "_resumo.json")), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(r["distribuicao"], ensure_ascii=False))

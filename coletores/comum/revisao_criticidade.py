"""
Revisão determinística (SOMENTE LEITURA) da simulação da régua de criticidade: separa o que parece superavaliado,
subavaliado, mudou muito em relação à prioridade antiga e tem regra ambígua. As etiquetas são regras explícitas
(abaixo), não julgamento livre — quem decide se a régua deve mudar é a Raphaela.

Uso: python revisao_criticidade.py simulacao_criticidade_v1_2.csv saida.csv resumo.json
"""
import csv
import json
import sys

M8_AMBIGUOS_LIDOS = {"semad-m8-170": "municipio_minerador_ignorado", "semad-m8-183": "municipio_minerador_ignorado",
                     "semad-m8-181": "vinculo_contextual", "semad-m8-182": "vinculo_contextual",
                     "semad-m8-200": "vinculo_contextual", "semad-m8-201": "vinculo_contextual"}
NIVEL_SELECIONAVEL = ("MEDIA", "ALTA", "CRITICO")
POTENCIAIS = ("POTENCIAL_CRITICO_PENDENTE_EVIDENCIA", "POTENCIAL_ALTA_PENDENTE_EVIDENCIA")


def etiquetar(r: dict) -> list:
    t = []
    niv, mod = r["criticidade"], r["modulo"]
    idade = int(r["idade_dias"]) if r["idade_dias"] else None
    reforcos = [x for x in r["reforcos"].split("+") if x]
    antes, depois = r["prioridade_antiga_ordem"], r["prioridade_nova_ordem"]
    antes = int(antes) if antes not in ("", None) else None
    sem_prioridade = r["prioridade_depois"] in ("", None)
    depois = int(depois) if depois not in ("", None) and not sem_prioridade else None
    if antes == 4:
        antes = None   # prioridade antiga ausente

    # ---- superavaliado: nível >= MEDIA com base frágil
    if niv in NIVEL_SELECIONAVEL:
        if int(r["n_evidencias_banco"] or 0) == 0:
            t.append("SUPER:sem_evidencia_no_banco")
        if r["provisoria"] == "True":
            t.append("SUPER:classificacao_provisoria")
        if mod == "M8" and "agravante_apenas_textual_nao_verificado" in r["motivos"]:
            t.append("SUPER:agravante_so_por_palavra_chave")
    # ---- pendente de evidência: não é erro, é estado intermediário (rastreio)
    if niv in POTENCIAIS:
        t.append("PENDENTE:" + niv.lower())
    # ---- subavaliado: nível <= BAIXA com sinal forte
    if niv in ("BAIXA", "ROTINA"):
        if r["fase"] == "efetiva" and r["objeto"] == "outro" and reforcos:
            t.append("SUB:tipo_nao_mapeado_efetivo_com_reforco")
        if r["fase"] == "efetiva" and r["objeto"] != "outro" and len(reforcos) >= 2 and idade is not None and "desce_de" in r["motivos"]:
            t.append("SUB:efetivo_com_2plus_reforcos_barrado_so_por_idade")
        if r["objeto"] == "gravame":
            t.append("SUB:gravame_efetivo_barrado")
        if mod == "M8" and r["id_evento"] in M8_AMBIGUOS_LIDOS:
            t.append("SUB:m8_lido_sem_vinculo_suficiente_" + M8_AMBIGUOS_LIDOS[r["id_evento"]])
    # ---- mudou muito: caiu 2 ou mais degraus A>B>C>D
    if antes is not None and depois is not None and depois - antes >= 2:
        t.append(f"MUDOU:{'ABCD'[antes]}->{'ABCD'[depois]}")
    elif antes is not None and sem_prioridade and niv in POTENCIAIS:
        t.append(f"MUDOU:{'ABCD'[antes]}->sem_prioridade_definitiva")
    # ---- ambíguo
    if r["objeto"] == "outro" and r["fase"] in ("efetiva", "indefinida"):
        t.append("AMBIGUO:objeto_outro_nao_pedido")
    if r["fase"] == "indefinida":
        t.append("AMBIGUO:fase_indefinida")
    if r["objeto"] == "prorrogacao_prazo_requerer_lavra":
        # decisão antiga ou pedido: resultado inequívoco pela regra (BAIXA). Só a decisão RECENTE depende do critério
        # "consequência material" e fica marcada como ambígua.
        if r["fase"] == "efetiva" and idade is not None and idade <= 365:
            t.append("AMBIGUO:prorrogacao_prazo_lavra_decisao_recente_consequencia_material")
        else:
            t.append("INFO:prorrogacao_prazo_lavra_regra_aplicada_" + ("decisao_antiga" if r["fase"] == "efetiva" else "pedido_ou_fase_nao_efetiva"))
    if mod == "M8" and "vinculo_provavel" in r["motivos"] and niv in NIVEL_SELECIONAVEL:
        t.append("AMBIGUO:vinculo_provavel")
    if r["provisoria"] == "True" and r["origem_classificacao"] == "curada":
        t.append("AMBIGUO:origem_curada_sem_tipo_oficial")
    if r["provisoria"] == "True" and r["modulo"] == "M8":
        t.append("AMBIGUO:agravante_m8_provisorio_aguarda_confirmacao_estruturada")
    return t


def main(entrada, saida_csv, saida_json):
    rows = list(csv.DictReader(open(entrada, encoding="utf-8-sig"), delimiter=";"))
    for r in rows:
        r["revisao_tags"] = "|".join(etiquetar(r))
    with open(saida_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    grupos = {"SUPER": [], "SUB": [], "MUDOU": [], "AMBIGUO": [], "PENDENTE": [], "INFO": []}
    for r in rows:
        for tag in r["revisao_tags"].split("|"):
            if tag:
                grupos[tag.split(":")[0]].append({"id_evento": r["id_evento"], "modulo": r["modulo"], "tag": tag,
                                                  "empresa": r["empresa"], "tipo_scm": r["tipo_scm"], "data_ato": r["data_ato"],
                                                  "criticidade": r["criticidade"], "prioridade_antes": r["prioridade_antes"],
                                                  "prioridade_depois": r["prioridade_depois"]})
    json.dump(grupos, open(saida_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {k: len(v) for k, v in grupos.items()}


if __name__ == "__main__":
    print(main(*sys.argv[1:4]))

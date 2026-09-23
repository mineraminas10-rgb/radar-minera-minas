"""
Módulo 9A — mapeamento de sinais (SignaisM9A) a partir dos campos
estruturados do SCM (não é heurística de texto livre como no M8 — os
microdados do SCM vêm em campos, não em narrativa). Mesmo assim, os
NOMES e VALORES reais das colunas (`evento_tipo`, `substancia` etc.) não
foram confirmados contra uma amostra real (ver aviso em ingestao_scm.py).
Ajustar as listas abaixo assim que a Rapha mandar a amostra.

Duas interpretações minhas que valem confirmar com a Rapha:
1. avanco_pesquisa (+3, "relatório aprovado, nova substância ou
   reavaliação aprovada") vs reserva_ou_substancia (+1, "nova substância
   ou reavaliação de reserva") se sobrepõem na letra da carta — tratei
   avanco_pesquisa como exigindo status 'aprovado' explícito, e
   reserva_ou_substancia como o sinal mais fraco (pedido/reavaliação
   ainda sem aprovação confirmada).
2. "empresa relevante" (+2) depende de uma lista de referência de
   empresas de grande porte — comecei só com as citadas na própria carta
   como exemplo (Vale, CSN, AngloGold, Kinross, Anglo American, Usiminas);
   provavelmente precisa de uma lista melhor (ex.: maiores produtoras por
   CFEM) que a Rapha já deve ter ou saber onde buscar.
"""
from typing import Optional
from scoring import SignaisM9A

EMPRESAS_RELEVANTES = {
    "vale", "csn", "anglogold", "anglogold ashanti", "kinross",
    "anglo american", "usiminas", "samarco", "nexa", "itaminas",
}

MINERAIS_ESTRATEGICOS = {
    "ferro", "ouro", "litio", "lítio", "manganes", "manganês", "niobio",
    "nióbio", "grafite", "terras raras", "cobalto", "niquel", "níquel",
    "fosfato", "titanio", "titânio",
}

EVENTOS_MUDANCA_MATERIAL = {
    "decaimento", "caducidade", "cessao", "cessão", "transferencia",
    "transferência", "penhora", "indisponibilidade", "interdicao",
    "interdição", "renuncia", "renúncia", "concessao", "concessão",
}
EVENTOS_DECAIMENTO_CADUCIDADE_INTERDICAO_LAVRA = {
    "decaimento", "caducidade", "interdicao de concessao de lavra",
    "interdição de concessão de lavra",
}
EVENTOS_AUTORIZACAO_EXTRACAO = {"guia de utilizacao", "guia de utilização", "portaria de lavra"}
EVENTOS_AVANCO_PESQUISA_APROVADO = {"relatorio aprovado", "relatório aprovado", "reavaliacao aprovada", "reavaliação aprovada"}
EVENTOS_ALVARA_COMUM = {"alvara de pesquisa", "alvará de pesquisa", "alvara comum de pesquisa"}
EVENTOS_RESERVA_SUBSTANCIA = {"nova substancia", "nova substância", "reavaliacao de reserva", "reavaliação de reserva"}
EVENTOS_ROTINA = {"protocolo", "juntada", "pagamento de tah", "ral", "documento diverso"}
EVENTOS_EXIGENCIA_GENERICA = {"exigencia", "exigência"}
EVENTOS_RETIFICACAO = {"retificacao", "retificação"}


def _norm(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def extrair_signais_m9a(linha: dict, contagem_municipios_processo: int = 1) -> SignaisM9A:
    """`linha` é um dict com os campos de um evento/ato já filtrado pelo
    recorte M9A (ver ingestao_scm.aplicar_recorte_m9a). `contagem_municipios_processo`
    vem de um agrupamento por processo feito antes desta chamada."""
    evento_tipo = _norm(linha.get("evento_tipo"))
    substancia = _norm(linha.get("substancia"))
    titular = _norm(linha.get("titular"))
    area_ha = linha.get("area_ha")

    mudanca_material = any(k in evento_tipo for k in EVENTOS_MUDANCA_MATERIAL)
    decaimento_especifico = any(k in evento_tipo for k in EVENTOS_DECAIMENTO_CADUCIDADE_INTERDICAO_LAVRA)

    return SignaisM9A(
        mudanca_material_direito=mudanca_material,
        decaimento_caducidade_ou_interdicao_lavra=decaimento_especifico,
        autorizacao_extracao=any(k in evento_tipo for k in EVENTOS_AUTORIZACAO_EXTRACAO) and "protocolo" not in evento_tipo,
        avanco_pesquisa=any(k in evento_tipo for k in EVENTOS_AVANCO_PESQUISA_APROVADO),
        alvara_comum_pesquisa=any(k in evento_tipo for k in EVENTOS_ALVARA_COMUM),
        dimensao_objetiva=bool(area_ha) and str(area_ha).strip() not in ("", "0", "0.0"),
        empresa_relevante=any(e in titular for e in EMPRESAS_RELEVANTES),
        mineral_estrategico=any(m in substancia for m in MINERAIS_ESTRATEGICOS),
        reserva_ou_substancia=any(k in evento_tipo for k in EVENTOS_RESERVA_SUBSTANCIA),
        varios_municipios=contagem_municipios_processo >= 2,
        rotina=any(k in evento_tipo for k in EVENTOS_ROTINA),
        exigencia_generica=any(k in evento_tipo for k in EVENTOS_EXIGENCIA_GENERICA),
        retificacao_formal=any(k in evento_tipo for k in EVENTOS_RETIFICACAO),
    )


def extrair_evidencias_campo(linha: dict) -> list:
    """Checklist Completo de Enriquecimento, seção 'Evidências e
    proveniência': mesmo dado estruturado (não texto livre) precisa de
    'trecho literal' rastreável por campo. Aqui o 'trecho' é o próprio
    valor da coluna do SCM, entre aspas — é literal porque é exatamente o
    que a fonte oficial publicou naquela coluna, sem interpretação do
    coletor (diferente dos SinaisM9A acima, que já são inferência)."""
    campos_rastreados = ["processo", "evento_tipo", "titular", "substancia", "municipio", "data_evento"]
    evidencias = []
    for campo in campos_rastreados:
        valor = linha.get(campo)
        if valor not in (None, ""):
            evidencias.append({"campo": campo, "trecho_literal": str(valor)})
    return evidencias

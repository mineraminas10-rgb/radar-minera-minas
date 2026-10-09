"""
Módulo 9A — mapeamento de sinais (SignaisM9A) a partir dos campos
estruturados do SCM (não é heurística de texto livre como no M8 — os
microdados do SCM vêm em campos, não em narrativa). Os NOMES e VALORES
reais das colunas de `evento_tipo`/`substância` foram confirmados contra
uma amostra real do dicionário `Evento.txt` (2.926 linhas, 28/09/2026) —
ver `classificacao_scm.py`. O que ainda não foi confirmado é o mapeamento
completo de `ingestao_scm.py` linha a linha do arquivo bruto (worker
separado) — ver aviso lá.

ACHADO de 28/09/2026, corrigido aqui: a classificação abaixo passou a
operar sobre `TipoEventoSCM` (identidade oficial do evento — IDEvento +
nome do dicionário `Evento.txt`, ver classificacao_scm.py), nunca sobre o
texto narrativo livre (`OBEvento`/`DSPublicacaoDOU`) que varia por
redação. Antes desta correção, `extrair_signais_m9a()` comparava palavra-
chave direto contra qualquer texto que viesse em `linha['evento_tipo']` —
o que fazia o mesmo ato classificar diferente dependendo de qual campo do
SCM alimentasse essa chave. Ver docstring de classificacao_scm.py para o
achado completo (não é um problema isolado de um evento, é uma classe de
variação de preposição/artigo que qualquer tipo do dicionário pode ter).

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
import classificacao_scm as clsf

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
    vem de um agrupamento por processo feito antes desta chamada.

    ACHADO/correção de 28/09/2026: a classificação por palavra-chave abaixo
    passou a rodar sobre `linha['descricao_tipo_evento']` (= DSEvento, nome
    do dicionário `Evento.txt`, join por `linha['id_tipo_evento']` = IDEvento
    — identidade oficial e estável do tipo de evento), nunca sobre
    `linha['evento_tipo']` (texto narrativo livre, mantido só para
    trecho_literal de evidência — ver extrair_evidencias_campo). Ver
    classificacao_scm.py para o achado completo. `autorizacao_extracao`
    também passou a exigir `situacao == 'concluido'` (pelo sufixo do
    dicionário: PUBL/AUTORIZADO/...) em vez do antigo `'protocolo' not in
    evento_tipo` — mesma ideia, mas genérica (funciona para qualquer tipo
    do dicionário 'em trâmite', não só quando a palavra é literalmente
    'protocolo')."""
    tipo = clsf.classificar(linha.get("id_tipo_evento"), linha.get("descricao_tipo_evento"))
    substancia = _norm(linha.get("substancia"))
    titular = _norm(linha.get("titular"))
    area_ha = linha.get("area_ha")

    mudanca_material = tipo.contem(*EVENTOS_MUDANCA_MATERIAL)
    decaimento_especifico = tipo.contem(*EVENTOS_DECAIMENTO_CADUCIDADE_INTERDICAO_LAVRA)

    return SignaisM9A(
        mudanca_material_direito=mudanca_material,
        decaimento_caducidade_ou_interdicao_lavra=decaimento_especifico,
        autorizacao_extracao=tipo.contem(*EVENTOS_AUTORIZACAO_EXTRACAO) and tipo.situacao == "concluido",
        avanco_pesquisa=tipo.contem(*EVENTOS_AVANCO_PESQUISA_APROVADO) and tipo.situacao == "concluido",
        alvara_comum_pesquisa=tipo.contem(*EVENTOS_ALVARA_COMUM),
        dimensao_objetiva=bool(area_ha) and str(area_ha).strip().replace(",", ".") not in ("", "0", "0.0"),
        empresa_relevante=any(e in titular for e in EMPRESAS_RELEVANTES),
        mineral_estrategico=any(m in substancia for m in MINERAIS_ESTRATEGICOS),
        reserva_ou_substancia=tipo.contem(*EVENTOS_RESERVA_SUBSTANCIA),
        varios_municipios=contagem_municipios_processo >= 2,
        rotina=tipo.contem(*EVENTOS_ROTINA),
        exigencia_generica=tipo.contem(*EVENTOS_EXIGENCIA_GENERICA),
        retificacao_formal=tipo.contem(*EVENTOS_RETIFICACAO),
    )


def extrair_evidencias_campo(linha: dict) -> list:
    """Checklist Completo de Enriquecimento, seção 'Evidências e
    proveniência': mesmo dado estruturado (não texto livre) precisa de
    'trecho literal' rastreável por campo. Aqui o 'trecho' é o próprio
    valor da coluna do SCM, entre aspas — é literal porque é exatamente o
    que a fonte oficial publicou naquela coluna, sem interpretação do
    coletor (diferente dos SinaisM9A acima, que já são inferência).

    `area_ha` e `descricao_tipo_evento` entraram em 28/09/2026 (achado da
    auditoria: a área já era usada em dimensao_objetiva mas nunca virava
    evidência gravável; o nome do dicionário passou a ser o campo que
    efetivamente decide classificação, então também merece evidência
    própria, sustentando por que o tipo foi classificado como foi)."""
    campos_rastreados = [
        "processo", "evento_tipo", "descricao_tipo_evento", "titular",
        "substancia", "municipio", "data_evento", "area_ha",
    ]
    evidencias = []
    for campo in campos_rastreados:
        valor = linha.get(campo)
        if valor not in (None, ""):
            evidencias.append({"campo": campo, "trecho_literal": str(valor)})
    return evidencias

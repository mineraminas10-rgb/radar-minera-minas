"""Funil determinístico para triagem de contaminação ligada à mineração.

Esta camada recebe conteúdo já capturado de fonte oficial; não faz scraping,
OCR, consulta de processo, nem grava no Supabase. Nenhum resultado é publicação.
"""
from __future__ import annotations

import re
import unicodedata
from html import escape
from calendar import monthrange
from datetime import date, datetime
from typing import Any

VERSAO_REGRA = "M10-IMPACTO-0.1"

ATIVIDADE_DIRETA = (
    "cava da mina", "barragem de rejeitos", "pilha de estéril", "pilha de esteril",
    "bacia de sedimentação", "bacia de sedimentacao", "drenagem ácida de mina",
    "drenagem acida de mina", "drenagem ácida", "drenagem acida", "dam",
    "lavra a céu aberto", "lavra a ceu aberto",
    "lavra subterrânea", "lavra subterranea", "duto de polpa", "espodumênio",
    "espodumenio", "minério de ferro", "minerio de ferro", "bauxita", "manganês",
    "manganes", "ouro", "lítio", "litio", "terras raras",
)
AMBIENTAL_SUBTERRANEO = (
    "aquífero", "aquifero", "lençol freático", "lencol freatico", "área de recarga",
    "area de recarga", "infiltração de efluentes", "infiltracao de efluentes",
    "percolação de contaminantes", "percolacao de contaminantes", "contaminação do solo",
    "contaminacao do solo", "metais pesados", "arsênio", "arsenio", "chumbo",
    "cádmio", "cadmio", "cianeto", "mercúrio", "mercurio",
)
AMBIENTAL_AMPLIADO = (
    "mortandade de peixes", "poluição de rios", "poluicao de rios", "córrego", "corrego",
    "bacia hidrográfica", "bacia hidrografica", "assoreamento", "turbidez da água",
    "turbidez da agua", "rejeitos na calha", "vazamento de lama", "contaminação do solo",
    "contaminacao do solo", "terra estéril", "terra esteril", "erosão", "erosao",
    "degradação da camada superficial", "degradacao da camada superficial",
    "inutilização da área", "inutilizacao da area", "metais pesados", "arsênio", "arsenio",
    "chumbo", "cádmio", "cadmio", "cianeto", "mercúrio", "mercurio", "aquífero",
    "aquifero", "lençol freático", "lencol freatico", "área de recarga", "area de recarga",
    "infiltração de efluentes", "infiltracao de efluentes", "percolação", "percolacao",
)
IMPACTO_SOCIAL = (
    "poço artesiano", "poco artesiano", "cisterna", "captação comunitária",
    "captacao comunitaria", "assentamento rural", "comunidade tradicional",
    "vazamento em propriedade de terceiros", "perda de potabilidade",
    "dessedentação de animais", "dessedentacao de animais", "pescadores",
    "economia da pesca", "agricultores", "destruição de lavoura", "destruicao de lavoura",
    "inviabilidade econômica", "inviabilidade economica",
)
# Normalização dos códigos informados: 07103, 07294 e grupo 081.
CNAE_ALVOS = {"07103", "07294", "081"}


def normalizar(texto: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.casefold()).strip()


def _matches(texto: str, termos: tuple[str, ...]) -> list[str]:
    t = normalizar(texto)
    encontrados = []
    for termo in termos:
        termo_normalizado = normalizar(termo)
        padrao = rf"(?<!\w){re.escape(termo_normalizado)}(?!\w)"
        if re.search(padrao, t):
            encontrados.append(termo)
    return encontrados


def _cnae_direto(cnae: str | None) -> str | None:
    digitos = re.sub(r"\D", "", str(cnae or ""))
    if digitos.startswith("07103"):
        return "07103"
    if digitos.startswith("07294"):
        return "07294"
    if digitos.startswith("081"):
        return "081"
    return None


def _data(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _adicionar_anos(d: date, anos: int) -> date:
    ano = d.year + anos
    return date(ano, d.month, min(d.day, monthrange(ano, d.month)[1]))


def _meses_ate(inicio: date, prazo_anos: int, hoje: date) -> int | None:
    limite = _adicionar_anos(inicio, prazo_anos)
    if hoje >= limite:
        return 0
    meses = (limite.year - hoje.year) * 12 + limite.month - hoje.month
    if limite.day > hoje.day:
        meses += 1
    return meses


def _frases(texto: str) -> list[str]:
    # Mantém a grafia e pontuação originais; o separador não é incluído.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", texto or "") if s.strip()]


def auditoria_status(evento: dict[str, Any], hoje: date) -> dict[str, Any]:
    ultima = _data(evento.get("data_ultima_movimentacao"))
    dias_parado = (hoje - ultima).days if ultima and ultima <= hoje else None
    multa = evento.get("valor_multa")
    multa_fonte = evento.get("fonte_valor_multa")
    jurisdiction = normalizar(evento.get("jurisdicao"))
    marco = _data(evento.get("marco_inicial_prescricao"))
    meses_limite = None
    regra = None
    alerta = "Sem dados suficientes para estimar prazo; conferir autos e legislação aplicável."

    # Lei federal 9.873/1999: prescrição intercorrente em processo federal
    # paralisado >3 anos aguardando julgamento ou despacho; quinquênio punitivo
    # tem marco inicial próprio (data da infração), distinto da última movimentação.
    if jurisdiction in {"federal", "anm"}:
        regra = "Lei 9.873/1999: quinquênio punitivo desde marco legal; intercorrente exige processo pendente e análise dos autos."
        if marco:
            meses_limite = _meses_ate(marco, 5, hoje)
            alerta = "Prazo estimado desde o marco informado; confirmar infração, atos interruptivos e tramitação."
        if dias_parado is not None and dias_parado >= 3 * 365:
            alerta = "Mais de 3 anos sem movimentação: verificar se o processo aguarda julgamento/despacho e se incide prescrição intercorrente."
    # Minas Gerais: Lei estadual 21.735/2015, art. 2-A (incluído pela Lei 24.755/2024).
    # Requer processo administrativo de crédito não tributário e inércia exclusiva do Estado.
    elif jurisdiction in {"minas gerais", "mg", "estadual mg"}:
        regra = "Lei MG 21.735/2015, art. 2-A: 5 anos de paralisação por inércia exclusiva da Administração."
        if marco and evento.get("inercia_exclusiva_estado") is True:
            meses_limite = _meses_ate(marco, 5, hoje)
            alerta = "Estimativa condicional; validar natureza do crédito, marco, suspensões e atos nos autos."
        else:
            alerta = "Prazo de prescrição não calculado: marco e/ou inércia exclusiva estadual não confirmados."

    return {
        "dias_desde_ultima_movimentacao": dias_parado,
        "valor_multa": multa,
        "fonte_valor_multa": multa_fonte,
        "meses_ate_marco_prescricional_estimado": meses_limite,
        "regra_prescricional_considerada": regra,
        "alerta_juridico": alerta,
    }


def avaliar_evento(evento: dict[str, Any], hoje: date | None = None) -> dict[str, Any]:
    """Executa os gates em ordem e devolve ficha candidata + trilha auditável."""
    hoje = hoje or date.today()
    # O gate setorial pode usar metadados/texto inicial/CNAE. Já os gates
    # ambiental e social só usam o texto descritivo atribuído ao fiscal.
    texto_setorial = "\n".join(str(evento.get(k) or "") for k in (
        "metadados", "texto_documento", "atividade", "cnae"
    ))
    hits_atividade = _matches(texto_setorial, ATIVIDADE_DIRETA)
    cnae = _cnae_direto(evento.get("cnae"))
    texto_fiscal = str(evento.get("texto_fiscal") or "")
    hits_ambientais = _matches(texto_fiscal, AMBIENTAL_AMPLIADO)
    hits_sociais = _matches(texto_fiscal, IMPACTO_SOCIAL)

    if not hits_atividade and not cnae:
        status, motivo = "descartado", "sem_atividade_mineraria_direta_ou_cnae_alvo"
    elif not hits_ambientais:
        status, motivo = "descartado", "sem_indicio_ambiental_subterraneo"
    elif not hits_sociais:
        status, motivo = "descartado", "sem_indicio_de_afetacao_humana_social"
    else:
        status, motivo = "candidato_fila_editor", "triplo_impacto_com_sinais_textuais"

    fiscal = texto_fiscal
    frases = _frases(fiscal)
    frases_ambientais = [s for s in frases if _matches(s, AMBIENTAL_AMPLIADO)]
    frases_sociais = [s for s in frases if _matches(s, IMPACTO_SOCIAL)]
    # Excerpt must come from the inspector's text exactly; no AI paraphrase.
    trecho = next((s for s in frases if _matches(s, AMBIENTAL_AMPLIADO)
                   and _matches(s, IMPACTO_SOCIAL)), None)
    if trecho is None:
        trecho = next(iter(frases_ambientais), None) or next(iter(frases_sociais), None)

    audit = auditoria_status(evento, hoje)
    prioridade = "ALTA_RELEVANCIA_ALERTA_VERMELHO" if (
        (audit["dias_desde_ultima_movimentacao"] is not None
         and audit["dias_desde_ultima_movimentacao"] >= 365)
        or (audit["meses_ate_marco_prescricional_estimado"] is not None
            and audit["meses_ate_marco_prescricional_estimado"] <= 12)
    ) else "EXPOSICAO_PADRAO"
    return {
        "versao_regra": VERSAO_REGRA,
        "status_triagem": status,
        "motivo_status": motivo,
        "numero_processo": evento.get("numero_processo"),
        "razao_social_empreendedor": evento.get("razao_social_empreendedor"),
        "data_abertura_processo": evento.get("data_abertura_processo"),
        "orgao_origem": evento.get("orgao_origem"),
        "atividade_direta": hits_atividade[0] if hits_atividade else None,
        "cnae_enquadrado": cnae,
        "evidencias_atividade": hits_atividade,
        "evidencias_ambientais": hits_ambientais,
        "evidencias_sociais": hits_sociais,
        "trecho_literal_fiscal": trecho,
        "trecho_cobre_os_dois_nexos": bool(trecho and _matches(trecho, AMBIENTAL_AMPLIADO)
                                           and _matches(trecho, IMPACTO_SOCIAL)),
        "fonte_url": evento.get("fonte_url"),
        "documento_url": evento.get("documento_url"),
        "data_publicacao": evento.get("data_publicacao"),
        "revisao_humana": "pendente" if status == "candidato_fila_editor" else None,
        "publicado": False,
        "auditoria_status": audit,
        "prioridade_exposicao": prioridade,
        "comentarios_habilitados": False,
        "requer_conferencia_manual": not bool(trecho and evento.get("fonte_url")),
    }


def gerar_ficha_html(resultado: dict[str, Any]) -> str:
    """Gera ficha HTML neutra para integração com a interface/portal.

    A função não publica nem grava no banco. Escape de HTML protege conteúdo
    extraído de documentos oficiais que possa conter marcação inesperada.
    """
    if resultado.get("status_triagem") != "candidato_fila_editor":
        raise ValueError("somente candidatos aprovados pelos gates podem virar ficha")
    audit = resultado.get("auditoria_status") or {}
    valor_multa = audit.get("valor_multa")
    multa = escape(str(valor_multa)) if valor_multa is not None else "Não localizado"
    dias = audit.get("dias_desde_ultima_movimentacao")
    dias_label = f"{dias} dias desde a última movimentação registrada" if dias is not None else "Data da última movimentação não localizada"
    trecho = escape(str(resultado.get("trecho_literal_fiscal") or "Trecho fiscal não localizado"))
    processo = escape(str(resultado.get("numero_processo") or "Não localizado"))
    empresa = escape(str(resultado.get("razao_social_empreendedor") or "Não localizado"))
    orgao = escape(str(resultado.get("orgao_origem") or "Não localizado"))
    atividade = escape(str(resultado.get("atividade_direta") or resultado.get("cnae_enquadrado") or "Não localizada"))
    return (
        '<article class="ficha-impacto">'
        f'<h2>Processo {processo}</h2>'
        f'<p>Empreendedor: {empresa} · Órgão: {orgao}</p>'
        f'<p>Atividade direta identificada: {atividade}</p>'
        '<h3>Trecho literal do relatório de fiscalização</h3>'
        f'<blockquote>{trecho}</blockquote>'
        f'<p>Valor de multa aplicada: {multa}</p>'
        f'<p>{escape(dias_label)}.</p>'
        '<p class="nota-editorial">Ficha técnica gerada a partir de documento oficial; requer validação editorial.</p>'
        '</article>'
    )

"""
Módulo 8 — campos ESTRUTURADOS do comunicado de acidente ambiental (SEMAD/NEA).

O comunicado oficial tem cabeçalho rotulado e regular ("MODALIDADE DO ACIDENTE:", "LOCAL:", "MUNICÍPIO:",
"DATA/HORA DA OCORRÊNCIA:" ...). Este módulo lê SÓ esses rótulos, de forma determinística (sem IA, sem requisição):

- um campo só é preenchido quando o rótulo foi encontrado e o valor passa na validação do seu tipo
  (data real, nº ONU de 4 dígitos, rodovia/km reconhecíveis). Valor duvidoso => None, nunca chute;
- o texto livre da descrição NÃO vira fato confirmado aqui. Vítimas, curso d'água atingido, evacuação etc. continuam
  fora das colunas booleanas (essas colunas são lidas como "confirmado em campo estruturado" pela régua de
  criticidade). A leitura da narrativa é devolvida à parte, em `indicios_narrativos`, só para a revisão humana,
  com o estado afirmado/incerto/negado de cada menção;
- horários são de Brasília (UTC-3, Minas não tem horário de verão desde 2019).
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

FUSO_BRASILIA = timezone(timedelta(hours=-3))

# rótulos na ordem em que aparecem no comunicado; o valor de um rótulo vai até o início do próximo rótulo achado
_ROTULOS = [
    ("protocolo", r"N[º°o]?\s*Protoc[o0]l[o0]\s*[:;.\-]?"),
    ("modalidade", r"MODALIDADE\s+DO\s+ACIDENTE\s*[:;]"),
    ("local", r"LOCAL\s*[:;]"),
    ("municipio", r"MUNIC[IÍ]PIO\s*[:;]"),
    ("data_ocorrencia", r"DATA\s*/\s*HORA\s+DA\s+OCORR[EÊ]NCIA\s*[:;]"),
    ("data_comunicado", r"DATA\s*/\s*HORA\s+DO\s+COMUNICADO(?:\s+AO\s+NEA)?\s*[:;]"),
    ("fonte", r"FONTE\s*\(?S?\)?\s+DE\s+INFORMA[CÇ][OÕ]ES\s*[:;]"),
    ("descricao", r"BREVE\s+DESCRI[CÇ][AÃ]O\s+DA\s+OCORR[EÊ]NCIA\s*[:;]"),
    ("produto", r"PRODUTO\s*[:;]"),
    ("onu", r"N[ÚU]MERO\s+ONU\s*[:;]"),
    ("classe", r"CLASSE\s+DE\s+RISCO\s*[:;]"),
    ("rodape", r"N[ÚU]CLEO\s+DE\s+PREVEN[CÇ][AÃ]O\s+E\s+EMERG[EÊ]NCIA\s+AMBIENTAL"),
]
# Rótulos em MAIÚSCULAS (como no documento impresso): "produto:" ou "local:" dentro da narrativa não pode ser tomado
# como rótulo. O protocolo ("Nº Protocolo:") e o rodapé do núcleo aceitam caixa mista.
_RE_ROTULOS = [(nome, re.compile(padrao, re.IGNORECASE if nome in ("protocolo", "rodape") else 0)) for nome, padrao in _ROTULOS]
_VAZIOS = {"", "-", "--", "---", "—", "n/a", "na", "n/d", "nd", "não informado", "nao informado"}


def _segmentar(texto: str) -> dict:
    """{rótulo: valor_bruto}. Procura cada rótulo uma vez (a primeira ocorrência após o rótulo anterior)."""
    achados = []
    posicao = 0
    for nome, rx in _RE_ROTULOS:
        m = rx.search(texto, posicao)
        if m:
            achados.append((nome, m.start(), m.end()))
            posicao = m.end()
    saida = {}
    for i, (nome, _ini, fim) in enumerate(achados):
        limite = achados[i + 1][1] if i + 1 < len(achados) else len(texto)
        saida[nome] = texto[fim:limite]
    return saida


def _limpar(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    v = " ".join(valor.replace("|", " ").split()).strip(" ;:-")
    return None if v.lower() in _VAZIOS else v


def _data_hora(valor: Optional[str]) -> Optional[datetime]:
    """'29/08/2026 - 16:30:00' (hora opcional) -> datetime com fuso de Brasília; data inexistente => None."""
    if not valor:
        return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s*[-–—,]?\s*(\d{1,2})[:h](\d{2})(?::(\d{2}))?)?", valor)
    if not m:
        return None
    d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h = int(m.group(4)) if m.group(4) else 0
    mi = int(m.group(5)) if m.group(5) else 0
    s = int(m.group(6)) if m.group(6) else 0
    try:
        return datetime(a, mes, d, h, mi, s, tzinfo=FUSO_BRASILIA)
    except ValueError:
        return None


_RE_RODOVIA = re.compile(r"\b(BR|MGC|AMG|LMG|MG|CMG|ALMG)\s*[-\s]?\s*(\d{2,4})\b", re.IGNORECASE)
_RE_KM = re.compile(r"\bkm\s*[:.]?\s*(\d{1,4}(?:[.,]\d{1,3})?)\b", re.IGNORECASE)


def _rodovia_km(local: Optional[str]) -> tuple:
    if not local:
        return None, None
    r = _RE_RODOVIA.search(local)
    k = _RE_KM.search(local)
    rodovia = f"{r.group(1).upper()}-{r.group(2)}" if r else None
    km = k.group(1).replace(",", ".") if k else None
    return rodovia, km


def _onu(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", valor)
    return m.group(1) if m else None


def _classe(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    m = re.match(r"\s*([1-9](?:\.\d)?)(?![\d\w])", valor)
    return m.group(1) if m else None


# ----------------------------------------------------------------------------
# Narrativa: só indício para revisão humana (NUNCA preenche coluna "confirmada")
# ----------------------------------------------------------------------------
_TEMAS = {
    "curso_dagua": r"c[óo]rrego|rio\b|ribeir[ãa]o|c[óo]rrego|curso\s+d['’]?\s*[áa]gua|drenagem|lago|lagoa|represa|nascente|leito",
    "vitimas": r"v[ií]tima|[óo]bito|morte\b|morreu|ferid[oa]s?|fatal",
    "evacuacao": r"evacua|desaloj|retirad[ao]s?\s+(?:de\s+)?(?:suas\s+)?(?:casas|resid)",
    "bloqueio_via": r"interdi|bloque(?:io|ad)|via\s+fechada",
    "solo": r"\bsolo\b",
    "incendio": r"incendi|fogo|explos",
}
_INCERTEZA = re.compile(r"possibilidade|poss[ií]vel|poss[ií]vel\s+que|pode(?:ria|m)?\s+ter|risco\s+de|suspeit|em\s+apura|"
                        r"ainda\s+n[ãa]o|n[ãa]o\s+(?:se\s+)?(?:sabe|h[áa]\s+informa)|sem\s+informa", re.IGNORECASE)
_NEGACAO = re.compile(r"\bsem\b|\bn[ãa]o\b|nenhum|n[ãa]o\s+foi|inexist|aus[êe]ncia", re.IGNORECASE)


def _indicios_narrativos(descricao: Optional[str]) -> dict:
    """{tema: 'afirmado'|'incerto'|'negado'}, só para os temas mencionados; por frase, o pior caso prevalece
    (incerto > negado > afirmado) quando o mesmo tema aparece em frases diferentes com sentidos diferentes."""
    if not descricao:
        return {}
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", descricao.replace("\n", " ")) if f.strip()]
    saida = {}
    ordem = {"afirmado": 0, "negado": 1, "incerto": 2}
    for tema, padrao in _TEMAS.items():
        rx = re.compile(padrao, re.IGNORECASE)
        for frase in frases:
            m = rx.search(frase)
            if not m:
                continue
            if _INCERTEZA.search(frase):
                estado = "incerto"
            elif _NEGACAO.search(frase[:m.start()]) or _NEGACAO.search(frase[m.end():m.end() + 25]):
                estado = "negado"
            else:
                estado = "afirmado"
            if tema not in saida or ordem[estado] > ordem[saida[tema]]:
                saida[tema] = estado
    return saida


def extrair_campos(texto: Optional[str]) -> dict:
    """Campos do cabeçalho do comunicado. Sempre devolve todas as chaves (None quando ausente/duvidoso), mais
    `campos_lidos` (quantos campos de cabeçalho vieram preenchidos) e `cabecalho_reconhecido` (True se achou o
    rótulo de modalidade E a data/hora da ocorrência — o mínimo para tratar o texto como comunicado legível)."""
    texto = texto or ""
    seg = _segmentar(texto)
    ocorrencia = _data_hora(_limpar(seg.get("data_ocorrencia")))
    comunicado = _data_hora(_limpar(seg.get("data_comunicado")))
    atraso = None
    if ocorrencia and comunicado and comunicado >= ocorrencia:
        atraso = int((comunicado - ocorrencia).total_seconds() // 60)
    local = _limpar(seg.get("local"))
    rodovia, km = _rodovia_km(local)
    descricao = _limpar(seg.get("descricao"))
    campos = {
        "protocolo_lido": _limpar(seg.get("protocolo")),
        "modalidade": _limpar(seg.get("modalidade")),
        "local_descrito": local,
        "rodovia": rodovia,
        "km": km,
        "municipio": _limpar(seg.get("municipio")),
        "data_hora_ocorrencia": ocorrencia.isoformat() if ocorrencia else None,
        "data_hora_comunicacao": comunicado.isoformat() if comunicado else None,
        "atraso_comunicacao_minutos": atraso,
        "fonte_informacao": _limpar(seg.get("fonte")),
        "descricao_literal": descricao,
        "produto": _limpar(seg.get("produto")),
        "numero_onu": _onu(_limpar(seg.get("onu"))),
        "classe_risco": _classe(_limpar(seg.get("classe"))),
    }
    campos["indicios_narrativos"] = _indicios_narrativos(descricao)
    chaves_cab = ("modalidade", "local_descrito", "municipio", "data_hora_ocorrencia", "data_hora_comunicacao",
                  "produto", "descricao_literal")
    campos["campos_lidos"] = sum(1 for k in chaves_cab if campos[k])
    campos["cabecalho_reconhecido"] = bool(campos["modalidade"] and campos["data_hora_ocorrencia"])
    return campos


# colunas de m8_acidentes_detalhe que este módulo pode preencher (nenhuma é booleana de fato "confirmado")
COLUNAS_DETALHE = ("modalidade", "local_descrito", "rodovia", "km", "data_hora_ocorrencia", "data_hora_comunicacao",
                   "atraso_comunicacao_minutos", "descricao_literal", "produto", "numero_onu", "classe_risco")


def para_detalhe(campos: dict) -> dict:
    """Só os campos preenchidos, prontos para o upsert em m8_acidentes_detalhe (não sobrescreve com None)."""
    return {k: campos[k] for k in COLUNAS_DETALHE if campos.get(k) not in (None, "")}

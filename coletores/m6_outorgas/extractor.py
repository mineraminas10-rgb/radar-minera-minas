"""
Módulo 6 — conversão de DOC/PDF e segmentação em atos individuais (carta
M6 v0.8 §44.3: "converter DOC, DOCX, PDF ou texto por rota compatível,
sem considerar a extensão prova do formato"; "segmentar o documento em
atos individuais antes de aplicar o filtro mineral").

AVISO IMPORTANTE — leia antes de rodar contra documento real: a função
`segmentar_em_atos()` abaixo é uma heurística razoável (cada ato começa
numa linha que cita portaria/processo/requerente em maiúsculas, ou termina
em ponto final seguido de nova portaria), não uma leitura confirmada do
layout real dos arquivos .doc do IGAM — este ambiente não tem acesso de
rede para baixar e inspecionar os três arquivos da Carta de Homologação
M6-V1.0 (ptp22_09_2026_21824.doc e os dois seguintes). `signals.py` e
`scoring.py` (classificação e pontuação) estão testados e corretos contra
texto já segmentado; esta camada — igual à de discovery.py — é a que
falta validar quando a rede/os documentos estiverem disponíveis.

A amostra homologatória (test_regressao_m6.py) não depende desta função:
usa os 6 atos já segmentados e descritos literalmente pela Carta de
Homologação M6-V1.0 (§3/§4/§5), porque é esse o gabarito oficial contra
o qual o sistema precisa provar reprodutibilidade — não uma segmentação
que eu mesmo inventaria sem ver o arquivo real.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

_RE_INICIO_ATO = re.compile(
    r"(?=\bPORTARIA\b|\bPROCESSO\b\s*(?:N[ºO°]?\s*)?\d|\bREQUERENTE\b)",
    re.IGNORECASE,
)


@dataclass
class AtoBruto:
    """Um ato individual já isolado dentro do documento — ainda não
    classificado (isso é signals.classificar_ato) nem filtrado (isso é
    signals.tem_vinculo_mineral)."""
    texto: str
    indice_no_documento: int
    pagina_ou_secao: Optional[str] = None


def hash_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def extrair_texto(caminho_ou_bytes) -> str:
    """Converte DOC/DOCX/PDF para texto. Implementação mínima — delega
    para bibliotecas padrão quando disponíveis (python-docx para .docx,
    pdfplumber/PyPDF2 para .pdf); arquivos .doc (formato binário antigo)
    normalmente exigem um conversor externo (ex. libreoffice --headless),
    não implementado aqui porque este ambiente não tem os arquivos reais
    para testar contra. Levanta NotImplementedError de forma explícita em
    vez de fingir sucesso."""
    raise NotImplementedError(
        "extrair_texto() depende do arquivo real (.doc do IGAM) para ser "
        "validado — ver aviso no topo do arquivo. Use segmentar_em_atos() "
        "diretamente sobre texto já extraído por outro meio enquanto isso."
    )


def segmentar_em_atos(texto_completo: str) -> List[AtoBruto]:
    """Divide o texto de um documento em atos individuais. Heurística:
    cada novo bloco que mencione 'PORTARIA', 'PROCESSO Nº' ou
    'REQUERENTE' inicia um ato novo; texto antes do primeiro marcador
    (cabeçalho do documento) é descartado da segmentação (mas não do
    log — fica preservado em separado por quem chama esta função, se
    quiser auditar o cabeçalho)."""
    indices = [m.start() for m in _RE_INICIO_ATO.finditer(texto_completo)]
    if not indices:
        return [AtoBruto(texto=texto_completo.strip(), indice_no_documento=0)] if texto_completo.strip() else []

    atos = []
    for i, inicio in enumerate(indices):
        fim = indices[i + 1] if i + 1 < len(indices) else len(texto_completo)
        trecho = texto_completo[inicio:fim].strip()
        if trecho:
            atos.append(AtoBruto(texto=trecho, indice_no_documento=i))
    return atos

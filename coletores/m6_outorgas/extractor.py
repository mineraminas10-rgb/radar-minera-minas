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
from pathlib import Path
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


def detectar_formato(conteudo: bytes) -> str:
    """Formato REAL pelos primeiros bytes — a extensão do arquivo não prova o formato (carta §44.3)."""
    if conteudo[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole2"          # .doc (Word 97-2003)
    if conteudo[:4] == b"PK\x03\x04":
        return "zip"           # .docx
    if conteudo[:5] == b"%PDF-":
        return "pdf"
    if conteudo.lstrip()[:5].lower() in (b"<html", b"<!doc"):
        return "html"
    return "texto"


def _soffice_para_texto(conteudo: bytes, sufixo: str, timeout: int = 180) -> str:
    """Converte .doc/.docx para texto UTF-8 com o LibreOffice (instalado no runner do GitHub Actions)."""
    import os
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("LibreOffice (soffice) não está instalado neste ambiente — necessário para ler arquivos .doc")
    with tempfile.TemporaryDirectory() as pasta:
        origem = os.path.join(pasta, "documento" + sufixo)
        with open(origem, "wb") as f:
            f.write(conteudo)
        perfil = "file://" + os.path.join(pasta, "perfil")
        r = subprocess.run([exe, f"-env:UserInstallationDir={perfil}", "--headless", "--convert-to",
                            "txt:Text (encoded):UTF8", "--outdir", pasta, origem],
                           capture_output=True, text=True, timeout=timeout)
        destino = os.path.join(pasta, "documento.txt")
        if not os.path.exists(destino):
            raise RuntimeError(f"LibreOffice não gerou o texto (código {r.returncode}): {(r.stderr or r.stdout)[:200]}")
        with open(destino, "rb") as f:
            return f.read().decode("utf-8", "replace").lstrip("\ufeff")


def extrair_texto(caminho_ou_bytes) -> str:
    """Converte DOC/DOCX/PDF/HTML/texto para texto puro, escolhendo o conversor pelo formato REAL do arquivo.
    Falha de conversão levanta erro explícito (nunca devolve texto vazio fingindo sucesso)."""
    if isinstance(caminho_ou_bytes, (str, Path)):
        conteudo = Path(caminho_ou_bytes).read_bytes()
    else:
        conteudo = bytes(caminho_ou_bytes)
    formato = detectar_formato(conteudo)
    if formato == "ole2":
        return _soffice_para_texto(conteudo, ".doc")
    if formato == "zip":
        return _soffice_para_texto(conteudo, ".docx")
    if formato == "pdf":
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    if formato == "html":
        from bs4 import BeautifulSoup
        return BeautifulSoup(conteudo, "html.parser").get_text("\n")
    return conteudo.decode("utf-8", "replace") if _e_utf8(conteudo) else conteudo.decode("cp1252", "replace")


def _e_utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ----------------------------------------------------------------------------
# Segmentação em atos (carta §44.3: "segmentar o documento em atos individuais antes de aplicar o filtro
# mineral"). Dois layouts reais observados nos arquivos do IGAM (10/10/2026):
#   (A) PORTARIA COMPLETA:  "Portaria nº 00020/2026 de 01/10/2026 – Renovação da Portaria nº 00260/2021"
#       seguida de "Processo:", "Decisão:", "Empreendimento:", "Municípios:", "Finalidade:" ... (um ato por portaria)
#   (B) PUBLICAÇÕES CURTAS: "PUBLICAÇÃO DE RETIFICAÇÃO - 17/09/2026" / "PUBLICAÇÃO DE ANULAÇÃO - 07/10/2026",
#       um subtítulo terminado em ":" ("Retificação:") e um parágrafo por ato.
# Documento fora desses dois layouts devolve ZERO atos — o coletor registra isso, não inventa segmentação.
# ----------------------------------------------------------------------------
_RE_PORTARIA_COMPLETA = re.compile(
    r"^\s*Portaria\s+n[º°o]\s*([\d./]+)\s+de\s+(\d{2}/\d{2}/\d{4})\s*(?:[–—-]\s*(.*))?$", re.IGNORECASE)
_RE_PUBLICACAO = re.compile(r"^\s*PUBLICA[ÇC][ÃA]O\s+DE\s+(.+?)\s*[-–—]\s*(\d{2}/\d{2}/\d{4})\s*$", re.IGNORECASE)
_RE_CAMPO = re.compile(r"^\s*([A-Za-zÀ-ÿ' ]{3,40}?)\s*:\s*(.*)$")
_RE_PORTARIA_NUM = re.compile(r"Portaria\s+n[º°o]\s*(\d[\d./]*\d|\d)", re.IGNORECASE)
# "Arquiva-se o processo nº. 08148 de 08/08/2025." — com ponto depois do "nº" e a data do processo logo depois
_RE_PROCESSO_NUM = re.compile(r"Processo\s+n?[º°o]?\s*[.:]?\s*(\d[\d./-]*\d)(?:\s+de\s+\d{2}/\d{2}/(\d{4}))?", re.IGNORECASE)


@dataclass
class AtoIgam:
    """Ato já segmentado e com os campos que o texto traz LITERALMENTE (nada inferido por nome de empresa)."""
    layout: str                       # 'portaria_completa' | 'publicacao_curta'
    tipo_publicacao: str              # rótulo do documento ("RETIFICAÇÃO", "Renovação da Portaria…") — NÃO classifica o ato
    processo_ou_portaria: str
    titular: str
    municipio: Optional[str]
    data_decisao: Optional[str]       # dd/mm/aaaa
    trecho_decisorio: str             # texto literal de onde sai o verbo decisório
    texto_para_vinculo: str           # texto usado no filtro mineral: SEM nome do titular/CNPJ (nome não decide)
    finalidade_uso: Optional[str] = None
    indice_no_documento: int = 0


def _limpar(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _ponto_final(s: str) -> str:
    return s.strip().rstrip(".").strip()


def _sem_titular_e_cnpj(texto: str, titular: str) -> str:
    t = texto
    if titular:
        t = t.replace(titular, " ")
    t = re.sub(r"\b(CNPJ|CPF)\s*:?\s*[\d./*-]+", " ", t, flags=re.IGNORECASE)
    return _limpar(t)


def _campos_do_bloco(linhas: List[str]) -> dict:
    campos = {}
    for ln in linhas:
        m = _RE_CAMPO.match(ln)
        if m:
            chave = _limpar(m.group(1)).lower()
            campos.setdefault(chave, _limpar(m.group(2)))
    return campos


def _segmentar_portarias_completas(linhas: List[str]) -> List[AtoIgam]:
    inicios = [i for i, ln in enumerate(linhas) if _RE_PORTARIA_COMPLETA.match(ln)]
    atos = []
    for n, ini in enumerate(inicios):
        fim = inicios[n + 1] if n + 1 < len(inicios) else len(linhas)
        bloco = linhas[ini:fim]
        m = _RE_PORTARIA_COMPLETA.match(bloco[0])
        numero, data, subtitulo = m.group(1), m.group(2), _limpar(m.group(3) or "")
        campos = _campos_do_bloco(bloco[1:40])    # os campos de cabeçalho ficam nas primeiras linhas
        decisao = campos.get("decisão") or campos.get("decisao") or ""
        art1 = ""
        for ln in bloco:     # "Art. 1º - Autorizar, ..." costuma vir no mesmo parágrafo do preâmbulo
            ma = re.search(r"Art\.?\s*1\s*[º°o]?.*", ln, re.IGNORECASE)
            if ma:
                art1 = _limpar(ma.group(0))[:700]
                break
        trecho = _limpar(f"{decisao} {art1}")[:1500]
        titular = campos.get("empreendimento") or campos.get("requerente") or campos.get("usuário") or ""
        municipio = campos.get("municípios") or campos.get("municípios do empreendimento") or campos.get("município")
        if municipio:
            municipio = _ponto_final(re.sub(r"\s*[-–—]\s*MG\s*$", "", _ponto_final(municipio)))
        finalidade = campos.get("finalidade")
        modos = campos.get("modos de usos") or campos.get("modo de uso") or ""
        atos.append(AtoIgam(
            layout="portaria_completa", tipo_publicacao=subtitulo or "Portaria",
            processo_ou_portaria=f"portaria-{numero}", titular=_ponto_final(titular) or "(titular não identificado)",
            municipio=municipio or None, data_decisao=data, trecho_decisorio=trecho,
            texto_para_vinculo=_limpar(f"{finalidade or ''} {modos}"), finalidade_uso=finalidade,
            indice_no_documento=n))
    return atos


def _segmentar_publicacoes_curtas(linhas: List[str]) -> List[AtoIgam]:
    atos, n = [], 0
    atual = None            # (rotulo, data)
    for ln in linhas:
        m = _RE_PUBLICACAO.match(ln)
        if m:
            atual = (_limpar(m.group(1)), m.group(2))
            continue
        if atual is None:
            continue
        texto = _limpar(ln)
        if not texto or (texto.endswith(":") and len(texto) < 80) or len(texto) < 25:
            continue                                     # subtítulo ("Retificação:") ou linha vazia
        rotulo, data = atual
        # número da portaria: em retificação vale o "Leia-se" (o dado corrigido)
        base = texto.split("Leia-se", 1)[1] if "Leia-se" in texto else texto
        mp = _RE_PORTARIA_NUM.search(base) or _RE_PORTARIA_NUM.search(texto)
        mpr = _RE_PROCESSO_NUM.search(base) or _RE_PROCESSO_NUM.search(texto)
        if mp:
            chave = f"portaria-{mp.group(1).rstrip('.')}"
        elif mpr:
            numero_proc = mpr.group(1)
            if mpr.group(2) and "/" not in numero_proc:
                numero_proc = f"{numero_proc}/{mpr.group(2)}"      # número do processo + ano (o número sozinho repete entre anos)
            chave = f"processo-{numero_proc}"
        else:
            chave = "ato-" + hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]
        mt = re.search(r"(?:Usu[aá]rios?|Requerentes?|Empreendimento|Outorgad[oa]s?)\s*:\s*(.+?)(?:\s*[.,]?\s*(?:CNPJ|CPF)\b|\.\s+(?:Curso|Motivo|Munic))",
                       base, re.IGNORECASE)
        titular = _ponto_final(mt.group(1)) if mt else ""
        mm = re.search(r"Munic[ií]pios?\s*:\s*(.+?)\s*[-–—]\s*MG", texto, re.IGNORECASE)
        municipio = _ponto_final(mm.group(1)) if mm else None
        atos.append(AtoIgam(
            layout="publicacao_curta", tipo_publicacao=rotulo, processo_ou_portaria=chave,
            titular=titular or "(titular não identificado)", municipio=municipio, data_decisao=data,
            trecho_decisorio=texto[:1500], texto_para_vinculo=_sem_titular_e_cnpj(texto, titular),
            indice_no_documento=n))
        n += 1
    return atos


def segmentar_documento(texto: str) -> List[AtoIgam]:
    """Segmenta o texto de UM documento do IGAM em atos individuais (ver layouts no cabeçalho da seção)."""
    linhas = [ln.rstrip() for ln in (texto or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    linhas = [ln.lstrip("\ufeff") for ln in linhas]
    completas = _segmentar_portarias_completas(linhas)
    curtas = _segmentar_publicacoes_curtas(linhas)
    return completas + curtas


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

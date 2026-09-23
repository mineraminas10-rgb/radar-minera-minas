"""
Módulo 8 — extração de texto do documento do comunicado (Carta M8 §5 passos
4-6, §16 tratamento de falhas).

Tenta texto nativo primeiro (pdfplumber). Se a página não trouxer texto
útil (documento é imagem escaneada), renderiza e aplica OCR (pdf2image +
pytesseract), conforme manda a carta.

Requer o binário `tesseract-ocr` instalado no ambiente de execução (no
GitHub Actions: `apt-get install -y tesseract-ocr tesseract-ocr-por`).

Igual ao discovery.py: não testado contra um documento real (sandbox sem
acesso à rede). A lógica de fallback nativo->OCR e o cálculo de hash são
puros/testáveis sem rede — ver test_extractor.py.
"""
import hashlib
from dataclasses import dataclass
from typing import Optional
import requests


@dataclass
class ResultadoExtracao:
    texto: str
    metodo_extracao: str  # 'nativo' | 'ocr'
    qualidade_ocr: Optional[str]  # None quando nativo; 'boa'|'ruim'|'parcial' quando ocr
    paginas_processadas: int
    hash_documento: str
    status_processamento: str  # 'processado' | 'pendente_revisao_manual' | 'falha_extracao'
    motivo_falha: Optional[str] = None


def baixar_documento(url: str, session: Optional[requests.Session] = None, timeout: int = 60) -> bytes:
    s = session or requests.Session()
    resp = s.get(url, timeout=timeout, headers={
        "User-Agent": "RadarDigitalMineraMinas/1.0 (+coletor M8; contato: Rapha)"
    })
    resp.raise_for_status()
    return resp.content


def hash_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def extrair_texto_nativo(pdf_bytes: bytes) -> Optional[str]:
    """Retorna None quando não há texto nativo útil (ex.: PDF de imagem
    escaneada sem camada de texto) — carta §5 passo 5: 'quando não houver
    texto útil, renderizar o documento e aplicar OCR'."""
    import pdfplumber
    import io
    textos = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            textos.append(t)
    texto_completo = "\n".join(textos).strip()
    # heurística simples de "texto útil": tem que ter um mínimo de
    # caracteres alfabéticos, senão é provável que seja lixo/():espaços
    letras = sum(c.isalpha() for c in texto_completo)
    if letras < 50:
        return None
    return texto_completo


def extrair_texto_ocr(pdf_bytes: bytes, idioma: str = "por") -> tuple:
    """Retorna (texto, qualidade_ocr, paginas_processadas)."""
    from pdf2image import convert_from_bytes
    import pytesseract

    imagens = convert_from_bytes(pdf_bytes, dpi=300)
    textos = []
    confiancas = []
    for img in imagens:
        dados = pytesseract.image_to_data(img, lang=idioma, output_type=pytesseract.Output.DICT)
        confs = [int(c) for c in dados["conf"] if c not in ("-1", -1)]
        if confs:
            confiancas.append(sum(confs) / len(confs))
        textos.append(pytesseract.image_to_string(img, lang=idioma))

    texto_completo = "\n".join(textos).strip()
    confianca_media = sum(confiancas) / len(confiancas) if confiancas else 0
    if confianca_media >= 70:
        qualidade = "boa"
    elif confianca_media >= 40:
        qualidade = "parcial"
    else:
        qualidade = "ruim"
    return texto_completo, qualidade, len(imagens)


def extrair(url_documento: str, session: Optional[requests.Session] = None) -> ResultadoExtracao:
    """Fluxo completo carta §5 passos 4-6 + §16 tratamento de falhas.
    Documento não abre -> status_processamento='falha_extracao', preserva
    alerta básico (carta §16) em vez de descartar o evento."""
    try:
        conteudo = baixar_documento(url_documento, session=session)
    except Exception as e:
        return ResultadoExtracao(
            texto="", metodo_extracao="nativo", qualidade_ocr=None,
            paginas_processadas=0, hash_documento="",
            status_processamento="falha_extracao",
            motivo_falha=f"documento não abriu: {e}",
        )

    hash_doc = hash_bytes(conteudo)

    texto_nativo = None
    try:
        texto_nativo = extrair_texto_nativo(conteudo)
    except Exception:
        texto_nativo = None  # cai para OCR

    if texto_nativo:
        return ResultadoExtracao(
            texto=texto_nativo, metodo_extracao="nativo", qualidade_ocr=None,
            paginas_processadas=texto_nativo.count("\x0c") + 1,  # aproximação
            hash_documento=hash_doc, status_processamento="processado",
        )

    try:
        texto_ocr, qualidade, paginas = extrair_texto_ocr(conteudo)
    except Exception as e:
        return ResultadoExtracao(
            texto="", metodo_extracao="ocr", qualidade_ocr=None,
            paginas_processadas=0, hash_documento=hash_doc,
            status_processamento="falha_extracao",
            motivo_falha=f"OCR falhou: {e}",
        )

    if not texto_ocr.strip():
        return ResultadoExtracao(
            texto="", metodo_extracao="ocr", qualidade_ocr="ruim",
            paginas_processadas=paginas, hash_documento=hash_doc,
            status_processamento="pendente_revisao_manual",
            motivo_falha="OCR não produziu texto legível",
        )

    return ResultadoExtracao(
        texto=texto_ocr, metodo_extracao="ocr", qualidade_ocr=qualidade,
        paginas_processadas=paginas, hash_documento=hash_doc,
        status_processamento="processado" if qualidade != "ruim" else "pendente_revisao_manual",
    )

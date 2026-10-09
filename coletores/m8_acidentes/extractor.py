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


def _processar_pdf(conteudo: bytes) -> ResultadoExtracao:
    """Texto nativo -> OCR (Carta §5 passos 5-6) sobre os bytes de um PDF já baixado."""
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


MAX_DOCUMENTOS_POR_COMUNICADO = 5
MIN_CARACTERES_PAGINA = 200


def _html_para_texto(html_bytes: bytes) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        t.decompose()
    return "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())


def _falha(motivo: str, metodo: str = "nativo") -> ResultadoExtracao:
    return ResultadoExtracao(texto="", metodo_extracao=metodo, qualidade_ocr=None, paginas_processadas=0,
                             hash_documento="", status_processamento="falha_extracao", motivo_falha=motivo)


def extrair(url_documento: str, session: Optional[requests.Session] = None, acessador=None) -> ResultadoExtracao:
    """Fluxo Carta §5 passos 4-6 + §16 + roteamento de fontes.
    - `url_documento` pode ser um PDF direto OU a página individual do comunicado (HTML). Na página, o
      conteúdo textual é lido, os anexos (PDF) são inventariados (reprodutível, até MAX_DOCUMENTOS_POR_COMUNICADO)
      e abertos; nada é classificado só por título/município.
    - Barreira de acesso (CAPTCHA/401/403/429): para, registra e devolve falha_extracao com motivo
      'barreira_de_acesso:...' — nunca contorna e nunca pede à IA que invente o conteúdo.
    - Documento não abre -> status_processamento='falha_extracao' (alerta básico preservado, Carta §16)."""
    ctype, pagina_html, resposta = "application/pdf", None, None
    try:
        if acessador is not None:
            resposta = acessador.get(url_documento, metodo_acesso="m8_documento")
            conteudo, ctype = resposta.corpo, resposta.content_type
        else:
            conteudo = baixar_documento(url_documento, session=session)
    except Exception as e:
        from acesso import BarreiraDeAcesso, AcessoInterrompido
        if isinstance(e, BarreiraDeAcesso):
            return _falha(f"barreira_de_acesso:{e.motivo}")
        if isinstance(e, AcessoInterrompido):
            return _falha(f"{e.resultado}:{e.motivo}")
        return _falha(f"documento não abriu: {e}")

    if not (ctype.startswith("text/html") or ctype == "application/xhtml+xml"):
        return _processar_pdf(conteudo)

    # ---- página individual (HTML): texto da página + anexos ----
    from acesso import inventariar_links, BarreiraDeAcesso, AcessoInterrompido, sha256
    texto_pagina = _html_para_texto(conteudo)
    hash_pagina = sha256(conteudo)
    base = resposta.url_final if resposta is not None else url_documento
    anexos = [l for l in inventariar_links(conteudo.decode("utf-8", "replace"), base)
              if l["extensao"] == ".pdf"][:MAX_DOCUMENTOS_POR_COMUNICADO]
    textos, hashes, paginas, metodo, qualidade, status = [], [hash_pagina], 0, "nativo", None, "processado"
    falhas = []
    for l in anexos:
        try:
            r = acessador.get(l["url"], metodo_acesso="m8_anexo") if acessador is not None else None
            if r is None:
                break
            res = _processar_pdf(r.corpo)
        except BarreiraDeAcesso as e:
            falhas.append(f"barreira_de_acesso:{e.motivo}@{l['url']}")
            continue
        except AcessoInterrompido as e:
            falhas.append(f"{e.resultado}:{e.motivo}@{l['url']}")
            continue
        if res.texto:
            textos.append(res.texto)
        hashes.append(res.hash_documento)
        paginas += res.paginas_processadas or 0
        if res.metodo_extracao == "ocr":
            metodo, qualidade = "ocr", res.qualidade_ocr
        if res.status_processamento != "processado":
            status = "pendente_revisao_manual"
    if not textos and len(texto_pagina) < MIN_CARACTERES_PAGINA:
        return _falha("página individual sem texto suficiente e sem documento associado legível"
                      + (f" ({'; '.join(falhas)})" if falhas else ""))
    texto = "\n\n".join([texto_pagina] + textos).strip()
    return ResultadoExtracao(
        texto=texto, metodo_extracao=metodo, qualidade_ocr=qualidade,
        paginas_processadas=paginas or 1, hash_documento=sha256("|".join(hashes).encode()),
        status_processamento=status, motivo_falha=("; ".join(falhas) or None),
    )

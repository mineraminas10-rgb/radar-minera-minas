"""
Módulo 8 — descoberta na página anual da SEMAD (Carta Operacional M8 §3/§4/§5
passos 1-3).

VALIDADO contra o HTML real da página (salvo em 10/10/2026, 20 itens, "Exibindo
1 - 20 de 190 resultados"). A página é uma biblioteca de documentos do Liferay,
renderizada no servidor (não depende de JavaScript). Cada comunicado é um cartão:

    <dd class="card-page-item card-page-item-asset" data-title="Comunicado de Acidente - Caeté/MG - 04/10/2026">
        <input type="checkbox" value="10236593">                  <- id do arquivo (estável e único)
        <img src=".../Emergência ambiental 204_2026.png">          <- o NÚMERO DO PROTOCOLO está no nome da imagem
        <a class="card-title" href=".../view_file/10236593?...">Comunicado de Acidente - Caeté/MG - 04/10/2026</a>

Consequências importantes:
- o título NÃO traz o protocolo; traz município e (quase sempre) a data do acidente. Um cartão
  ("Serra do Salitre/MG") veio sem data — a data fica vazia, nunca inventada;
- o protocolo (ex.: 204/2026) vem do nome da imagem de pré-visualização. Se um cartão vier sem esse
  nome, o protocolo vira "arq<id do arquivo>" (identificador estável, marcado em `protocolo_origem`),
  em vez de descartar o comunicado;
- a página tem 20 itens por vez; as demais páginas são ligadas por `curEntry=N` (`urls_outras_paginas`);
- o documento do comunicado é uma IMAGEM (PNG) — a leitura é por OCR (ver extractor.py).
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, unquote
import requests
from bs4 import BeautifulSoup

URL_PAGINA_ANUAL = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"

SELETOR_ITEM_LISTA = "dd.card-page-item-asset, dd[data-qa-id='row']"   # um cartão por comunicado (Liferay)
SELETOR_TITULO = "a.card-title"
SELETOR_IMAGEM = "img"
SELETOR_ID_ARQUIVO = "input[type=checkbox][value]"


@dataclass
class ItemInventario:
    protocolo: str
    ano: int
    titulo_fonte: str
    municipio: Optional[str]
    data_publicada: Optional[str]  # texto cru da data como aparece no título (dd/mm/aaaa) — pode faltar
    url_detalhe: str
    hash_linha: str  # hash do conteúdo textual do cartão, para detectar alteração sem reabrir o link
    id_arquivo: Optional[str] = None       # id do arquivo no Liferay (fileEntryId)
    protocolo_origem: str = "nome_da_imagem"   # 'nome_da_imagem' | 'texto_do_comunicado' | 'id_do_arquivo' (provisório)


_RE_PROTOCOLO = re.compile(r"(\d{1,4})\s*/\s*(20\d{2})")
# nome da imagem de pré-visualização: "Emergência ambiental 204_2026.png" (ou com %20 / +)
_RE_PROTOCOLO_ARQUIVO = re.compile(r"(?<!\d)(\d{1,4})\s*_\s*(20\d{2})(?!\d)")
_RE_TITULO = re.compile(r"^\s*Comunicado de Acidente\s*-\s*(?P<municipio>.+?)\s*/\s*(?P<uf>[A-Z]{2})"
                        r"(?:\s*-\s*(?P<data>\d{1,2}/\d{1,2}/\d{4}))?\s*$", re.IGNORECASE)
_RE_ID_ARQUIVO = re.compile(r"view_file/(\d+)")
_RE_CUR_ENTRY = re.compile(r"curEntry=(\d+)")


def extrair_protocolo_ano(texto: str) -> Optional[tuple]:
    """Carta §3: 'identificado prioritariamente por protocolo e endereço permanente do documento'.
    Aceita '179/2026' (texto) ou '179_2026' (nome de arquivo). Devolve (protocolo:str, ano:int)."""
    m = _RE_PROTOCOLO.search(texto) or _RE_PROTOCOLO_ARQUIVO.search(texto)
    if not m:
        return None
    return m.group(1), int(m.group(2))


# "Nº Protocolo: 195/2026" no cabeçalho do comunicado. O OCR erra "Nº"/"N°"/":" com frequência, então só o
# rótulo "Protocolo" (tolerando 1-2 letras trocadas no fim) + número/ano é aceito — nunca um "n/2026" solto.
_RE_PROTOCOLO_TEXTO = re.compile(r"Protoc[o0]l[o0]?\s*[:;.\-]?\s*(\d{1,4})\s*/\s*(20\d{2})", re.IGNORECASE)


def extrair_protocolo_do_comunicado(texto: str, ano_esperado: int = None) -> Optional[tuple]:
    """Protocolo lido do TEXTO (OCR) do comunicado. Devolve (protocolo:str, ano:int) ou None.
    Só vale se o ano lido for o ano da página (ano_esperado) — ano diferente indica leitura errada."""
    m = _RE_PROTOCOLO_TEXTO.search((texto or "")[:1500])
    if not m:
        return None
    protocolo, ano = str(int(m.group(1))), int(m.group(2))
    if ano_esperado and ano != ano_esperado:
        return None
    return protocolo, ano


def interpretar_titulo(titulo: str) -> dict:
    """'Comunicado de Acidente - Caeté/MG - 04/10/2026' -> município, UF, data (texto cru). Título fora do
    padrão devolve campos vazios (nunca chuta)."""
    m = _RE_TITULO.match(titulo or "")
    if not m:
        return {"municipio": None, "uf": None, "data": None}
    return {"municipio": m.group("municipio").strip(), "uf": m.group("uf").upper(), "data": m.group("data")}


def _hash_linha(texto: str) -> str:
    return hashlib.sha256(texto.strip().encode("utf-8")).hexdigest()


def buscar_pagina(url: str, session: Optional[requests.Session] = None, timeout: int = 30) -> requests.Response:
    s = session or requests.Session()
    resp = s.get(url, timeout=timeout, headers={
        "User-Agent": "RadarDigitalMineraMinas/1.0 (+coletor M8; contato: Rapha)"
    })
    resp.raise_for_status()
    return resp


def _protocolo_do_cartao(card, titulo: str, id_arquivo: Optional[str]) -> tuple:
    """(protocolo, ano, origem). Ordem: nome da imagem -> título -> id do arquivo (último recurso)."""
    for img in card.select(SELETOR_IMAGEM):
        for atributo in ("src", "alt", "title"):
            valor = unquote((img.get(atributo) or "").replace("+", " "))
            nome = valor.rsplit("/", 1)[-1]
            pa = _RE_PROTOCOLO_ARQUIVO.search(nome)
            if pa:
                return pa.group(1), int(pa.group(2)), "nome_da_imagem"
    # O título NÃO é fonte de protocolo: "…- 04/10/2026" é uma DATA e casaria com o padrão "n/2026".
    if id_arquivo:
        return f"arq{id_arquivo}", ANO_PAGINA, "id_do_arquivo"
    return None, None, None


ANO_PAGINA = 2026   # a página é anual (…-acidentes-ambientais-2026)


def parse_inventario(html: str, base_url: str = URL_PAGINA_ANUAL) -> List[ItemInventario]:
    """Extrai os comunicados (um por cartão) de UMA página da lista. Ordem = ordem na página (mais recente
    primeiro). Cartões repetidos (mesmo id de arquivo) são ignorados."""
    soup = BeautifulSoup(html, "lxml")
    itens: List[ItemInventario] = []
    vistos = set()

    for card in soup.select(SELETOR_ITEM_LISTA):
        link = card.select_one(SELETOR_TITULO)
        href = (link.get("href") or "").strip() if link else ""
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url_detalhe = urljoin(base_url, href)
        titulo = (card.get("data-title") or (link.get_text(" ", strip=True) if link else "")).strip()
        m_id = _RE_ID_ARQUIVO.search(url_detalhe)
        box = card.select_one(SELETOR_ID_ARQUIVO)
        id_arquivo = (m_id.group(1) if m_id else (box.get("value") if box else None))
        if id_arquivo and id_arquivo in vistos:
            continue
        protocolo, ano, origem = _protocolo_do_cartao(card, titulo, id_arquivo)
        if not protocolo:
            continue    # sem protocolo e sem id de arquivo: não há como identificar com segurança
        if id_arquivo:
            vistos.add(id_arquivo)
        t = interpretar_titulo(titulo)
        itens.append(ItemInventario(
            protocolo=protocolo, ano=ano, titulo_fonte=titulo[:500],
            municipio=t["municipio"], data_publicada=t["data"], url_detalhe=url_detalhe,
            hash_linha=_hash_linha(f"{titulo}|{protocolo}/{ano}"),
            id_arquivo=id_arquivo, protocolo_origem=origem,
        ))
    return itens


def total_informado(html: str) -> Optional[int]:
    """'Exibindo 1 - 20 de 190 resultados.' -> 190 (para conferir a paginação)."""
    m = re.search(r"Exibindo\s+\d+\s*-\s*\d+\s+de\s+(\d+)\s+resultados", html or "")
    return int(m.group(1)) if m else None


def urls_outras_paginas(html: str, base_url: str = URL_PAGINA_ANUAL) -> List[str]:
    """URLs das demais páginas da lista (paginação `curEntry=N`), em ordem, sem repetir e sem a página 1."""
    soup = BeautifulSoup(html, "lxml")
    por_pagina = {}
    for a in soup.select("ul.pagination a[href], .pagination-bar a[href]"):
        href = (a.get("href") or "").strip()
        m = _RE_CUR_ENTRY.search(href)
        if not m or "/document_library/" not in href:
            continue
        n = int(m.group(1))
        if n > 1:
            por_pagina.setdefault(n, urljoin(base_url, href.replace("&amp;", "&")))
    return [por_pagina[n] for n in sorted(por_pagina)]


def comparar_com_inventario_anterior(
    inventario_novo: List[ItemInventario],
    hashes_anteriores: dict,  # {(protocolo, ano): hash_linha da rodada anterior}
) -> dict:
    """Carta §4 passo 2/3: compara protocolo+hash com a rodada anterior e
    seleciona só itens novos ou alterados para processamento integral;
    itens idênticos só recebem registro de verificação (sem nova chamada
    de IA — carta §4.3)."""
    novos, alterados, identicos = [], [], []
    for item in inventario_novo:
        chave = (item.protocolo, item.ano)
        hash_anterior = hashes_anteriores.get(chave)
        if hash_anterior is None:
            novos.append(item)
        elif hash_anterior != item.hash_linha:
            alterados.append(item)
        else:
            identicos.append(item)
    return {"novos": novos, "alterados": alterados, "identicos": identicos}

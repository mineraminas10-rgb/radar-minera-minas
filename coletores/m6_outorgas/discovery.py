"""
Módulo 6 — descoberta no índice de publicações de portarias do IGAM
(Carta M6 v0.8 §44.2, fonte M6F01: https://outorga.meioambiente.mg.gov.br/
index.php?r=portaria/listar; §44.3 define o conector IGAM_PUBLICACOES_DOC).

VALIDADO contra o HTML real do índice (salvo em 10/10/2026: 4.213 publicações desde 2001).
Estrutura observada — página simples, sem JavaScript, sem CAPTCHA:

    <a href=".../arquivos/outorgas_ate_31_12_2014.xlsx">Listagem de outorgados ...</a>   <- listagens históricas (NÃO são portarias)
    <h4>2026</h4>
    <ul>
      <li><a href=".../arquivos/ptp07_10_2026_21830.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 07/10/2026</li>
      ...                                                                                    <- mais recente primeiro
    </ul>

- o texto do link ("Portaria 0 e Cancelamentos") é só a CATEGORIA do repositório: nunca classifica o ato
  (carta §23; a Carta de Homologação prova isso — "Cancelamentos" no título e nenhum cancelamento dentro);
- o nome do arquivo (`ptp07_10_2026_21830.doc`) traz data e um número sequencial estável;
- o arquivo é .doc (Word antigo) — a conversão para texto está em extractor.py.
"""
import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class ItemPortaria:
    url_documento: str
    nome_arquivo: str
    data_listada: str  # texto cru, formato não garantido
    categoria: Optional[str]  # texto do cabeçalho/categoria do repositório — NUNCA usado para classificar o ato (carta §23)
    hash_linha: str


def _hash_linha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


URL_INDICE = "https://outorga.meioambiente.mg.gov.br/index.php?r=portaria/listar"


def buscar_indice(session: Optional[requests.Session] = None, timeout: int = 30) -> requests.Response:
    sess = session or requests.Session()
    return sess.get(
        "https://outorga.meioambiente.mg.gov.br/index.php?r=portaria/listar",
        timeout=timeout,
    )


_RE_PUBLICADA = re.compile(r"publicada\(s\)\s+em\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_NOME = re.compile(r"^ptp(\d{2})_(\d{2})_(\d{4})_(\d+)\.(\w+)$", re.IGNORECASE)


def parse_indice(html: str, base_url: str = URL_INDICE) -> List[ItemPortaria]:
    """Extrai as publicações do índice, NA ORDEM da página (mais recente primeiro). Só entram itens que têm
    link para documento e o texto "publicada(s) em dd/mm/aaaa" — as listagens históricas do topo não entram."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    itens: List[ItemPortaria] = []
    vistos = set()
    for li in soup.find_all("li"):
        link = li.find("a", href=True)
        if not link:
            continue
        texto_li = li.get_text(" ", strip=True)
        m = _RE_PUBLICADA.search(texto_li)
        if not m:
            continue
        url = urljoin(base_url, link["href"].strip())
        if url in vistos:
            continue
        vistos.add(url)
        nome = url.rsplit("/", 1)[-1].split("?")[0]
        itens.append(ItemPortaria(
            url_documento=url, nome_arquivo=nome, data_listada=m.group(1),
            categoria=link.get_text(" ", strip=True) or None,
            hash_linha=_hash_linha(f"{nome}|{m.group(1)}|{link.get_text(' ', strip=True)}"),
        ))
    return itens


def data_iso(data_dd_mm_aaaa: str) -> Optional[str]:
    """'07/10/2026' -> '2026-10-07' (None se não for uma data válida)."""
    try:
        return datetime.strptime(data_dd_mm_aaaa.strip(), "%d/%m/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def comparar_com_inventario_anterior(itens_atuais: List[ItemPortaria], hashes_anteriores: set) -> List[ItemPortaria]:
    """Retorna só os itens novos/alterados (carta §44.3: 'comparar o
    inventário com a execução anterior e baixar somente arquivos novos ou
    alterados'). `hashes_anteriores` vem do log_coleta da execução
    passada."""
    return [item for item in itens_atuais if item.hash_linha not in hashes_anteriores]

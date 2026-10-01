"""
Módulo 6 — descoberta no índice de publicações de portarias do IGAM
(Carta M6 v0.8 §44.2, fonte M6F01: https://outorga.meioambiente.mg.gov.br/
index.php?r=portaria/listar; §44.3 define o conector IGAM_PUBLICACOES_DOC).

AVISO IMPORTANTE — leia antes de rodar contra a fonte real: este arquivo
NÃO foi validado contra a página real do IGAM. O sandbox onde foi escrito
não tem acesso de rede a outorga.meioambiente.mg.gov.br (confirmado:
connect_rejected pela política de egress da organização). Os seletores
HTML abaixo são uma estrutura razoável a partir da descrição da carta
("o índice público apresenta links diretos aos documentos [...] sem
autenticação, CAPTCHA ou interação de navegador"), não uma leitura do
HTML real. `signals.py`/`scoring.py` estão testados e corretos contra o
texto já extraído (ver test_scoring.py/test_signals.py); esta camada de
descoberta/download é a que falta validar quando a rede estiver disponível
— mesmo estado em que coletores/m8_acidentes/discovery.py está hoje.
"""
import hashlib
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


def buscar_indice(session: Optional[requests.Session] = None, timeout: int = 30) -> requests.Response:
    sess = session or requests.Session()
    return sess.get(
        "https://outorga.meioambiente.mg.gov.br/index.php?r=portaria/listar",
        timeout=timeout,
    )


def parse_indice(html: str) -> List[ItemPortaria]:
    """Extrai a lista de publicações do HTML do índice. Implementação
    mínima (BeautifulSoup, se disponível) — ver aviso no topo do arquivo:
    os seletores precisam ser confirmados contra o HTML real antes de
    rodar em produção. Levanta ImportError de forma clara se bs4 não
    estiver instalado, em vez de falhar silenciosamente."""
    from bs4 import BeautifulSoup  # import local: só é necessário aqui

    soup = BeautifulSoup(html, "html.parser")
    itens = []
    for linha in soup.select("table tr"):
        link = linha.find("a", href=True)
        if not link or not link["href"].endswith((".doc", ".docx", ".pdf")):
            continue
        texto_linha = linha.get_text(" ", strip=True)
        itens.append(ItemPortaria(
            url_documento=link["href"],
            nome_arquivo=link["href"].rsplit("/", 1)[-1],
            data_listada=texto_linha,  # refinar quando o HTML real estiver disponível
            categoria=None,
            hash_linha=_hash_linha(texto_linha),
        ))
    return itens


def comparar_com_inventario_anterior(itens_atuais: List[ItemPortaria], hashes_anteriores: set) -> List[ItemPortaria]:
    """Retorna só os itens novos/alterados (carta §44.3: 'comparar o
    inventário com a execução anterior e baixar somente arquivos novos ou
    alterados'). `hashes_anteriores` vem do log_coleta da execução
    passada."""
    return [item for item in itens_atuais if item.hash_linha not in hashes_anteriores]

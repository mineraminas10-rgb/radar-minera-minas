"""
Módulo 8 — descoberta na página anual da SEMAD (Carta Operacional M8 §3/§4/§5
passos 1-3).

AVISO IMPORTANTE (ler antes de rodar em produção): o sandbox onde este
código foi escrito não tem acesso de rede à página real
(meioambiente.mg.gov.br está fora da allowlist de rede daqui — confirmado
via teste de conectividade em 23/09/2026). Os seletores HTML abaixo
(`SELETOR_ITEM_LISTA`, `SELETOR_LINK`, `SELETOR_DATA`, `SELETOR_PROTOCOLO`)
são um ponto de partida razoável baseado na estrutura descrita na carta
(§3: "página anual" com "links visíveis" contendo protocolo, título, data
e URL do documento) mas NÃO foram validados contra o HTML real da página.
Assim que a Rapha enviar uma amostra (ela confirmou que vai enviar), ajustar
esses seletores e rodar `validar_contra_amostra()` antes de considerar isto
pronto para produção. Até lá, este módulo é esqueleto funcional, não
coletor homologado.
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional
import requests
from bs4 import BeautifulSoup

URL_PAGINA_ANUAL = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"

# TODO (pendente de amostra real): confirmar/ajustar estes seletores.
SELETOR_ITEM_LISTA = "table tr, .comunicado-item, article"  # tentativa ampla — ajustar
SELETOR_LINK = "a[href]"
SELETOR_TEXTO_LINHA = None  # usar .get_text() do item inteiro por ora


@dataclass
class ItemInventario:
    protocolo: str
    ano: int
    titulo_fonte: str
    municipio: Optional[str]
    data_publicada: Optional[str]  # texto cru da data como aparece na página
    url_detalhe: str
    hash_linha: str  # hash do conteúdo textual da linha, para detectar alteração sem reabrir o link


_RE_PROTOCOLO = re.compile(r"(\d{1,4})\s*/\s*(20\d{2})")


def extrair_protocolo_ano(texto: str) -> Optional[tuple]:
    """Carta §3: 'identificado prioritariamente por protocolo e endereço
    permanente do documento'. Formato observado nos casos congelados:
    '179/2026'."""
    m = _RE_PROTOCOLO.search(texto)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _hash_linha(texto: str) -> str:
    return hashlib.sha256(texto.strip().encode("utf-8")).hexdigest()


def buscar_pagina(url: str, session: Optional[requests.Session] = None, timeout: int = 30) -> requests.Response:
    s = session or requests.Session()
    resp = s.get(url, timeout=timeout, headers={
        "User-Agent": "RadarDigitalMineraMinas/1.0 (+coletor M8; contato: Rapha)"
    })
    resp.raise_for_status()
    return resp


def parse_inventario(html: str) -> List[ItemInventario]:
    """Extrai os itens visíveis da página anual. TODO: validar seletores
    contra HTML real (ver aviso no topo do arquivo)."""
    soup = BeautifulSoup(html, "lxml")
    itens: List[ItemInventario] = []

    candidatos = soup.select(SELETOR_ITEM_LISTA)
    for c in candidatos:
        texto = c.get_text(" ", strip=True)
        protocolo_ano = extrair_protocolo_ano(texto)
        if not protocolo_ano:
            continue  # linha sem protocolo reconhecível — provavelmente cabeçalho/rodapé, não um item
        protocolo, ano = protocolo_ano

        link = c.select_one(SELETOR_LINK)
        if not link or not link.get("href"):
            continue
        url_detalhe = link["href"]

        itens.append(ItemInventario(
            protocolo=protocolo,
            ano=ano,
            titulo_fonte=texto[:500],
            municipio=None,  # TODO: extrair de coluna própria quando os seletores forem confirmados
            data_publicada=None,
            url_detalhe=url_detalhe,
            hash_linha=_hash_linha(texto),
        ))
    return itens


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

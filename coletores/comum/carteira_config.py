"""Leitura e aplicação das regras editoriais configuradas por carteira.

Fail closed para escopo e configuração: uma carteira ausente, inativa ou sem
vínculo de coleta para a fonte não pode cair silenciosamente em parâmetros
globais. Scores deste módulo são sempre 0–100; scores brutos de coletores não
devem ser passados diretamente para ``prioridade_por_score``.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlparse


class ErroCarteira(RuntimeError):
    """Configuração da carteira ausente, inválida ou fora do escopo da fonte."""


def _linhas(sb, tabela: str, empresa_id: str, carteira_id: str) -> list[dict]:
    q = (sb.table(tabela).select("*")
         .eq("empresa_id", empresa_id).eq("carteira_id", carteira_id))
    r = q.execute()
    if getattr(r, "error", None):
        raise ErroCarteira(f"Falha lendo {tabela}: {r.error}")
    return list(getattr(r, "data", None) or [])


def carregar(sb, *, empresa_id: str, carteira_id: str, source_id: str) -> dict:
    """Carrega carteira, critérios, pesos e vínculo da fonte com escopo explícito."""
    if not all((empresa_id, carteira_id, source_id)):
        raise ErroCarteira("empresa_id, carteira_id e source_id são obrigatórios")

    r = (sb.table("carteiras").select("*").eq("id", carteira_id)
         .eq("empresa_id", empresa_id).execute())
    if getattr(r, "error", None):
        raise ErroCarteira(f"Falha lendo carteira: {r.error}")
    carteiras = list(getattr(r, "data", None) or [])
    if len(carteiras) != 1:
        raise ErroCarteira("Carteira não encontrada no escopo desta empresa")
    carteira = carteiras[0]
    if carteira.get("ativa") is not True:
        raise ErroCarteira("Carteira inativa; coleta interrompida")

    fontes = _linhas(sb, "carteira_fontes", empresa_id, carteira_id)
    vinculo = next((f for f in fontes if str(f.get("source_id")) == str(source_id)), None)
    if not vinculo:
        raise ErroCarteira("Fonte não está vinculada à carteira selecionada")
    if str(vinculo.get("finalidade") or "").strip().lower() not in {"coleta", "ambos"}:
        raise ErroCarteira("Fonte vinculada apenas para validação; não pode iniciar coleta")

    sr = sb.table("sources").select("*").eq("id", source_id).execute()
    if getattr(sr, "error", None):
        raise ErroCarteira(f"Falha lendo fonte {source_id}: {sr.error}")
    fontes_cadastradas = list(getattr(sr, "data", None) or [])
    if len(fontes_cadastradas) != 1:
        raise ErroCarteira("Fonte vinculada não encontrada no cadastro sources")
    fonte = fontes_cadastradas[0]
    if fonte.get("ativa") is False:
        raise ErroCarteira("Fonte inativa; coleta interrompida")
    if fonte.get("empresa_id") not in (None, empresa_id):
        raise ErroCarteira("Fonte cadastrada para outra empresa")
    for campo in ("url_base", "url_secundaria"):
        url = fonte.get(campo)
        if url:
            parsed = urlparse(str(url))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ErroCarteira(f"{campo} da fonte precisa ser uma URL http(s) válida")
    if not fonte.get("url_base") and not fonte.get("url_secundaria"):
        raise ErroCarteira("A fonte da carteira não tem URL base nem secundária configurada")

    bandas = {}
    for chave, campo in (("A", "banda_a_min"), ("B", "banda_b_min"), ("C", "banda_c_min")):
        try:
            valor = float(carteira[campo])
        except (KeyError, TypeError, ValueError):
            raise ErroCarteira(f"Banda {chave} ausente ou inválida ({campo})") from None
        if not math.isfinite(valor) or not 0 <= valor <= 100:
            raise ErroCarteira(f"Banda {chave} precisa estar entre 0 e 100")
        bandas[chave] = valor
    if not bandas["A"] >= bandas["B"] >= bandas["C"]:
        raise ErroCarteira("Bandas inválidas: A deve ser >= B e B >= C")

    criterios = carteira.get("criterio_regra") or {}
    if not isinstance(criterios, dict):
        raise ErroCarteira("criterio_regra precisa ser um objeto campo: valor")
    criterios = {str(k).strip(): str(v).strip() for k, v in criterios.items()}
    if any(not k or not v for k, v in criterios.items()):
        raise ErroCarteira("Critério da carteira contém campo ou valor vazio")

    pesos = _linhas(sb, "carteira_pesos", empresa_id, carteira_id)
    pesos_norm = []
    for p in pesos:
        nome = str(p.get("componente") or "").strip()
        try:
            peso = float(p.get("peso"))
        except (TypeError, ValueError):
            raise ErroCarteira("Peso de componente inválido") from None
        if not nome or not math.isfinite(peso) or peso < 0:
            raise ErroCarteira("Componente/peso inválido; pesos devem ser não negativos")
        if peso:
            pesos_norm.append({"componente": nome, "peso": peso})
    if pesos and (not pesos_norm or sum(p["peso"] for p in pesos_norm) <= 0):
        raise ErroCarteira("A carteira possui pesos, mas nenhum peso positivo")

    return {
        "empresa_id": str(empresa_id), "carteira_id": str(carteira_id),
        "source_id": str(source_id), "nome": carteira.get("nome"),
        "bandas": bandas, "criterios": criterios, "pesos": pesos_norm,
        "finalidade": vinculo.get("finalidade"),
        "usar_varredura_inicial": bool(vinculo.get("usar_varredura_inicial")),
        "url_base": fonte.get("url_base"), "url_secundaria": fonte.get("url_secundaria"),
        "metodo_captura": fonte.get("metodo_captura"),
    }


def _normalizar(valor: Any) -> str:
    s = unicodedata.normalize("NFKD", str(valor or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", s).strip()


def criterios_atendidos(contexto: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Os critérios da tela são conjunções de igualdade exata em colunas de events.

    Não encontrados/ausentes falham o critério e mantêm o registro para histórico;
    a chamada não remove nem altera eventos existentes.
    """
    criterios = config.get("criterios") or {}
    faltantes = []
    for campo, esperado in criterios.items():
        atual = contexto.get(campo)
        if atual is None or _normalizar(atual) != _normalizar(esperado):
            faltantes.append(str(campo))
    return not faltantes, faltantes


def score_ponderado(score_base_0_100: float, componentes_0_100: Mapping[str, Any],
                    config: Mapping[str, Any]) -> tuple[float, list[str]]:
    """Calcula média ponderada só com componentes normalizados explicitamente fornecidos.

    Pesos sem componente correspondente são devolvidos em ``nao_aplicados``; não
    são silenciosamente tratados como zeros nem recebem equivalências inventadas.
    """
    base = float(score_base_0_100)
    if not math.isfinite(base) or not 0 <= base <= 100:
        raise ErroCarteira("Score-base precisa estar normalizado entre 0 e 100")
    usados, nao_aplicados = [], []
    componentes = componentes_0_100 or {}
    # Só normaliza nomes que são rótulos equivalentes já usados pela interface.
    # Não associa dimensões diferentes nem replica o score agregado em cada peso.
    aliases = {
        "score_dano_risco": "dano_risco",
        "score_consequencia_operacional": "consequencia_operacional",
        "score_abrangencia_interesse_publico": "interesse_publico",
    }
    index = dict(componentes)
    for alias, canonico in aliases.items():
        if canonico in componentes:
            index.setdefault(alias, componentes[canonico])
        elif alias in componentes:
            index.setdefault(canonico, componentes[alias])
    for p in config.get("pesos") or []:
        nome, peso = p["componente"], float(p["peso"])
        chave = aliases.get(nome, nome)
        valor = index.get(nome, index.get(chave))
        if valor is None:
            nao_aplicados.append(nome)
            continue
        nota = float(valor)
        if not math.isfinite(nota) or not 0 <= nota <= 100:
            raise ErroCarteira(f"Componente {nome!r} não está normalizado entre 0 e 100")
        usados.append((nota, peso))
    # Não calcule um score parcial: uma dimensão configurada e indisponível
    # mudaria a proporção efetiva dos pesos sem autorização do editor.
    if nao_aplicados:
        return base, nao_aplicados
    if not usados:
        return base, nao_aplicados
    soma = sum(p for _, p in usados)
    return sum(n * p for n, p in usados) / soma, nao_aplicados


def prioridade_por_score(score_0_100: float, config: Mapping[str, Any]) -> str:
    score = float(score_0_100)
    b = config["bandas"]
    if score >= b["A"]:
        return "A"
    if score >= b["B"]:
        return "B"
    if score >= b["C"]:
        return "C"
    return "D"


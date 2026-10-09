"""Escopo de coleta: empresa + carteira + fonte (isolamento de carteiras por empresa).

Regra do pedido: "Mesmo Master não deve executar uma consulta sem empresa_id definido"; toda
execução carrega empresa_id + carteira_id, e a carteira tem que pertencer à empresa.

Como o coletor descobre o escopo (nada é adivinhado):
  1. a fonte é achada por `url_base`. Se mais de uma empresa tem a MESMA fonte, o coletor exige
     `RADAR_EMPRESA_ID` (variável de ambiente / argumento) — sem ela, falha com mensagem clara;
  2. a carteira vem de `RADAR_CARTEIRA_ID` (se definida) ou da única carteira da empresa que usa
     essa fonte (`carteira_fontes`). Zero ou várias => falha pedindo a definição explícita;
  3. a carteira é conferida contra a empresa antes de qualquer escrita.
Este módulo só LÊ; não importa supabase-py (recebe o cliente já criado).
"""
from typing import Optional


class EscopoInvalido(RuntimeError):
    """Escopo ausente, ambíguo ou de outra empresa. Sempre aborta a coleta ANTES de qualquer escrita."""


def _norm(v: Optional[str]) -> Optional[str]:
    v = (v or "").strip().lower()
    return v or None


def resolver_escopo(sb, url_base: str, empresa_id: Optional[str] = None, carteira_id: Optional[str] = None,
                    rotulo: str = "coletor") -> dict:
    """Devolve {'id': source_id, 'empresa_id', 'carteira_id'} ou levanta EscopoInvalido."""
    empresa_id, carteira_id = _norm(empresa_id), _norm(carteira_id)
    q = sb.table("sources").select("id, empresa_id").eq("url_base", url_base)
    if empresa_id:
        q = q.eq("empresa_id", empresa_id)
    fontes = q.limit(50).execute().data or []
    if not fontes:
        raise EscopoInvalido(
            f"Fonte do {rotulo} ({url_base}) não encontrada" + (f" para a empresa {empresa_id}" if empresa_id else "")
            + " em sources — cadastrar antes de rodar o coletor.")
    if len(fontes) > 1:
        raise EscopoInvalido(
            f"A fonte do {rotulo} ({url_base}) existe em {len(fontes)} empresas; defina RADAR_EMPRESA_ID "
            "para dizer em nome de qual empresa esta coleta roda (nenhuma é escolhida automaticamente).")
    fonte = fontes[0]
    if not fonte.get("empresa_id"):
        raise EscopoInvalido(f"A fonte {fonte['id']} não tem empresa_id; corrigir o cadastro antes de coletar.")
    emp = fonte["empresa_id"]

    if carteira_id:
        c = sb.table("carteiras").select("id, empresa_id").eq("id", carteira_id).limit(1).execute().data or []
        if not c:
            raise EscopoInvalido(f"Carteira {carteira_id} não existe.")
        if c[0]["empresa_id"] != emp:
            raise EscopoInvalido(f"Carteira {carteira_id} pertence a outra empresa; a coleta foi barrada antes de qualquer escrita.")
        return {"id": fonte["id"], "empresa_id": emp, "carteira_id": c[0]["id"]}

    vinc = sb.table("carteira_fontes").select("carteira_id").eq("source_id", fonte["id"]).eq("empresa_id", emp).limit(50).execute().data or []
    ids = sorted({v["carteira_id"] for v in vinc})
    if not ids:
        raise EscopoInvalido(f"Nenhuma carteira da empresa {emp} usa a fonte {fonte['id']}; vincule a fonte a uma carteira ou defina RADAR_CARTEIRA_ID.")
    if len(ids) > 1:
        raise EscopoInvalido(f"{len(ids)} carteiras da empresa {emp} usam a fonte {fonte['id']}; defina RADAR_CARTEIRA_ID para escolher uma.")
    return {"id": fonte["id"], "empresa_id": emp, "carteira_id": ids[0]}

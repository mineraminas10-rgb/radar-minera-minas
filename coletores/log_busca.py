"""Mapeia o registro completo de requisição para a tabela log_busca EXISTENTE (sem migration):
colunas nativas = url_requisitada, parametros(jsonb), data_hora, codigo_http, url_final, hash_conteudo, origem_vinculo, erro;
os demais campos (url original, MIME, tamanho, método, resultado, tentativa...) vão em parametros.registro."""
from typing import Optional


def linha_log_busca(reg: dict, execucao_id: str, source_id: Optional[str], empresa_id: Optional[str] = None) -> dict:
    return {
        "execucao_id": execucao_id,
        "source_id": source_id or reg.get("source_id"),
        "url_requisitada": reg.get("url_requisitada") or reg.get("url_original"),
        "parametros": {"params": reg.get("parametros") or {}, "registro": {
            k: reg.get(k) for k in ("modulo", "url_original", "mime", "tamanho", "metodo_acesso", "resultado",
                                    "motivo_interrupcao", "tentativa", "versao_rotas", "lacuna")}},
        "data_hora": reg.get("data_hora"),
        "codigo_http": reg.get("status_http"),
        "url_final": reg.get("url_final"),
        "hash_conteudo": reg.get("hash"),
        "origem_vinculo": reg.get("metodo_acesso"),
        "erro": reg.get("motivo_interrupcao"),
        "empresa_id": empresa_id,
    }


def gravar(sb, reg: dict, execucao_id: str, source_id: Optional[str], empresa_id: Optional[str] = None):
    sb.table("log_busca").insert(linha_log_busca(reg, execucao_id, source_id, empresa_id)).execute()

"""
Diagnóstico por etapa dos coletores (M8/M9A).

Objetivo: quando uma rodada falha no GitHub Actions, o log deve dizer QUAL etapa falhou e POR QUÊ,
sem imprimir segredos. Nunca imprime valores de variáveis de ambiente — só presença e "tipo" da chave.
"""
import base64
import json
import os
import sys
import time
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional


class ErroEtapa(RuntimeError):
    def __init__(self, etapa: str, causa: str, dica: Optional[str] = None):
        self.etapa, self.causa, self.dica = etapa, causa, dica
        super().__init__(f"[{etapa}] {causa}" + (f" | dica: {dica}" if dica else ""))


def classificar_chave(chave: Optional[str]) -> str:
    """Só o TIPO da chave, nunca o valor: vazia | sb_secret | sb_publishable | jwt_service_role |
    jwt_anon | jwt_outro | desconhecido."""
    if not chave or not chave.strip():
        return "vazia"
    c = chave.strip()
    if c.startswith("sb_secret_"):
        return "sb_secret"
    if c.startswith("sb_publishable_"):
        return "sb_publishable"
    partes = c.split(".")
    if len(partes) == 3:
        try:
            pad = partes[1] + "=" * (-len(partes[1]) % 4)
            role = json.loads(base64.urlsafe_b64decode(pad)).get("role")
            if role == "service_role":
                return "jwt_service_role"
            if role == "anon":
                return "jwt_anon"
            return "jwt_outro"
        except Exception:
            return "jwt_outro"
    return "desconhecido"


def checar_ambiente(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Valida SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY. Levanta ErroEtapa com mensagem acionável."""
    env = os.environ if env is None else env
    url = (env.get("SUPABASE_URL") or "").strip()
    chave = env.get("SUPABASE_SERVICE_ROLE_KEY")
    tipo = classificar_chave(chave)
    faltando = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", (chave or "").strip())) if not v]
    if faltando:
        raise ErroEtapa(
            "ambiente", f"secrets ausentes ou vazios no GitHub Actions: {', '.join(faltando)}",
            "cadastrar em Settings > Secrets and variables > Actions (nome exato, sem espaços)")
    if not url.startswith("https://") or ".supabase.co" not in url:
        raise ErroEtapa("ambiente", "SUPABASE_URL não parece uma URL de projeto Supabase (https://<ref>.supabase.co)")
    if url.endswith("/"):
        pass  # tolerado
    if tipo in ("jwt_anon", "sb_publishable"):
        raise ErroEtapa("ambiente", f"a chave informada é do tipo {tipo} (pública); o coletor precisa da chave secreta de servidor",
                        "usar a service_role (eyJ...) ou a Secret key (sb_secret_...)")
    return {"SUPABASE_URL": "presente", "SUPABASE_SERVICE_ROLE_KEY": f"presente (tipo {tipo})"}


def resumo_http(resp, limite_trecho: int = 160) -> Dict[str, object]:
    """Resumo seguro de uma resposta HTTP para o log (status, tipo, tamanho, início do texto)."""
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
    corpo = getattr(resp, "content", b"") or b""
    trecho = ""
    if ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        trecho = " ".join(corpo[:2000].decode("utf-8", "replace").split())[:limite_trecho]
    return {"status": resp.status_code, "content_type": ctype, "bytes": len(corpo), "inicio": trecho}


class Etapas:
    """Registra cada etapa (ok/falha, duração) e imprime no log; opcionalmente escreve no resumo do job."""

    def __init__(self, nome_coletor: str, saida: Callable[[str], None] = print):
        self.nome, self.saida, self.registro = nome_coletor, saida, []   # type: ignore

    @contextmanager
    def etapa(self, nome: str):
        t0 = time.monotonic()
        self.saida(f"[{self.nome}] etapa '{nome}' ... iniciando")
        try:
            yield
        except ErroEtapa as e:
            self._fim(nome, t0, False, e.causa)
            if e.etapa != nome:
                raise ErroEtapa(nome, e.causa, e.dica) from e
            raise
        except Exception as e:
            causa = f"{type(e).__name__}: {e}"
            self._fim(nome, t0, False, causa)
            raise ErroEtapa(nome, causa) from e
        else:
            self._fim(nome, t0, True, None)

    def _fim(self, nome, t0, ok, causa):
        dur = round(time.monotonic() - t0, 2)
        self.registro.append({"etapa": nome, "ok": ok, "segundos": dur, "causa": causa})
        self.saida(f"[{self.nome}] etapa '{nome}' {'OK' if ok else 'FALHOU'} ({dur}s)" + (f" -> {causa}" if causa else ""))

    def markdown(self) -> str:
        linhas = [f"### {self.nome} — etapas", "", "| etapa | resultado | s | detalhe |", "|---|---|---|---|"]
        for r in self.registro:
            linhas.append(f"| {r['etapa']} | {'ok' if r['ok'] else '**falhou**'} | {r['segundos']} | {r['causa'] or ''} |")
        return "\n".join(linhas) + "\n"

    def gravar_resumo_job(self):
        caminho = os.environ.get("GITHUB_STEP_SUMMARY")
        if caminho:
            try:
                with open(caminho, "a", encoding="utf-8") as f:
                    f.write(self.markdown())
            except OSError:
                pass

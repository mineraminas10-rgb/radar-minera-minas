"""
Acesso HTTP único dos coletores. Toda requisição:
  - só vai a URL dentro das fontes oficiais (rotas.url_permitida), inclusive depois de redirecionamentos;
  - é registrada com: source_id, URL original, URL requisitada, parâmetros, data/hora, status HTTP,
    URL final, MIME, tamanho, hash, método de acesso, resultado e motivo de interrupção;
  - NUNCA contorna barreira: 401/403/429, CAPTCHA/antibot/autenticação => para, registra e devolve a lacuna
    (acesso manual autorizado, fonte pública alternativa ou integração formal). Sem retry em barreira.
Retry só para erro transitório de rede/5xx (poucas tentativas, espera crescente).
"""
import hashlib
import re
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests

import rotas

USER_AGENT = "RadarDigitalMineraMinas/1.0 (coletor oficial; uso de dados publicos)"
BARREIRAS_STATUS = {401: "autenticacao_exigida", 403: "acesso_negado", 429: "limite_de_taxa"}
ASSINATURAS_BARREIRA = (
    "g-recaptcha", "h-captcha", "hcaptcha", "cf-turnstile", "cf-challenge", "captcha",
    "attention required! | cloudflare", "just a moment...", "access denied", "px-captcha",
)
EXTENSOES_DOCUMENTO = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods", ".csv", ".txt")


class AcessoInterrompido(Exception):
    def __init__(self, resultado: str, motivo: str, registro: dict):
        self.resultado, self.motivo, self.registro = resultado, motivo, registro
        super().__init__(f"{resultado}: {motivo}")


class BarreiraDeAcesso(AcessoInterrompido):
    """CAPTCHA/401/403/429/antibot. Decisão: parar, registrar, não contornar."""


class ForaDaRota(AcessoInterrompido):
    pass


class LimiteDeRequisicoes(AcessoInterrompido):
    pass


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def detectar_barreira_no_corpo(ctype: str, corpo: bytes) -> Optional[str]:
    if not (ctype.startswith("text/html") or ctype == "" or "xhtml" in ctype):
        return None
    amostra = corpo[:200_000].decode("utf-8", "ignore").lower()
    for a in ASSINATURAS_BARREIRA:
        if a in amostra:
            return f"assinatura_antibot:{a}"
    return None


@dataclass
class Resposta:
    registro: dict
    corpo: bytes = b""
    url_final: str = ""
    content_type: str = ""
    status: int = 0

    @property
    def texto(self) -> str:
        return self.corpo.decode("utf-8", "replace")


class Acessador:
    def __init__(self, modulo: str, source_id: Optional[str] = None, sink: Optional[Callable[[dict], None]] = None,
                 session: Optional[requests.Session] = None, max_requisicoes: int = 200, timeout: int = 30,
                 tentativas: int = 3, espera: Callable[[float], None] = time.sleep, sem_checar_rota: bool = False):
        self.modulo, self.source_id, self.sink = modulo, source_id, sink
        self.s = session or requests.Session()
        self.max_requisicoes, self.timeout, self.tentativas, self.espera = max_requisicoes, timeout, tentativas, espera
        self.sem_checar_rota = sem_checar_rota    # só testes com servidor local
        self.registros: List[dict] = []
        self.barreiras: List[dict] = []
        self.n = 0

    # -- registro --------------------------------------------------------------------
    def _novo(self, url, params, metodo):
        return {"modulo": self.modulo, "source_id": self.source_id, "url_original": url, "url_requisitada": url,
                "parametros": params or {}, "data_hora": agora_iso(), "status_http": None, "url_final": None,
                "mime": None, "tamanho": None, "hash": None, "metodo_acesso": metodo,
                "resultado": None, "motivo_interrupcao": None, "tentativa": 0}

    def _fechar(self, reg, resultado, motivo=None):
        reg["resultado"], reg["motivo_interrupcao"] = resultado, motivo
        self.registros.append(reg)
        if resultado == "barreira":
            self.barreiras.append({k: reg[k] for k in ("url_original", "status_http", "data_hora", "tentativa", "motivo_interrupcao")}
                                  | {"decisao": "parada; não contornado; lacuna enviada para acesso manual autorizado, fonte pública alternativa ou integração formal"})
        if self.sink:
            self.sink(reg)
        return reg

    def _checar_rota(self, reg, url, quando):
        if self.sem_checar_rota:
            return
        ok, motivo = rotas.url_permitida(url)
        if not ok:
            self._fechar(reg, "fora_da_rota", f"{quando}:{motivo}")
            raise ForaDaRota("fora_da_rota", f"{quando}:{motivo}", reg)

    # -- GET -------------------------------------------------------------------------
    def get(self, url: str, params: Optional[dict] = None, metodo_acesso: str = "http_get", max_bytes: int = 50_000_000) -> Resposta:
        reg = self._novo(url, params, metodo_acesso)
        if self.n >= self.max_requisicoes:
            self._fechar(reg, "limite", f"limite de {self.max_requisicoes} requisições por rodada")
            raise LimiteDeRequisicoes("limite", reg["motivo_interrupcao"], reg)
        self._checar_rota(reg, url, "url_inicial")
        ultimo_erro = None
        for tent in range(1, self.tentativas + 1):
            reg["tentativa"] = tent
            self.n += 1
            try:
                r = self.s.get(url, params=params, timeout=self.timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            except (requests.Timeout, requests.ConnectionError) as e:
                ultimo_erro = f"{type(e).__name__}"
                if tent < self.tentativas:
                    self.espera(2 ** tent)
                    continue
                self._fechar(reg, "erro_rede", ultimo_erro)
                raise AcessoInterrompido("erro_rede", ultimo_erro, reg)
            reg["status_http"] = r.status_code
            reg["url_requisitada"] = getattr(r.request, "url", url) if getattr(r, "request", None) is not None else url
            reg["url_final"] = r.url
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            reg["mime"] = ctype
            corpo = r.content or b""
            reg["tamanho"], reg["hash"] = len(corpo), sha256(corpo)
            self._checar_rota(reg, r.url, "apos_redirecionamento")
            if r.status_code in BARREIRAS_STATUS:
                motivo = f"{r.status_code}:{BARREIRAS_STATUS[r.status_code]}"
                self._fechar(reg, "barreira", motivo)
                raise BarreiraDeAcesso("barreira", motivo, reg)
            if r.status_code >= 500 and tent < self.tentativas:
                self.espera(2 ** tent)
                continue
            if r.status_code >= 400:
                self._fechar(reg, "erro_http", f"{r.status_code}")
                raise AcessoInterrompido("erro_http", f"HTTP {r.status_code}", reg)
            b = detectar_barreira_no_corpo(ctype, corpo)
            if b:
                self._fechar(reg, "barreira", b)
                raise BarreiraDeAcesso("barreira", b, reg)
            if len(corpo) > max_bytes:
                self._fechar(reg, "erro_http", f"corpo maior que {max_bytes} bytes")
                raise AcessoInterrompido("erro_http", reg["motivo_interrupcao"], reg)
            self._fechar(reg, "ok")
            return Resposta(registro=reg, corpo=corpo, url_final=r.url, content_type=ctype, status=r.status_code)
        raise AcessoInterrompido("erro_http", ultimo_erro or "falha", reg)   # pragma: no cover

    # -- download em fluxo para arquivos grandes --------------------------------------
    def baixar_arquivo(self, url: str, destino: str, max_bytes: int, mimes_aceitos: Optional[tuple] = None,
                       metodo_acesso: str = "http_get_stream") -> dict:
        reg = self._novo(url, None, metodo_acesso)
        self._checar_rota(reg, url, "url_inicial")
        self.n += 1
        reg["tentativa"] = 1
        try:
            r = self.s.get(url, stream=True, timeout=self.timeout, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        except (requests.Timeout, requests.ConnectionError) as e:
            self._fechar(reg, "erro_rede", type(e).__name__)
            raise AcessoInterrompido("erro_rede", type(e).__name__, reg)
        try:
            reg.update(status_http=r.status_code, url_final=r.url)
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            reg["mime"] = ctype
            self._checar_rota(reg, r.url, "apos_redirecionamento")
            if r.status_code in BARREIRAS_STATUS:
                m = f"{r.status_code}:{BARREIRAS_STATUS[r.status_code]}"
                self._fechar(reg, "barreira", m)
                raise BarreiraDeAcesso("barreira", m, reg)
            if r.status_code >= 400:
                self._fechar(reg, "erro_http", str(r.status_code))
                raise AcessoInterrompido("erro_http", f"HTTP {r.status_code}", reg)
            if ctype.startswith("text/html"):
                # dado aberto servido como HTML = página de erro/antibot/redirecionamento, não o arquivo
                self._fechar(reg, "barreira" if "captcha" in r.text[:200000].lower() else "erro_http", "recebido HTML no lugar do arquivo")
                raise AcessoInterrompido("erro_http", "recebido HTML no lugar do arquivo", reg)
            if mimes_aceitos and ctype not in mimes_aceitos:
                self._fechar(reg, "erro_http", f"MIME inesperado: {ctype}")
                raise AcessoInterrompido("erro_http", f"MIME inesperado: {ctype}", reg)
            declarado = int(r.headers.get("Content-Length") or 0)
            if declarado and declarado > max_bytes:
                self._fechar(reg, "erro_http", f"tamanho declarado {declarado} > limite {max_bytes}")
                raise AcessoInterrompido("erro_http", reg["motivo_interrupcao"], reg)
            h, total = hashlib.sha256(), 0
            with open(destino, "wb") as f:
                for bloco in r.iter_content(chunk_size=1 << 20):
                    total += len(bloco)
                    if total > max_bytes:
                        self._fechar(reg, "erro_http", f"download passou do limite {max_bytes}")
                        raise AcessoInterrompido("erro_http", reg["motivo_interrupcao"], reg)
                    h.update(bloco)
                    f.write(bloco)
            if declarado and total != declarado:
                self._fechar(reg, "erro_http", f"download truncado: {total} de {declarado} bytes")
                raise AcessoInterrompido("erro_http", reg["motivo_interrupcao"], reg)
            reg.update(tamanho=total, hash=h.hexdigest())
            self._fechar(reg, "ok")
            return reg
        finally:
            r.close()


# -- expansão documental reproduzível e limitada -------------------------------------
def inventariar_links(html: str, base_url: str, limite: int = 40) -> List[dict]:
    """Inventaria links de anexos/documentos de uma página oficial ANTES da interpretação.
    Ordem = ordem de aparição na página; duplicados removidos; só URLs dentro das fontes oficiais; teto `limite`."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    vistos, saida = set(), []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        url = url.split("#")[0]
        if url in vistos:
            continue
        vistos.add(url)
        caminho = urlparse(url).path.lower()
        ext = next((e for e in EXTENSOES_DOCUMENTO if caminho.endswith(e)), None)
        ok, motivo = rotas.url_permitida(url)
        saida.append({"url": url, "texto": a.get_text(" ", strip=True)[:200], "extensao": ext, "permitido": ok, "motivo": motivo})
    docs = [x for x in saida if x["extensao"] and x["permitido"]]
    return docs[:limite]


class LimiteDeBuscas:
    """Busca complementar só por template versionado, com tentativas limitadas e parada quando a evidência
    obrigatória já está coberta. Cada busca registra a lacuna que a motivou (vai para Log_Busca em `parametros`)."""

    def __init__(self, maximo: int = 3):
        self.maximo, self.feitas = maximo, []

    def pode(self, lacuna: str, evidencia_ja_coberta: bool) -> bool:
        if evidencia_ja_coberta:
            return False
        return len(self.feitas) < self.maximo

    def registrar(self, template: str, consulta: str, lacuna: str):
        if len(self.feitas) >= self.maximo:
            raise LimiteDeRequisicoes("limite", f"máximo de {self.maximo} buscas complementares", {})
        self.feitas.append({"template": template, "consulta": consulta, "lacuna": lacuna, "data_hora": agora_iso()})

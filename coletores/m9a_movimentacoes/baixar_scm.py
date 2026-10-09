"""
Download seguro do dump SCM (ANM) — substitui o `curl | unzip` do workflow, que falhava sem dizer onde.

Etapas (cada uma com nome próprio no log, sem segredos):
  download -> validar_zip -> extrair -> validar_arquivos
Validações: rota oficial (inclusive após redirecionamento), status, barreiras (401/403/429/CAPTCHA => parar,
registrar, não contornar), MIME (HTML no lugar do zip = erro), tamanho declarado x recebido, limite de bytes,
assinatura PK, integridade do zip, hash SHA-256, proteção contra zip-slip, limite de tamanho por arquivo,
extração SÓ dos 9 arquivos usados pelo M9A, número de colunas de cada cabeçalho.
Se o SHA-256 do zip for igual ao da última coleta bem-sucedida (`--hash-anterior`), nada é extraído nem
processado ("hash igual ao último sucesso" => zero trabalho).
Não faz chamada de IA.
"""
import argparse
import json
import os
import sys
import zipfile
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))

import acesso
import diagnostico
import ingestao_scm
import rotas

URL_SCM = "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip"
MAX_ZIP_BYTES = 600 * 1024 * 1024            # ~198 MB observado; folga para crescer
MAX_MEMBRO_BYTES = 3 * 1024 * 1024 * 1024    # ProcessoEvento.txt ~1,04 GB observado
MIN_ZIP_BYTES = 1 * 1024 * 1024              # menos que isso não é o dump
MIMES_ZIP = ("application/zip", "application/x-zip-compressed", "application/octet-stream", "binary/octet-stream")
ARQUIVOS_NECESSARIOS = tuple(ingestao_scm.COLUNAS_POR_ARQUIVO)


def baixar_e_extrair(destino: str, url: str = URL_SCM, hash_anterior: Optional[str] = None, acessador=None,
                     saida=print, max_zip_bytes: int = MAX_ZIP_BYTES, min_zip_bytes: int = MIN_ZIP_BYTES,
                     max_membro_bytes: int = MAX_MEMBRO_BYTES) -> dict:
    os.makedirs(destino, exist_ok=True)
    etapas = diagnostico.Etapas("M9A-download", saida=saida)
    ac = acessador or acesso.Acessador("M9A", sem_checar_rota=False)
    caminho_zip = os.path.join(destino, "microdados-scm.zip")
    res = {"url": url, "mudou": True, "registro_http": None}

    with etapas.etapa("download"):
        reg = ac.baixar_arquivo(url, caminho_zip, max_bytes=max_zip_bytes, mimes_aceitos=MIMES_ZIP,
                                metodo_acesso="m9a_scm_zip")
        res["registro_http"], res["sha256"], res["bytes"] = reg, reg["hash"], reg["tamanho"]
        saida(f"[M9A] zip: {reg['tamanho']} bytes, mime={reg['mime']}, sha256={reg['hash'][:16]}…, url_final={reg['url_final']}")

    with etapas.etapa("validar_zip"):
        if res["bytes"] < min_zip_bytes:
            raise diagnostico.ErroEtapa("validar_zip", f"arquivo pequeno demais ({res['bytes']} bytes) para ser o dump do SCM")
        with open(caminho_zip, "rb") as f:
            if f.read(4) != b"PK\x03\x04":
                raise diagnostico.ErroEtapa("validar_zip", "o arquivo baixado não começa com a assinatura de zip (PK)")
        if not zipfile.is_zipfile(caminho_zip):
            raise diagnostico.ErroEtapa("validar_zip", "zip inválido ou corrompido")
        with zipfile.ZipFile(caminho_zip) as z:
            ruim = z.testzip()
            if ruim:
                raise diagnostico.ErroEtapa("validar_zip", f"membro corrompido no zip: {ruim}")
        if hash_anterior and hash_anterior == res["sha256"]:
            res["mudou"] = False
            saida("[M9A] hash do zip igual ao da última coleta bem-sucedida: nada a extrair nem processar")
            res["etapas"] = etapas.registro
            return res

    with etapas.etapa("extrair"):
        extraidos = {}
        with zipfile.ZipFile(caminho_zip) as z:
            por_nome = {}
            for info in z.infolist():
                base = os.path.basename(info.filename.replace("\\", "/"))
                if info.is_dir() or base.lower() not in {a.lower() for a in ARQUIVOS_NECESSARIOS}:
                    continue
                por_nome.setdefault(base.lower(), info)
            faltando = [a for a in ARQUIVOS_NECESSARIOS if a.lower() not in por_nome]
            if faltando:
                raise diagnostico.ErroEtapa("extrair", f"arquivos ausentes no zip: {faltando}. O formato do zip oficial mudou?")
            for a in ARQUIVOS_NECESSARIOS:
                info = por_nome[a.lower()]
                if info.file_size > max_membro_bytes:
                    raise diagnostico.ErroEtapa("extrair", f"{a} tem {info.file_size} bytes (limite {max_membro_bytes})")
                alvo = os.path.join(destino, "microdados", a)         # nome fixo: sem zip-slip possível
                os.makedirs(os.path.dirname(alvo), exist_ok=True)
                total = 0
                with z.open(info) as src, open(alvo, "wb") as dst:
                    while True:
                        b = src.read(1 << 20)
                        if not b:
                            break
                        total += len(b)
                        if total > max_membro_bytes:
                            raise diagnostico.ErroEtapa("extrair", f"{a} passou do limite ao descompactar")
                        dst.write(b)
                extraidos[a] = total
        res["dir_microdados"] = os.path.join(destino, "microdados")
        res["arquivos"] = extraidos
        saida(f"[M9A] extraídos {len(extraidos)} arquivos: " + ", ".join(f"{k}={v}" for k, v in extraidos.items()))

    with etapas.etapa("validar_arquivos"):
        vazios = [a for a, n in extraidos.items() if n == 0]
        if vazios:
            raise diagnostico.ErroEtapa("validar_arquivos", f"arquivos vazios: {vazios}")
        avisos = []
        ingestao_scm.conferir_cabecalhos(res["dir_microdados"], avisos)
        res["avisos_cabecalho"] = avisos
        for a in avisos:
            saida(f"[M9A] aviso: {a}")

    res["etapas"] = etapas.registro
    return res


def main():
    ap = argparse.ArgumentParser(description="Baixa e valida o dump SCM da ANM")
    ap.add_argument("--destino", required=True)
    ap.add_argument("--url", default=URL_SCM)
    ap.add_argument("--hash-anterior", default=None)
    ap.add_argument("--registro-saida", default=None, help="JSON com o registro da requisição (para o log_busca)")
    a = ap.parse_args()
    ok, motivo = rotas.url_permitida(a.url)
    if not ok:
        print(f"[M9A] URL fora das fontes oficiais: {motivo}")
        sys.exit(2)
    try:
        r = baixar_e_extrair(a.destino, a.url, a.hash_anterior)
    except Exception as e:
        print(f"[M9A-download] FALHA: {e}")
        if isinstance(e, diagnostico.ErroEtapa) and isinstance(e.__cause__, acesso.AcessoInterrompido):
            print(f"[M9A-download] registro: {json.dumps(e.__cause__.registro, default=str)}")
        sys.exit(1)
    if a.registro_saida:
        with open(a.registro_saida, "w") as f:
            json.dump(r["registro_http"], f, default=str)
    for var, val in (("DIR_MICRODADOS", r.get("dir_microdados", "")), ("SCM_MUDOU", "true" if r["mudou"] else "false"),
                     ("SCM_SHA256", r["sha256"])):
        print(f"{var}={val}")
        if os.environ.get("GITHUB_ENV"):
            with open(os.environ["GITHUB_ENV"], "a") as f:
                f.write(f"{var}={val}\n")


if __name__ == "__main__":
    main()

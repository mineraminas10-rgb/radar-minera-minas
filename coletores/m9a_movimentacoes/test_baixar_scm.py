import io, os, pathlib, sys, tempfile, threading, unittest, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import acesso, diagnostico
import baixar_scm as b
import ingestao_scm as ing
from test_ingestao_blocos import dump_sintetico

ROTAS = {}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        st, ctype, corpo, extra = ROTAS[self.path]
        self.send_response(st); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(extra.get("cl", len(corpo))))
        self.end_headers(); self.wfile.write(corpo)
    def log_message(self, *a): pass


def zip_do_dump(prefixo="", extra=None, sem=()):
    with tempfile.TemporaryDirectory() as d:
        dump_sintetico(d)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in os.listdir(d):
                if n in sem: continue
                z.write(os.path.join(d, n), prefixo + n)
            for k, v in (extra or {}).items():
                z.writestr(k, v)
        return buf.getvalue()


class TestBaixar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def go(self, corpo, st=200, ctype="application/zip", hash_anterior=None, **kw):
        ROTAS["/x.zip"] = (st, ctype, corpo, {})
        ac = acesso.Acessador("M9A", sem_checar_rota=True, tentativas=1)
        with tempfile.TemporaryDirectory() as d:
            r = b.baixar_e_extrair(d, self.base + "/x.zip", hash_anterior=hash_anterior, acessador=ac,
                                   saida=lambda s: None, min_zip_bytes=100, **kw)
            return r, os.listdir(os.path.join(d, "microdados")) if r.get("dir_microdados") else None

    def falha(self, corpo, esperado, **kw):
        with self.assertRaises(diagnostico.ErroEtapa) as c:
            self.go(corpo, **kw)
        self.assertEqual(c.exception.etapa, esperado, str(c.exception))
        return c.exception

    def test_ok_em_subpasta(self):
        r, arqs = self.go(zip_do_dump("dump-2026/"))
        self.assertEqual(sorted(arqs), sorted(b.ARQUIVOS_NECESSARIOS))
        self.assertTrue(r["mudou"]); self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual([e["ok"] for e in r["etapas"]], [True] * 4)

    def test_so_extrai_os_nove_arquivos_e_ignora_zipslip(self):
        r, arqs = self.go(zip_do_dump("", extra={"../evil.txt": "x", "Outro.txt": "y", "a/../../Pessoa2.txt": "z"}))
        self.assertEqual(sorted(arqs), sorted(b.ARQUIVOS_NECESSARIOS))

    def test_html_no_lugar_do_zip(self):
        self.falha(b"<html>pagina de erro</html>" * 10, "download", ctype="text/html")

    def test_barreira_403(self):
        e = self.falha(b"Forbidden", "download", st=403, ctype="text/plain")
        self.assertIsInstance(e.__cause__, acesso.BarreiraDeAcesso)

    def test_nao_e_zip(self):
        self.falha(b"nao sou zip" * 50, "validar_zip", ctype="application/octet-stream")

    def test_zip_sem_arquivo_obrigatorio(self):
        e = self.falha(zip_do_dump("", sem=("Pessoa.txt",)), "extrair")
        self.assertIn("Pessoa.txt", str(e))

    def test_arquivo_vazio_no_zip(self):
        self.falha(self._zip_com_vazio(), "validar_arquivos")

    def _zip_com_vazio(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n in os.listdir(d):
                    z.writestr(n, "" if n == "Pessoa.txt" else pathlib.Path(d, n).read_bytes())
            return buf.getvalue()

    def test_hash_igual_nao_extrai(self):
        z = zip_do_dump()
        r1, _ = self.go(z)
        ROTAS["/x.zip"] = (200, "application/zip", z, {})
        ac = acesso.Acessador("M9A", sem_checar_rota=True, tentativas=1)
        with tempfile.TemporaryDirectory() as d:
            r = b.baixar_e_extrair(d, self.base + "/x.zip", hash_anterior=r1["sha256"], acessador=ac, saida=lambda s: None, min_zip_bytes=100)
            self.assertFalse(r["mudou"])
            self.assertFalse(os.path.exists(os.path.join(d, "microdados")))

    def test_pequeno_demais(self):
        ROTAS["/x.zip"] = (200, "application/zip", b"PK\x03\x04" + b"0" * 10, {})
        ac = acesso.Acessador("M9A", sem_checar_rota=True, tentativas=1)
        with tempfile.TemporaryDirectory() as d, self.assertRaises(diagnostico.ErroEtapa) as c:
            b.baixar_e_extrair(d, self.base + "/x.zip", acessador=ac, saida=lambda s: None)
        self.assertEqual(c.exception.etapa, "validar_zip")

    def test_url_fora_da_rota_oficial_nem_baixa(self):
        ac = acesso.Acessador("M9A", tentativas=1)
        with tempfile.TemporaryDirectory() as d, self.assertRaises(diagnostico.ErroEtapa) as c:
            b.baixar_e_extrair(d, "https://exemplo.com/microdados-scm.zip", acessador=ac, saida=lambda s: None)
        self.assertIsInstance(c.exception.__cause__, acesso.ForaDaRota)

    def test_fallback_tenta_outra_rota_oficial_apos_falha_de_host(self):
        urls = (b.URL_SCM, "https://app.anm.gov.br/DadosAbertos/SCM/microdados/microdados-scm.zip")
        chamadas = []

        def fake_download(destino, url, hash_anterior=None, acessador=None, saida=print, **kw):
            chamadas.append(url)
            if len(chamadas) == 1:
                raise diagnostico.ErroEtapa("download", "falha TLS simulada")
            pathlib.Path(destino, "microdados-scm.zip").write_bytes(b"zip validado")
            md = pathlib.Path(destino, "microdados")
            md.mkdir()
            (md / "Processo.txt").write_text("dados")
            return {"url": url, "mudou": True, "registro_http": {"url": url}, "sha256": "abc"}

        with tempfile.TemporaryDirectory() as d, patch.object(b, "baixar_e_extrair", side_effect=fake_download):
            r = b.baixar_com_fallback(d, urls=urls, saida=lambda s: None)
            self.assertEqual(chamadas, list(urls))
            self.assertEqual(r["url"], urls[1])
            self.assertTrue(pathlib.Path(d, "microdados-scm.zip").is_file())
            self.assertTrue(pathlib.Path(d, "microdados", "Processo.txt").is_file())
            self.assertIn("sucesso", r["rotas_tentadas"][-1])

    def test_url_padrao_esta_dentro_da_rota_m9a(self):
        self.assertTrue(b.rotas.url_permitida(b.URL_SCM)[0])
        self.assertTrue(b.URL_SCM.startswith(b.rotas.fonte_primaria_url("M9A")))


if __name__ == "__main__":
    unittest.main()

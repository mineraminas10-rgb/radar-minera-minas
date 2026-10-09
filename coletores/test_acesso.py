import os, tempfile, unittest
import requests
import acesso as a
import rotas
from log_busca import linha_log_busca


class FakeResp:
    def __init__(self, status=200, body=b"<html>ok</html>", ctype="text/html; charset=utf-8", url=None, headers=None):
        self.status_code, self.content = status, body
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self.url, self.request, self.text = url, None, body.decode("utf-8", "ignore")
    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]
    def close(self): pass


class FakeSession:
    def __init__(self, *respostas):
        self.fila, self.chamadas = list(respostas), []
    def get(self, url, **kw):
        self.chamadas.append(url)
        r = self.fila.pop(0)
        if isinstance(r, Exception):
            raise r
        if r.url is None:
            r.url = url
        return r


URL = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"


def mk(*resp, **kw):
    s = FakeSession(*resp)
    logs = []
    ac = a.Acessador("M8", source_id="S1", sink=logs.append, session=s, espera=lambda x: None, **kw)
    return ac, s, logs


class TestRotas(unittest.TestCase):
    def test_modulos_e_primarias(self):
        self.assertEqual(rotas.modulos(), ["M6", "M7", "M8", "M9A", "M9B"])
        self.assertEqual(rotas.fonte_primaria_url("M8"), URL)
        self.assertTrue(rotas.fonte_primaria_url("M9B").endswith("/SIGBM/"))

    def test_todas_as_urls_http_das_rotas_sao_permitidas(self):
        for m in rotas.modulos():
            r = rotas.rota_do_modulo(m)
            for k in ("descoberta", "estruturada", "confirmacao"):
                for u in r.get(k, []):
                    self.assertTrue(rotas.url_permitida(u)[0], u)
            for u in r.get("complementares", []):
                if u.startswith("http"):
                    self.assertTrue(rotas.url_permitida(u)[0], u)

    def test_fora_da_rota(self):
        for u in ("https://www.google.com/search?q=x", "https://exemplo.com/a.pdf", "ftp://meioambiente.mg.gov.br/x",
                  "https://www.gov.br/saude/", "https://meioambiente.mg.gov.br.evil.com/x", "https://evilmeioambiente.mg.gov.br/x"):
            self.assertFalse(rotas.url_permitida(u)[0], u)
        self.assertTrue(rotas.url_permitida("https://www.gov.br/anm/pt-br/assuntos/barragens/dce-e-dco")[0])

    def test_m9a_regra_scm_descobre(self):
        self.assertIn("SCM descobre", rotas.rota_do_modulo("M9A")["regras"][0])

    def test_descricao_da_rota_tem_versao(self):
        self.assertEqual(rotas.descricao_da_rota("M8")["versao_rotas"], rotas.VERSAO_ROTAS)


class TestAcesso(unittest.TestCase):
    def test_registro_completo_em_requisicao_ok(self):
        ac, s, logs = mk(FakeResp(body=b"<html>ola</html>"))
        r = ac.get(URL, params={"ano": 2026})
        reg = logs[0]
        for k in ("source_id", "url_original", "url_requisitada", "parametros", "data_hora", "status_http", "url_final",
                  "mime", "tamanho", "hash", "metodo_acesso", "resultado", "motivo_interrupcao"):
            self.assertIn(k, reg)
        self.assertEqual((reg["status_http"], reg["mime"], reg["tamanho"], reg["resultado"]), (200, "text/html", 16, "ok"))
        self.assertEqual(len(reg["hash"]), 64)
        self.assertEqual(r.status, 200)

    def test_barreiras_param_status_nao_tentam_de_novo_e_nao_contornam(self):
        for st in (401, 403, 429):
            ac, s, logs = mk(FakeResp(status=st), FakeResp(status=200))
            with self.assertRaises(a.BarreiraDeAcesso):
                ac.get(URL)
            self.assertEqual(len(s.chamadas), 1, f"status {st}: não pode repetir a requisição")
            self.assertEqual(logs[0]["resultado"], "barreira")
            self.assertIn(str(st), logs[0]["motivo_interrupcao"])
            self.assertEqual(len(ac.barreiras), 1)
            self.assertIn("não contornado", ac.barreiras[0]["decisao"])

    def test_captcha_no_corpo_para(self):
        ac, s, logs = mk(FakeResp(body=b'<html><div class="g-recaptcha"></div></html>'))
        with self.assertRaises(a.BarreiraDeAcesso):
            ac.get(URL)
        self.assertEqual(logs[0]["resultado"], "barreira")

    def test_erro_5xx_tenta_poucas_vezes_depois_registra(self):
        ac, s, logs = mk(FakeResp(status=503), FakeResp(status=503), FakeResp(status=503))
        with self.assertRaises(a.AcessoInterrompido):
            ac.get(URL)
        self.assertEqual(len(s.chamadas), 3)
        self.assertEqual(logs[0]["resultado"], "erro_http")

    def test_5xx_transitorio_recupera(self):
        ac, s, logs = mk(FakeResp(status=502), FakeResp(body=b"<html>ok</html>"))
        self.assertEqual(ac.get(URL).status, 200)
        self.assertEqual(logs[0]["tentativa"], 2)

    def test_timeout_registra_erro_rede(self):
        ac, s, logs = mk(requests.Timeout(), requests.Timeout(), requests.Timeout())
        with self.assertRaises(a.AcessoInterrompido):
            ac.get(URL)
        self.assertEqual(logs[0]["resultado"], "erro_rede")

    def test_url_fora_da_rota_nao_e_requisitada(self):
        ac, s, logs = mk(FakeResp())
        with self.assertRaises(a.ForaDaRota):
            ac.get("https://www.google.com/search?q=acidente+mineracao")
        self.assertEqual(s.chamadas, [])
        self.assertEqual(logs[0]["resultado"], "fora_da_rota")

    def test_redirecionamento_para_fora_da_rota_para(self):
        ac, s, logs = mk(FakeResp(url="https://exemplo.com/login"))
        with self.assertRaises(a.ForaDaRota):
            ac.get(URL)
        self.assertEqual(logs[0]["url_final"], "https://exemplo.com/login")

    def test_limite_de_requisicoes(self):
        ac, s, logs = mk(FakeResp(), FakeResp(), max_requisicoes=1)
        ac.get(URL)
        with self.assertRaises(a.LimiteDeRequisicoes):
            ac.get(URL + "?x=1")

    def test_download_stream_ok_e_hash(self):
        corpo = b"PK\x03\x04" + b"x" * 5000
        ac, s, logs = mk(FakeResp(body=corpo, ctype="application/zip", headers={"Content-Length": str(len(corpo))}))
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.zip")
            reg = ac.baixar_arquivo("https://dadosabertos.anm.gov.br/SCM/microdados/x.zip", dest, max_bytes=10_000)
            self.assertEqual(os.path.getsize(dest), len(corpo))
            self.assertEqual(reg["hash"], a.sha256(corpo))

    def test_download_html_no_lugar_do_arquivo_e_recusado(self):
        ac, s, logs = mk(FakeResp(body=b"<html>erro</html>", ctype="text/html"))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(a.AcessoInterrompido):
                ac.baixar_arquivo("https://dadosabertos.anm.gov.br/x.zip", os.path.join(d, "a.zip"), 1000)
        self.assertEqual(logs[0]["resultado"], "erro_http")

    def test_download_tamanho_acima_do_limite_e_truncado(self):
        ac, s, logs = mk(FakeResp(body=b"z" * 3000, ctype="application/zip"))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(a.AcessoInterrompido):
                ac.baixar_arquivo("https://dadosabertos.anm.gov.br/x.zip", os.path.join(d, "a.zip"), 1000)

    def test_download_truncado_content_length(self):
        ac, s, logs = mk(FakeResp(body=b"z" * 500, ctype="application/zip", headers={"Content-Length": "900"}))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(a.AcessoInterrompido):
                ac.baixar_arquivo("https://dadosabertos.anm.gov.br/x.zip", os.path.join(d, "a.zip"), 10_000)
        self.assertIn("truncado", logs[0]["motivo_interrupcao"])


class TestExpansao(unittest.TestCase):
    HTML = """<a href="/a/comunicado 179.pdf">PDF</a><a href="javascript:void(0)">x</a><a href="mailto:a@b.c">m</a>
      <a href="https://exemplo.com/x.pdf">fora</a><a href="/a/comunicado 179.pdf">dup</a><a href="/b/ata.docx#p">ata</a><a href="/c/pagina">pág</a>"""

    def test_inventario_reproduzivel_limitado_e_so_oficial(self):
        base = "https://meioambiente.mg.gov.br/comunicados/2026"
        r1 = a.inventariar_links(self.HTML, base)
        r2 = a.inventariar_links(self.HTML, base)
        self.assertEqual(r1, r2)
        self.assertEqual([x["extensao"] for x in r1], [".pdf", ".docx"])
        self.assertTrue(all(x["url"].startswith("https://meioambiente.mg.gov.br/") for x in r1))
        self.assertEqual(len(a.inventariar_links(self.HTML, base, limite=1)), 1)

    def test_busca_complementar_limitada_e_para_quando_coberta(self):
        lb = a.LimiteDeBuscas(maximo=2)
        self.assertFalse(lb.pode("lacuna", evidencia_ja_coberta=True))
        lb.registrar("T1", "q1", "campo X"); lb.registrar("T1", "q2", "campo X")
        self.assertFalse(lb.pode("campo X", False))
        with self.assertRaises(a.LimiteDeRequisicoes):
            lb.registrar("T1", "q3", "campo X")


class TestLogBusca(unittest.TestCase):
    def test_mapeia_para_colunas_existentes(self):
        ac, s, logs = mk(FakeResp(status=403))
        with self.assertRaises(a.BarreiraDeAcesso):
            ac.get(URL, params={"a": 1})
        l = linha_log_busca(logs[0], "EXEC", "S1", "EMP")
        self.assertEqual(set(l), {"execucao_id", "source_id", "url_requisitada", "parametros", "data_hora", "codigo_http",
                                  "url_final", "hash_conteudo", "origem_vinculo", "erro", "empresa_id"})
        self.assertEqual(l["codigo_http"], 403)
        self.assertEqual(l["parametros"]["registro"]["resultado"], "barreira")
        self.assertEqual(l["parametros"]["params"], {"a": 1})


if __name__ == "__main__":
    unittest.main()

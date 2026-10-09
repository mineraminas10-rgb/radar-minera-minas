import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import main as m
import db_writer
from test_ingestao_blocos import dump_sintetico

ENV_OK = {"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_teste"}


class Tab:
    def __init__(self, sb, n): self.sb, self.n = sb, n
    def insert(self, l): self.sb.ins.append((self.n, l)); return self
    def execute(self):
        class R: data = []
        return R()


class SB:
    def __init__(self): self.ins = []
    def table(self, n): return Tab(self, n)


class TestRodadaM9A(unittest.TestCase):
    def setUp(self):
        self.o = {k: getattr(db_writer, k) for k in ("buscar_fonte", "criar_execucao", "finalizar_execucao", "registrar_log_coleta")}
        self.final = {}
        db_writer.buscar_fonte = lambda sb, empresa_id=None, carteira_id=None: {"id": "SRC", "empresa_id": "EMP", "carteira_id": "CART"}
        db_writer.criar_execucao = lambda sb, i, ambiente="piloto", empresa_id=None, carteira_id=None: "EXEC"
        db_writer.finalizar_execucao = lambda sb, e, totais, status_final="concluída": self.final.update(totais=totais, status=status_final)
        db_writer.registrar_log_coleta = lambda *a, **k: None
        self.op = m.processar_caso
        self.chamados = []
        m.processar_caso = lambda sb, ex, atos, **k: (self.chamados.append(atos) or {"criado": True, "processos": [atos[0].processo]})

    def tearDown(self):
        for k, v in self.o.items(): setattr(db_writer, k, v)
        m.processar_caso = self.op

    def test_rodada_em_blocos_sem_ia_e_com_metricas(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            sb = SB()
            r = m.run(d, sb=sb, env=ENV_OK, tamanho_bloco=9,
                      registro_download={"url_original": "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip",
                                         "status_http": 200, "resultado": "ok", "hash": "h", "metodo_acesso": "m9a_scm_zip"})
        res = r["resumo"]
        self.assertEqual(self.final["status"], "concluída")
        self.assertEqual(res["brutos"], 120)
        self.assertGreater(res["dentro_recorte"], 0)
        self.assertEqual(res["chamadas_ia"], 0)
        self.assertEqual(res["pre_ia_coletados"], res["casos_consolidados"])
        self.assertEqual(res["pre_ia_dispensados"] + res["pre_ia_elegiveis"], res["pre_ia_coletados"])
        self.assertEqual(len(self.chamados), res["casos_consolidados"])
        self.assertEqual([e["ok"] for e in res["diagnostico_etapas"]], [True] * len(res["diagnostico_etapas"]))
        self.assertEqual(len([1 for t, _ in sb.ins if t == "log_busca"]), 1)   # registro do download

    def test_limite_casos_e_amostra(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=5, max_linhas_evento=30, limite_casos=1)
        self.assertEqual(r["resumo"]["brutos"], 30)
        self.assertTrue(r["resumo"]["ingestao"]["amostra"])
        self.assertEqual(len(self.chamados), 1)

    def test_secrets_ausentes_falha_na_etapa_ambiente(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception) as c:
                m.run(d, sb=SB(), env={})
        self.assertIn("SUPABASE_URL", str(c.exception))

    def test_dump_incompleto_falha_com_etapa_nomeada(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d); os.remove(os.path.join(d, "Pessoa.txt"))
            with self.assertRaises(Exception) as c:
                m.run(d, sb=SB(), env=ENV_OK)
        self.assertIn("leitura_em_blocos_e_recorte", str(c.exception))
        self.assertEqual(self.final["status"], "falha")


if __name__ == "__main__":
    unittest.main()

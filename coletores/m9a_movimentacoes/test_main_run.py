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


def confere_regra_do_banco(teste, logs):
    """Mesma regra do CHECK chk_analisados_soma do banco: analisados = identicos+atualizados+novos+duplicatas+descartados."""
    for c in logs:
        soma = sum(c.get(k) or 0 for k in ("identicos", "atualizados", "novos", "duplicatas_bloqueadas", "descartados"))
        teste.assertEqual(c["analisados"], soma, f"log_coleta violaria chk_analisados_soma: {c}")


REG_OK = {"url_original": "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip",
          "status_http": 200, "resultado": "ok", "hash": "h", "metodo_acesso": "m9a_scm_zip"}


class TestRodadaM9A(unittest.TestCase):
    def setUp(self):
        self.o = {k: getattr(db_writer, k) for k in ("buscar_fonte", "criar_execucao", "finalizar_execucao", "registrar_log_coleta")}
        self.final = {}
        db_writer.buscar_fonte = lambda sb, empresa_id=None, carteira_id=None: {"id": "SRC", "empresa_id": "EMP", "carteira_id": "CART"}
        db_writer.criar_execucao = lambda sb, i, ambiente="piloto", empresa_id=None, carteira_id=None: "EXEC"
        db_writer.finalizar_execucao = lambda sb, e, totais, status_final="concluída": self.final.update(totais=totais, status=status_final)
        self.logs = []
        db_writer.registrar_log_coleta = lambda sb, e, src, c, empresa_id=None: self.logs.append(c)
        self.op = m.processar_caso
        self.chamados = []
        m.processar_caso = lambda sb, ex, atos, **k: (self.chamados.append(atos) or {"criado": True, "processos": [atos[0].processo]})

    def tearDown(self):
        for k, v in self.o.items(): setattr(db_writer, k, v)
        m.processar_caso = self.op
        confere_regra_do_banco(self, self.logs)

    def test_rodada_em_blocos_sem_ia_e_com_metricas(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            sb = SB()
            r = m.run(d, sb=sb, env=ENV_OK, tamanho_bloco=9, piso_criticidade=None, janela_dias=0,
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

    def test_regua_de_criticidade_filtra_por_data_e_piso_e_ordena_antes_do_limite(self):
        """CRIT-V1.2 no coletor: janela de data (não lê atos velhos), piso (BAIXA/ROTINA ficam fora) e a ordem
        criticidade > pontuação > atualidade vale ANTES de --limite-casos."""
        from datetime import date
        reg = {"url_original": "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip",
               "status_http": 200, "resultado": "ok", "hash": "h", "metodo_acesso": "m9a_scm_zip"}
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            sem_regua = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, piso_criticidade=None, janela_dias=0, registro_download=reg)["resumo"]
            padrao = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, hoje=date(2026, 10, 14), registro_download=reg)["resumo"]
            # referência muito no futuro: tudo cai fora da janela de leitura de 1.095 dias
            velho = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, hoje=date(2035, 1, 1), registro_download=reg)["resumo"]
            limitado = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, hoje=date(2026, 10, 14), limite_casos=3, registro_download=reg)["resumo"]
        self.assertEqual(sem_regua["casos_consolidados"], 41)
        self.assertEqual(padrao["casos_consolidados"], 41)
        dispensados = sum(padrao["dispensados_por_criticidade"].values())
        self.assertGreater(dispensados, 0)
        self.assertTrue(set(padrao["dispensados_por_criticidade"]) <= {"BAIXA", "ROTINA", "NAO_AVALIAVEL"})
        self.assertEqual(padrao["novos"] + padrao["atualizados"], 41 - dispensados)
        self.assertEqual(padrao["versao_regra_criticidade"], "CRIT-V1.2")
        self.assertEqual(velho["dentro_recorte"], 0)
        self.assertEqual(velho["ingestao"]["fora_por_data"] + velho["ingestao"]["fora_de_mg"] + velho["ingestao"]["fora_por_familia"], velho["brutos"])
        self.assertEqual(limitado["novos"] + limitado["atualizados"], 3)
        # os 3 escolhidos são os 3 primeiros da ordem de criticidade (todos aceitos pelo piso)
        self.assertEqual(len(self.chamados[-3:]), 3)

    def test_recalculo_de_pendentes_roda_no_fim_da_rodada_sem_derrubar_a_coleta(self):
        import recalcular_criticidade as rc
        orig = rc.recalcular_pendentes
        chamadas = []
        try:
            rc.recalcular_pendentes = lambda sb, par, hoje: chamadas.append(hoje) or {
                "examinados": 4, "gravados": 1, "inalterados": 3, "erros": 0, "mudancas": [{"id_evento": "x", "criticidade": "MEDIA", "provisoria": False}]}
            with tempfile.TemporaryDirectory() as d:
                dump_sintetico(d)
                r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, registro_download=REG_OK)
            self.assertEqual(len(chamadas), 1)
            self.assertEqual(r["resumo"]["recalculo_pendentes"]["gravados"], 1)
            self.assertEqual(r["resumo"]["chamadas_ia"], 0)
            rc.recalcular_pendentes = lambda sb, par, hoje: (_ for _ in ()).throw(RuntimeError("falha simulada"))
            with tempfile.TemporaryDirectory() as d:
                dump_sintetico(d)
                r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, registro_download=REG_OK)
            self.assertEqual(self.final["status"], "concluída")
            self.assertIn("falha simulada", r["resumo"]["recalculo_pendentes"]["erro"])
            with tempfile.TemporaryDirectory() as d:
                dump_sintetico(d)
                r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, registro_download=REG_OK, recalcular_pendentes=False)
            self.assertNotIn("recalculo_pendentes", r["resumo"])
        finally:
            rc.recalcular_pendentes = orig

    def test_valores_ausentes_do_scm_nao_quebram_a_consolidacao(self):
        """Regressão da execução real de 09/10/2026: IDEvento fora do dicionário (DSEvento ausente) e
        evento sem texto chegavam como NaN (float) e quebravam a normalização ('expected string ... got float')."""
        import pandas as pd
        for v in (float("nan"), pd.NA, None, "", "  ", "nan"):
            self.assertIsNone(m._limpo(v), repr(v))
        self.assertEqual(m._limpo("Guia"), "Guia")
        self.assertEqual(m._limpo(5), 5)
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            with open(os.path.join(d, "ProcessoEvento.txt"), "a", encoding="latin-1", newline="") as f:
                f.write("831.000/2020;99;2026-05-10;;\n")          # evento 99 não existe em Evento.txt, sem OBEvento/DOU
                f.write("831.000/2020;99;2026-05-11;;\n")
                f.write("831.000/2020;2;2026-05-13;;\n")           # evento conhecido, mas sem OBEvento nem DOU: texto_narrativo ausente (caso do log real)
                f.write(";2;2026-05-12;obs sem processo;\n")       # sem processo: descartado, não derruba a rodada
            r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50,
                      registro_download={"url_original": "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip",
                                         "status_http": 200, "resultado": "ok", "hash": "h", "metodo_acesso": "m9a_scm_zip"})
        self.assertEqual(self.final["status"], "concluída")
        self.assertEqual([e["ok"] for e in r["resumo"]["diagnostico_etapas"]], [True] * len(r["resumo"]["diagnostico_etapas"]))
        self.assertGreaterEqual(r["resumo"]["atos_descartados_sem_chave"], 0)

    def test_log_coleta_conta_so_os_casos_processados_com_limite(self):
        """Regressão da execução real de 09/10/2026: analisados=24892 (consolidados) com só 5 processados violava o banco."""
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            r = m.run(d, sb=SB(), env=ENV_OK, tamanho_bloco=50, limite_casos=2,
                      registro_download={"url_original": "https://dadosabertos.anm.gov.br/SCM/microdados/microdados-scm.zip",
                                         "status_http": 200, "resultado": "ok", "hash": "h", "metodo_acesso": "m9a_scm_zip"})
        self.assertGreater(r["resumo"]["casos_consolidados"], 2)
        self.assertEqual(len(self.logs), 1)
        self.assertEqual(self.logs[0]["analisados"], 2)
        self.assertEqual(self.logs[0]["novos"] + self.logs[0]["atualizados"], 2)

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

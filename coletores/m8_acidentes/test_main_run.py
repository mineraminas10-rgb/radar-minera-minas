"""Rodada completa do M8 com banco e HTTP falsos: etapas, barreiras, deduplicação, sem IA."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import main as m
import extractor
import db_writer

LISTA = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"
PAGINA = ("<html><body><h1>Comunicado 179/2026</h1><p>" + "Vazamento de rejeito em barragem de mineração no município de Itabira, "
          "atingindo curso d'água. Empresa informou medidas de contenção. " * 5 + "</p></body></html>")
HTML_LISTA = """<table><tr><td>179/2026</td><td><a href="/comunicados/179-2026">Itabira</a></td></tr>
<tr><td>180/2026</td><td><a href="/comunicados/180-2026">Mariana</a></td></tr>
<tr><td>cabecalho sem protocolo</td><td><a href="/x">x</a></td></tr></table>"""
ENV_OK = {"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_teste"}


class Resp:
    def __init__(self, status=200, body="", ctype="text/html; charset=utf-8", url=None):
        self.status_code, self.content, self.text = status, body.encode(), body
        self.headers = {"Content-Type": ctype}; self.url = url; self.request = None


class Sessao:
    def __init__(self, mapa):
        self.mapa, self.chamadas = mapa, []
    def get(self, url, **kw):
        self.chamadas.append(url)
        r = self.mapa[url]
        r.url = r.url or url
        return r


class Tab:
    def __init__(self, sb, nome): self.sb, self.nome, self.dados, self.filtros = sb, nome, None, []
    def select(self, *a, **k): return self
    def eq(self, c, v): self.filtros.append((c, v)); return self
    def insert(self, linha): self.sb.inseridos.append((self.nome, linha)); self.dados = [linha]; return self
    def execute(self):
        class R: pass
        r = R(); r.data = [x for x in self.sb.tabelas.get(self.nome, []) if all(x.get(c) == v for c, v in self.filtros)]; return r


class SB:
    def __init__(self, tabelas=None): self.tabelas, self.inseridos = tabelas or {}, []
    def table(self, nome): return Tab(self, nome)


class TestIsolamentoM8(unittest.TestCase):
    def test_processados_de_outra_empresa_nao_dispensam_a_coleta(self):
        sb = SB({"m8_acidentes_detalhe": [
            {"protocolo_semad": "179", "ano": 2026, "status_processamento": "processado", "hash_documento": "h", "empresa_id": "A"}]})
        self.assertEqual(m.carregar_processados(sb, "A"), {("179", 2026)} if "processado" in m.PROCESSADOS_FINAIS else set())
        self.assertEqual(m.carregar_processados(sb, "B"), set())

    def test_escrita_exige_empresa(self):
        with self.assertRaises(RuntimeError):
            db_writer.upsert_m8_detalhe(SB(), "ev", "179", 2026, {}, empresa_id=None)
        with self.assertRaises(RuntimeError):
            db_writer.buscar_evento_por_id_evento(SB(), "M8-179-2026", None)
        with self.assertRaises(RuntimeError):
            db_writer.criar_execucao(SB(), "X", empresa_id="A", carteira_id=None)


class TestRodadaM8(unittest.TestCase):
    def setUp(self):
        self.orig = {k: getattr(db_writer, k) for k in ("buscar_fonte", "criar_execucao", "finalizar_execucao", "registrar_log_coleta")}
        self.final = {}
        db_writer.buscar_fonte = lambda sb, empresa_id=None, carteira_id=None: {"id": "SRC", "empresa_id": "EMP", "carteira_id": "CART"}
        db_writer.criar_execucao = lambda sb, idexec, ambiente="piloto", empresa_id=None, carteira_id=None: "EXEC"
        db_writer.finalizar_execucao = lambda sb, eid, totais, status_final="concluída": self.final.update(totais=totais, status=status_final)
        db_writer.registrar_log_coleta = lambda *a, **k: None
        self.orig_proc = m.processar_item
        self.ia = 0
        def proc(sb, execucao_id, source_id, item, empresa_id=None, acessador=None):
            r = extractor.extrair(item.url_detalhe, acessador=acessador)
            return {"protocolo": item.protocolo, "acao": r.status_processamento == "falha_extracao" and "falha_extracao" or "processado",
                    "faixa": "provavel", "criado": True}
        m.processar_item = proc

    def tearDown(self):
        for k, v in self.orig.items(): setattr(db_writer, k, v)
        m.processar_item = self.orig_proc

    def rodar(self, mapa, sb=None, **kw):
        s = Sessao(mapa); sb = sb or SB()
        try:
            out = m.run(sb=sb, sessao_http=s, env=kw.pop("env", ENV_OK), **kw)
            return out, s, sb, None
        except Exception as e:
            return None, s, sb, e

    def test_fluxo_feliz_links_relativos_e_sem_ia(self):
        mapa = {LISTA: Resp(body=HTML_LISTA),
                "https://meioambiente.mg.gov.br/comunicados/179-2026": Resp(body=PAGINA),
                "https://meioambiente.mg.gov.br/comunicados/180-2026": Resp(body=PAGINA)}
        out, s, sb, err = self.rodar(mapa)
        self.assertIsNone(err)
        self.assertEqual(out["resumo"]["brutos"], 2)
        self.assertEqual(out["resumo"]["processados"], 2)
        self.assertEqual(s.chamadas[0], LISTA)
        self.assertEqual(out["resumo"]["chamadas_ia"], 0)
        self.assertEqual(self.final["status"], "concluída")
        logs = [l for t, l in sb.inseridos if t == "log_busca"]
        self.assertEqual(len(logs), 3)
        self.assertTrue(all(l["parametros"]["registro"]["resultado"] == "ok" for l in logs))
        self.assertEqual(out["resumo"]["pre_ia_elegiveis"], 2)

    def test_barreira_403_na_pagina_anual_para_e_registra(self):
        out, s, sb, err = self.rodar({LISTA: Resp(status=403, body="Forbidden")})
        self.assertIsNotNone(err)
        self.assertEqual(len(s.chamadas), 1)           # sem retry, sem contornar
        self.assertEqual(self.final["status"], "falha")
        self.assertEqual(self.final["totais"]["barreiras_de_acesso"][0]["status_http"], 403)
        self.assertEqual(self.final["totais"]["chamadas_ia"], 0)

    def test_pagina_sem_itens_falha_alto(self):
        out, s, sb, err = self.rodar({LISTA: Resp(body="<html><body><p>Sem tabela</p></body></html>")})
        self.assertIn("nenhum comunicado", str(err))
        self.assertEqual(self.final["status"], "falha")

    def test_item_ja_processado_nao_e_requisitado(self):
        sb = SB({"m8_acidentes_detalhe": [{"protocolo_semad": "179", "ano": 2026, "status_processamento": "processado", "hash_documento": "h", "empresa_id": "EMP"}]})
        mapa = {LISTA: Resp(body=HTML_LISTA), "https://meioambiente.mg.gov.br/comunicados/180-2026": Resp(body=PAGINA)}
        out, s, sb, err = self.rodar(mapa, sb=sb)
        self.assertIsNone(err)
        self.assertEqual(len(s.chamadas), 2)            # lista + 180; 179 nem foi aberto
        self.assertNotIn("https://meioambiente.mg.gov.br/comunicados/179-2026", s.chamadas)
        r = out["resumo"]
        self.assertEqual(r["identicos"], 1)
        self.assertEqual(r["pre_ia_por_motivo"]["enriquecimento_ja_concluido"], 1)

    def test_falha_com_pendente_volta_para_a_fila(self):
        sb = SB({"m8_acidentes_detalhe": [{"protocolo_semad": "179", "ano": 2026, "status_processamento": "falha_extracao", "hash_documento": None, "empresa_id": "EMP"}]})
        mapa = {LISTA: Resp(body=HTML_LISTA), "https://meioambiente.mg.gov.br/comunicados/179-2026": Resp(body=PAGINA),
                "https://meioambiente.mg.gov.br/comunicados/180-2026": Resp(body=PAGINA)}
        out, s, sb, err = self.rodar(mapa, sb=sb)
        self.assertEqual(out["resumo"]["processados"], 2)

    def test_barreira_em_item_preserva_alerta_basico_e_interrompe(self):
        mapa = {LISTA: Resp(body=HTML_LISTA),
                "https://meioambiente.mg.gov.br/comunicados/179-2026": Resp(status=429, body="Too many"),
                "https://meioambiente.mg.gov.br/comunicados/180-2026": Resp(body=PAGINA)}
        out, s, sb, err = self.rodar(mapa)
        self.assertIsNone(err)
        self.assertEqual(out["resultados"][0]["acao"], "falha_extracao")
        self.assertEqual(len(out["resultados"]), 1)     # parou
        self.assertNotIn("https://meioambiente.mg.gov.br/comunicados/180-2026", s.chamadas)
        self.assertEqual(out["resumo"]["pre_ia_por_motivo"]["bloqueado_por_falta_de_documento"], 1)
        self.assertEqual(len(out["resumo"]["barreiras_de_acesso"]), 1)

    def test_ambiente_sem_secrets_falha_na_etapa_ambiente(self):
        out, s, sb, err = self.rodar({}, env={})
        self.assertIn("ambiente", str(err))
        self.assertIn("SUPABASE_URL", str(err))
        self.assertEqual(s.chamadas, [])

    def test_link_para_fora_das_fontes_oficiais_nao_e_aberto(self):
        html = '<table><tr><td>181/2026</td><td><a href="https://noticias.exemplo.com/acidente">x</a></td></tr></table>'
        out, s, sb, err = self.rodar({LISTA: Resp(body=html)})
        self.assertEqual(s.chamadas, [LISTA])
        self.assertEqual(out["resultados"][0]["acao"], "falha_extracao")


if __name__ == "__main__":
    unittest.main()

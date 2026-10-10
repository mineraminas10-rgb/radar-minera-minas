"""Rodada completa do M8 com banco e HTTP falsos: etapas, barreiras, deduplicação, sem IA."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import main as m
import extractor
import db_writer

LISTA = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"
PAGINA = ("<html><body><h1>Comunicado 179/2026</h1><p>" + "Vazamento de rejeito em barragem de mineração no município de Itabira, "
          "atingindo curso d'água. Empresa informou medidas de contenção. " * 5 + "</p></body></html>")
def cartao(protocolo, href, municipio="Itabira", data="01/10/2026", id_arq="1"):
    """Cartão no formato REAL da página da SEMAD (Liferay): protocolo no nome da imagem, município/data no título."""
    titulo = f"Comunicado de Acidente - {municipio}/MG - {data}"
    return (f'<dd class=" card-page-item card-page-item-asset " data-qa-id="row" data-title="{titulo}">'
            f'<input type="checkbox" value="{id_arq}"><img alt="" src="./pagina_files/Emergência ambiental {protocolo}_2026.png">'
            f'<a class="card-title" href="{href}" title="{titulo}">{titulo}</a></dd>')


HTML_LISTA = ("<dl>" + cartao("179", "/comunicados/179-2026", "Itabira", "01/10/2026", "11")
              + cartao("180", "/comunicados/180-2026", "Mariana", "02/10/2026", "12")
              + '<dd class="x"><a href="/x">cabecalho sem protocolo</a></dd></dl>')
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


def confere_regra_do_banco(teste, logs):
    """Mesma regra do CHECK chk_analisados_soma do banco: analisados = identicos+atualizados+novos+duplicatas+descartados."""
    for c in logs:
        soma = sum(c.get(k) or 0 for k in ("identicos", "atualizados", "novos", "duplicatas_bloqueadas", "descartados"))
        teste.assertEqual(c["analisados"], soma, f"log_coleta violaria chk_analisados_soma: {c}")


class TestRodadaM8(unittest.TestCase):
    def setUp(self):
        self.orig = {k: getattr(db_writer, k) for k in ("buscar_fonte", "criar_execucao", "finalizar_execucao", "registrar_log_coleta")}
        self.final = {}
        db_writer.buscar_fonte = lambda sb, empresa_id=None, carteira_id=None: {"id": "SRC", "empresa_id": "EMP", "carteira_id": "CART"}
        db_writer.criar_execucao = lambda sb, idexec, ambiente="piloto", empresa_id=None, carteira_id=None: "EXEC"
        db_writer.finalizar_execucao = lambda sb, eid, totais, status_final="concluída": self.final.update(totais=totais, status=status_final)
        self.logs = []
        db_writer.registrar_log_coleta = lambda sb, e, src, c, empresa_id=None: self.logs.append(c)
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
        confere_regra_do_banco(self, self.logs)

    def test_contagens_do_log_respeitam_a_regra_do_banco_com_erros_e_descartados(self):
        resumo = {"brutos": 50, "identicos": 7, "erros": 3}
        resultados = [{"acao": "processado", "criado": True}, {"acao": "processado", "criado": False},
                      {"acao": "descartado", "criado": True}, {"acao": "falha_extracao", "criado": True},
                      {"acao": "erro", "erro": "x"}, {"acao": "processado", "criado": True}]
        c = m.contagens_log_coleta(resumo, resultados, 6)
        self.assertEqual((c["novos"], c["atualizados"], c["descartados"], c["identicos"], c["erros"]), (2, 1, 1, 7, 3))
        confere_regra_do_banco(self, [c])

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

    def test_paginacao_so_abre_mais_paginas_quando_falta_item_para_o_limite(self):
        pag2 = "https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view/9?curEntry=2"
        lista1 = HTML_LISTA.replace("</dl>", "</dl>") + (
            f'<ul class="pagination"><li><a class="page-link" href="{pag2}">2</a></li></ul>')
        lista2 = "<dl>" + cartao("178", "/comunicados/178-2026", "Betim", "30/09/2026", "10") + "</dl>"
        base = {LISTA: Resp(body=lista1), pag2: Resp(body=lista2),
                "https://meioambiente.mg.gov.br/comunicados/179-2026": Resp(body=PAGINA),
                "https://meioambiente.mg.gov.br/comunicados/180-2026": Resp(body=PAGINA),
                "https://meioambiente.mg.gov.br/comunicados/178-2026": Resp(body=PAGINA)}
        out, s, sb, err = self.rodar(dict(base), limite=2)
        self.assertIsNone(err)
        self.assertNotIn(pag2, s.chamadas)              # 2 itens da página 1 bastam para o limite
        self.assertEqual(out["resumo"]["brutos"], 2)
        out, s, sb, err = self.rodar(dict(base))         # sem limite: percorre tudo
        self.assertIsNone(err)
        self.assertIn(pag2, s.chamadas)
        self.assertEqual(out["resumo"]["brutos"], 3)

    def test_ambiente_sem_secrets_falha_na_etapa_ambiente(self):
        out, s, sb, err = self.rodar({}, env={})
        self.assertIn("ambiente", str(err))
        self.assertIn("SUPABASE_URL", str(err))
        self.assertEqual(s.chamadas, [])

    def test_link_para_fora_das_fontes_oficiais_nao_e_aberto(self):
        html = "<dl>" + cartao("181", "https://noticias.exemplo.com/acidente", id_arq="13") + "</dl>"
        out, s, sb, err = self.rodar({LISTA: Resp(body=html)})
        self.assertEqual(s.chamadas, [LISTA])
        self.assertEqual(out["resultados"][0]["acao"], "falha_extracao")


if __name__ == "__main__":
    unittest.main()

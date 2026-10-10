"""
Coletor M6 contra DOCUMENTOS E ÍNDICE REAIS do IGAM (baixados em 10/10/2026):
  ptp01_10_2026_21829.doc (Portaria 00020/2026 completa), ptp07_10_2026_21830.doc (anulação) e
  ptp17_09_2026_21823.doc (retificação) + o índice de publicações.
Os textos abaixo são o resultado REAL da conversão desses .doc (LibreOffice -> UTF-8); o índice é um trecho do HTML real.
Prova: leitura do índice, segmentação, classificação pelo verbo, filtro mineral sem usar nome de empresa, a
coleta de ponta a ponta sem IA e o respeito à regra de contagem do banco (chk_analisados_soma).
"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "comum"))

import discovery  # noqa: E402
import extractor  # noqa: E402
import main  # noqa: E402
import signals  # noqa: E402
from test_regressao_m6 import FakeSupabase, _Query, _Tabela, _Resultado  # noqa: E402

TEXTO_PORTARIA_20 = """﻿Portaria nº 00020/2026 de 01/10/2026 – Renovação da Portaria nº 00260/2021

Processo: 54513/2024 
Decisão: Deferido com condicionantes.
O Gerente de Regulação de Usos de Recursos Hídricos - GERUR, no uso da competência delegada pelo Diretor Geral do Instituto Mineiro de Gestão das Águas – Igam por meio da Portaria Igam nº 27, de 08 de setembro de 2025, determina: Art. 1º- Autorizar, pelo prazo de validade de 10 (dez) anos, ato relacionado com outorga de direito de uso de recursos hídricos, conforme descrito abaixo:
Empreendimento: Instituto Mineiro de Gestão das Águas – IGAM – Usuários de Água da Bacia do Rio Candonga 
CPFs e CNPJs: Vide Quadro Anexo
Municípios: Arcos, Formiga e Pains – MG.
Modos de usos: CAPTAÇÃO EM CORPO DE ÁGUA (RIOS, LAGOAS NATURAIS ETC) e CAPTAÇÃO EM BARRAMENTO EM CURSO DE ÁGUA, COM REGULARIZAÇÃO DE VAZÃO.
Bacia Estadual: Rio Candonga
Bacia Federal: Rio São Francisco
UPGRH – SF1 – CBH dos Afluentes do Alto São Francisco   
Curso D'agua: Rio Candonga e Afluentes
Coordenadas Geográficas: Latitude: Vide Quadro Anexo e Longitude: Vide Quadro Anexo      
Finalidade: Abastecimento público, Dessedentação de animais, Consumo industrial, Aquicultura e Irrigação.

"""

TEXTO_ANULACAO = """﻿PUBLICAÇÃO  DE  ANULAÇÃO  -  07/10/2026


Ato de Anulação:

Fica anulado o ato publicado dia 29/06/2026 da Portaria nº 15.01.0050552.2026 - Usuário: GSM Mineração Ltda. CNPJ: 29.196.180/0009-68. Motivo: Autotutela. Município: Barão de Cocais – MG.

"""

TEXTO_RETIFICACAO = """﻿PUBLICAÇÃO  DE  RETIFICAÇÃO  -  17/09/2026


Retificação:

Retifica-se a publicação do mantido o indeferimento publicado dia 16/09/2026. Onde se lê: Portaria nº 00640 publicada dia 28/04/2020. Requerente: Concrelagos Concreto Ltda. CNPJ: 07.015.016/0040-23. Curso d’água: Poço Tubular. Motivo: Conforme a decisão que indeferiu o pedido inicial. Leia-se: Portaria nº 00650 publicada dia 28/04/2020. Requerente: Concrelagos Concreto Ltda. CNPJ: 07.015.016/0040-23. Curso d’água: Poço Tubular. Motivo: Conforme a decisão que indeferiu o pedido inicial. Município: Congonhas - MG.

"""

INDICE_REAL = r"""<body>
<a href="https://outorga.meioambiente.mg.gov.br/arquivos/outorgas_ate_31_12_2008.zip">Listagem de outorgados até 31/12/2008 - 1.03 MB</a><br>
<a href="https://outorga.meioambiente.mg.gov.br/arquivos/outorgas_ate_25_02_11.zip">Listagem de outorgados de 01/01/09 a 25/02/2011 - 997 KB</a><br>
<a href="https://outorga.meioambiente.mg.gov.br/arquivos/outorgas_ate_31_12_2014.xlsx">Listagem de outorgados de 01/01/2014 a 31/12/2014 - 412 KB</a><br>
<a href="https://outorga.meioambiente.mg.gov.br/arquivos/outorgas_ate_31_12_2015.xlsx">Listagem de outorgados de 01/01/2015 a 31/12/2015 - 376 KB</a><br><br><br>
<h4>2026</h4><ul><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp07_10_2026_21830.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 07/10/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp01_10_2026_21828.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 01/10/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp01_10_2026_21829.doc">Portaria 20</a> publicada(s) em 01/10/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp30_09_2026_21827.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 30/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp24_09_2026_21826.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 24/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp23_09_2026_21825.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 23/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp22_09_2026_21824.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 22/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp17_09_2026_21823.doc">Portaria 0, Retificações</a> publicada(s) em 17/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp16_09_2026_21822.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 16/09/2026</li><li><a class="" href="https://outorga.meioambiente.mg.gov.br/arquivos/ptp04_09_2026_21821.doc">Portaria 0 e Cancelamentos</a> publicada(s) em 04/09/2026</li></ul></body>"""

U1 = "https://outorga.meioambiente.mg.gov.br/arquivos/ptp07_10_2026_21830.doc"
U2 = "https://outorga.meioambiente.mg.gov.br/arquivos/ptp01_10_2026_21829.doc"
U3 = "https://outorga.meioambiente.mg.gov.br/arquivos/ptp17_09_2026_21823.doc"


class TestIndiceReal(unittest.TestCase):
    def setUp(self):
        self.itens = discovery.parse_indice(INDICE_REAL)

    def test_so_publicacoes_em_ordem_e_sem_as_listagens_historicas(self):
        nomes = [i.nome_arquivo for i in self.itens]
        self.assertEqual(nomes[0], "ptp07_10_2026_21830.doc")
        self.assertEqual(nomes[1:3], ["ptp01_10_2026_21828.doc", "ptp01_10_2026_21829.doc"])
        self.assertTrue(all(n.startswith("ptp") for n in nomes))
        self.assertGreaterEqual(len(nomes), 10)

    def test_categoria_do_link_e_so_rotulo_e_data_vem_do_texto(self):
        primeiro = self.itens[0]
        self.assertEqual(primeiro.categoria, "Portaria 0 e Cancelamentos")
        self.assertEqual(primeiro.data_listada, "07/10/2026")
        self.assertEqual(discovery.data_iso(primeiro.data_listada), "2026-10-07")
        self.assertEqual(primeiro.url_documento, U1)

    def test_pagina_sem_publicacoes_devolve_vazio(self):
        self.assertEqual(discovery.parse_indice("<html><body><p>Manutenção</p></body></html>"), [])


class TestSegmentacaoReal(unittest.TestCase):
    def test_portaria_completa(self):
        atos = extractor.segmentar_documento(TEXTO_PORTARIA_20)
        self.assertEqual(len(atos), 1)
        a = atos[0]
        self.assertEqual(a.layout, "portaria_completa")
        self.assertEqual(a.processo_ou_portaria, "portaria-00020/2026")
        self.assertEqual(a.data_decisao, "01/10/2026")
        self.assertEqual(a.municipio, "Arcos, Formiga e Pains")
        self.assertIn("Candonga", a.titular)
        self.assertIn("Autorizar", a.trecho_decisorio)
        self.assertIn("Irrigação", a.finalidade_uso)

    def test_anulacao(self):
        atos = extractor.segmentar_documento(TEXTO_ANULACAO)
        self.assertEqual(len(atos), 1)
        a = atos[0]
        self.assertEqual((a.layout, a.tipo_publicacao), ("publicacao_curta", "ANULAÇÃO"))
        self.assertEqual(a.processo_ou_portaria, "portaria-15.01.0050552.2026")
        self.assertEqual(a.titular, "GSM Mineração Ltda")
        self.assertEqual(a.municipio, "Barão de Cocais")
        self.assertEqual(a.data_decisao, "07/10/2026")

    def test_retificacao_usa_o_numero_do_leia_se(self):
        a = extractor.segmentar_documento(TEXTO_RETIFICACAO)[0]
        self.assertEqual(a.processo_ou_portaria, "portaria-00650")      # "Onde se lê" era 00640
        self.assertEqual(a.titular, "Concrelagos Concreto Ltda")
        self.assertEqual(a.municipio, "Congonhas")

    def test_texto_para_vinculo_nao_contem_nome_nem_cnpj_do_titular(self):
        for texto in (TEXTO_ANULACAO, TEXTO_RETIFICACAO):
            a = extractor.segmentar_documento(texto)[0]
            self.assertNotIn(a.titular, a.texto_para_vinculo)
            self.assertNotIn("CNPJ", a.texto_para_vinculo)

    def test_documento_fora_dos_dois_layouts_devolve_zero_atos(self):
        self.assertEqual(extractor.segmentar_documento("Aviso geral sem portarias nem publicações."), [])
        self.assertEqual(extractor.segmentar_documento(""), [])

    def test_formato_real_pelos_bytes_e_nao_pela_extensao(self):
        self.assertEqual(extractor.detectar_formato(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"), "ole2")
        self.assertEqual(extractor.detectar_formato(b"%PDF-1.7"), "pdf")
        self.assertEqual(extractor.detectar_formato(b"PK\x03\x04"), "zip")

    @unittest.skipUnless(shutil.which("soffice") or shutil.which("libreoffice"), "LibreOffice não instalado")
    def test_conversao_real_de_doc_ida_e_volta(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as p:
            txt = os.path.join(p, "ato.txt")
            Path(txt).write_text(TEXTO_ANULACAO, encoding="utf-8")
            subprocess.run([shutil.which("soffice") or "libreoffice", f"-env:UserInstallationDir=file://{p}/perfil", "--headless",
                            "--convert-to", "doc", "--outdir", p, txt], capture_output=True, timeout=180)
            conteudo = Path(p, "ato.doc").read_bytes()
        self.assertEqual(extractor.detectar_formato(conteudo), "ole2")
        atos = extractor.segmentar_documento(extractor.extrair_texto(conteudo))
        self.assertEqual(atos[0].processo_ou_portaria, "portaria-15.01.0050552.2026")


class TestClassificacaoDosAtosReais(unittest.TestCase):
    def _classificar(self, texto):
        a = extractor.segmentar_documento(texto)[0]
        tipo = signals.classificar_ato(a.trecho_decisorio)
        vinculo = signals.tem_vinculo_mineral(signals.SinaisVinculoMineral(
            titular=a.titular, finalidade_uso=a.finalidade_uso or "", texto_livre=a.texto_para_vinculo))[0]
        return tipo, vinculo

    def test_portaria_de_abastecimento_e_irrigacao_nao_e_mineral(self):
        self.assertEqual(self._classificar(TEXTO_PORTARIA_20), ("concessao_outorga", "nao_mineral_confirmado"))

    def test_nome_da_empresa_com_mineracao_nao_confirma_vinculo(self):
        # GSM MINERAÇÃO: só o nome indica mineração; finalidade/atividade não estão no ato -> apuração, não "confirmado".
        self.assertEqual(self._classificar(TEXTO_ANULACAO), ("anulacao", "indeterminado"))

    def test_retificacao_e_pelo_verbo_nao_pelo_texto_do_indeferimento_citado(self):
        self.assertEqual(self._classificar(TEXTO_RETIFICACAO), ("retificacao", "indeterminado"))

    def test_palavra_mina_so_vale_inteira(self):
        s = signals.SinaisVinculoMineral(texto_livre="A Portaria determina que Minas Gerais ...")
        self.assertEqual(signals.tem_vinculo_mineral(s)[0], "indeterminado")
        s = signals.SinaisVinculoMineral(finalidade_uso="Uso na mina de ferro")
        self.assertEqual(signals.tem_vinculo_mineral(s)[0], "confirmado")


# ---------------------------------------------------------------- coleta de ponta a ponta (rede e banco falsos)
class _QComLike(_Query):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.likes = []

    def like(self, campo, padrao):
        self.likes.append((campo, padrao.strip("%")))
        return self

    def execute(self):
        r = super().execute()
        for campo, trecho in self.likes:
            r = _Resultado([x for x in r.data if trecho in (x.get(campo) or "")])
        return r


class _TabComLike(_Tabela):
    def select(self, *_c):
        return _QComLike(self.store, self.nome, "select")


class _SB(FakeSupabase):
    def table(self, nome):
        return _TabComLike(self.store, nome)


class _Resp:
    def __init__(self, corpo, ctype, url):
        self.status_code, self.content, self.url = 200, corpo, url
        self.text = corpo.decode("utf-8", "replace") if ctype.startswith("text") else ""
        self.headers = {"Content-Type": ctype}
        self.request = None


class _Sessao:
    def __init__(self, mapa):
        self.mapa, self.chamadas = mapa, []

    def get(self, url, **kw):
        self.chamadas.append(url)
        return self.mapa[url]


def _regra_do_banco(teste, c):
    soma = sum(c.get(k) or 0 for k in ("identicos", "atualizados", "novos", "duplicatas_bloqueadas", "descartados"))
    teste.assertEqual(c["analisados"], soma, f"violaria chk_analisados_soma: {c}")


ENV_OK = {"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_teste"}


class TestColetaDePontaAPonta(unittest.TestCase):
    def setUp(self):
        self.orig = {k: getattr(main.db_writer, k) for k in ("buscar_fonte_id", "criar_execucao", "finalizar_execucao", "registrar_log_coleta")}
        self.logs, self.final = [], {}
        main.db_writer.buscar_fonte_id = lambda sb, url, empresa_id=None, carteira_id=None: {"id": "SRC", "empresa_id": "EMP", "carteira_id": "CART"}
        main.db_writer.criar_execucao = lambda sb, i, ambiente="piloto", empresa_id=None, carteira_id=None: "EXEC"
        main.db_writer.finalizar_execucao = lambda sb, e, totais, status_final="concluída": self.final.update(totais=totais, status=status_final)
        main.db_writer.registrar_log_coleta = lambda sb, e, s, c, empresa_id=None: self.logs.append(c)
        self.orig_txt = extractor.extrair_texto
        textos = {b"DOC1": TEXTO_ANULACAO, b"DOC2": TEXTO_PORTARIA_20, b"DOC3": TEXTO_RETIFICACAO, b"VAZIO": "sem layout conhecido"}
        extractor.extrair_texto = lambda b: textos[bytes(b)]

    def tearDown(self):
        for k, v in self.orig.items():
            setattr(main.db_writer, k, v)
        extractor.extrair_texto = self.orig_txt
        for c in self.logs:
            _regra_do_banco(self, c)

    def _mapa(self, extra=None):
        base = {discovery.URL_INDICE: _Resp(INDICE_REAL.encode(), "text/html", discovery.URL_INDICE),
                U1: _Resp(b"DOC1", "application/msword", U1), U2: _Resp(b"DOC2", "application/msword", U2)}
        base.update(extra or {})
        return base

    def _rodar(self, mapa, sb=None, **kw):
        s = _Sessao(mapa)
        sb = sb or _SB()
        return main.coletar(sb=sb, sessao_http=s, env=ENV_OK, **kw), s, sb

    def test_le_os_tres_documentos_mais_recentes_sem_ia(self):
        # índice real: 1o = 07/10 (anulação), 2o = 01/10 (21828, aqui com a retificação), 3o = 01/10 (Portaria 20)
        u_21828 = "https://outorga.meioambiente.mg.gov.br/arquivos/ptp01_10_2026_21828.doc"
        mapa = self._mapa({u_21828: _Resp(b"DOC3", "application/msword", u_21828)})
        out, s, sb = self._rodar(mapa, limite=3)
        r = out["resumo"]
        self.assertEqual((r["documentos_lidos"], r["chamadas_ia"], r["documentos_sem_atos"]), (3, 0, 0))
        self.assertEqual(self.final["status"], "concluída")
        eventos = {e["id_evento"]: e for e in sb.store["events"]}
        self.assertEqual(len(eventos), 3)
        gsm = eventos["igam-m6-portaria-150100505522026"]
        self.assertEqual(gsm["status_editorial"], "em_apuracao")          # nome "Mineração" não vira vínculo
        self.assertEqual(gsm["tipo_evento"], "anulacao")
        self.assertEqual(gsm["data_evento"], "2026-10-07")
        self.assertEqual(gsm["url_oficial"], U1)
        irrigacao = eventos["igam-m6-portaria-00020-2026"]
        self.assertEqual(irrigacao["status_editorial"], "descartado")      # abastecimento/irrigação: fora do núcleo mineral
        self.assertNotIn("event_scores", sb.store)                          # nenhum score inventado
        self.assertTrue(all(e.get("revisao_humana") in (None, "Pendente") for e in eventos.values()))
        c = self.logs[0]
        self.assertEqual((c["descartados"], c["novos"], c["erros"]), (1, 2, 0))

    def test_segunda_rodada_nao_baixa_de_novo_o_que_ja_virou_evento(self):
        mapa = self._mapa()
        sb = _SB()
        self._rodar(mapa, sb=sb, limite=1)                    # só ptp07_10 (anulação)
        out, s, sb = self._rodar(self._mapa(), sb=sb, limite=1)
        self.assertNotIn(U1, s.chamadas)                      # já processado: não é requisitado
        self.assertEqual(out["resumo"]["documentos_ja_processados"], 1)

    def test_documento_sem_layout_conhecido_vira_erro_visivel(self):
        mapa = self._mapa({U1: _Resp(b"VAZIO", "application/msword", U1)})
        out, s, sb = self._rodar(mapa, limite=1)
        self.assertEqual(out["resumo"]["documentos_sem_atos"], 1)
        self.assertEqual(out["resumo"]["erros"], 1)
        self.assertEqual(sb.store.get("events", []), [])

    def test_indice_sem_publicacoes_falha_alto(self):
        mapa = {discovery.URL_INDICE: _Resp(b"<html><body>fora do ar</body></html>", "text/html", discovery.URL_INDICE)}
        with self.assertRaises(Exception) as ctx:
            self._rodar(mapa)
        self.assertIn("nenhuma publicação", str(ctx.exception))
        self.assertEqual(self.final["status"], "falha")

    def test_barreira_403_no_indice_para_sem_contornar(self):
        r403 = _Resp(b"Forbidden", "text/html", discovery.URL_INDICE)
        r403.status_code = 403
        with self.assertRaises(Exception):
            self._rodar({discovery.URL_INDICE: r403})
        self.assertEqual(self.final["status"], "falha")

    def test_contagens_respeitam_a_regra_do_banco(self):
        res = [{"acao": "descartado", "criado": True}, {"acao": "requer_apuracao_humana", "criado": True},
               {"acao": "aguardando_score", "criado": False}, {"acao": "erro", "erro": "x"}, {"acao": "processado", "criado": True}]
        c = main.contagens_log_coleta(res, brutos=5, identicos=2)
        self.assertEqual((c["descartados"], c["novos"], c["atualizados"], c["erros"]), (1, 2, 1, 1))
        _regra_do_banco(self, c)


if __name__ == "__main__":
    unittest.main()

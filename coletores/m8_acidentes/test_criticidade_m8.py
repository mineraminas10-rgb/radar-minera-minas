import os, sys, unittest
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comum"))
import main as m
import discovery
from scoring import SignaisGravidade


class _Q:
    def __init__(self, sb): self.sb, self.f, self.op, self.p = sb, {}, "select", None
    def select(self, *_): return self
    def eq(self, k, v): self.f[k] = v; return self
    def update(self, p): self.op, self.p = "update", p; return self
    def insert(self, p): self.op, self.p = "insert", p; return self
    def execute(self):
        class R: data = []
        r = R()
        if self.op == "select": r.data = [x for x in self.sb.rows if all(x.get(k) == v for k, v in self.f.items())]
        elif self.op == "update":
            for x in self.sb.rows:
                if all(x.get(k) == v for k, v in self.f.items()): x.update(self.p)
        else: self.sb.rows.append(dict(self.p))
        return r


class SB:
    def __init__(self): self.rows = []
    def table(self, n): return _Q(self)


def item(titulo):
    return discovery.ItemInventario(protocolo="1/2026", ano=2026, titulo_fonte=titulo, municipio="Ouro Preto",
                                    data_publicada=None, url_detalhe="https://x", hash_linha="h") \
        if hasattr(discovery, "ItemInventario") else None


class TestCriticidadeM8(unittest.TestCase):
    def test_falha_de_extracao_vira_nao_avaliavel_nunca_rotina(self):
        sb = SB()
        m._gravar_criticidade_m8(sb, "E1", item("Comunicado 05/10/2026"), "EMP", "falha_extracao", "contextual", tem_evidencia=False,
                                 motivo_falha="OCR não produziu texto legível")
        self.assertEqual(len(sb.rows), 1)
        self.assertEqual(sb.rows[0]["versao_score"], "CRIT-V1.2")
        self.assertEqual(sb.rows[0]["componentes"]["criticidade"], "NAO_AVALIAVEL")
        self.assertIsNone(sb.rows[0]["prioridade"])
        self.assertEqual(sb.rows[0]["componentes"]["motivos"], ["nao_avaliavel_falha_de_extracao"])

    def test_teto_de_requisicoes_e_detectado_como_limite_nao_como_falha(self):
        self.assertTrue(m._parou_por_limite("limite:limite de 200 requisições por rodada"))
        self.assertTrue(m._parou_por_limite("página individual sem texto suficiente (limite:limite de 200 requisições por rodada@u)"))
        self.assertFalse(m._parou_por_limite("OCR não produziu texto legível"))
        self.assertFalse(m._parou_por_limite("barreira_de_acesso:captcha"))
        self.assertFalse(m._parou_por_limite(None))

    def test_palavra_chave_recente_e_media_nunca_alta(self):
        sb = SB()
        sig = SignaisGravidade(atingiu_ou_pode_atingir_curso_dagua=True)
        m._gravar_criticidade_m8(sb, "E2", item("Comunicado 05/10/2026"), "EMP", "processado", "confirmado",
                                 sig_gravidade=sig, score_g=3, hoje=date(2026, 10, 14))
        self.assertEqual(sb.rows[0]["componentes"]["criticidade"], "MEDIA")
        self.assertEqual(sb.rows[0]["prioridade"], "C")

    def test_data_do_cabecalho_do_comunicado_vale_mais_que_titulo_e_evita_teto_sem_data(self):
        sb = SB()
        sig = SignaisGravidade(atingiu_ou_pode_atingir_curso_dagua=True)
        # título sem data (como "Serra do Salitre/MG"): sem a data do cabeçalho o teto seria BAIXA
        m._gravar_criticidade_m8(sb, "E4", item("Comunicado de Acidente - Serra do Salitre/MG"), "EMP", "processado", "confirmado",
                                 sig_gravidade=sig, score_g=3, hoje=date(2026, 10, 14),
                                 data_ocorrencia="2026-09-30T20:00:00-03:00")
        self.assertEqual(sb.rows[0]["componentes"]["criticidade"], "MEDIA")
        sb2 = SB()
        m._gravar_criticidade_m8(sb2, "E5", item("Comunicado de Acidente - Serra do Salitre/MG"), "EMP", "processado", "confirmado",
                                 sig_gravidade=sig, score_g=3, hoje=date(2026, 10, 14))
        self.assertEqual(sb2.rows[0]["componentes"]["criticidade"], "BAIXA")

    def test_processar_item_grava_campos_estruturados_e_nao_marca_fatos_como_confirmados(self):
        from unittest import mock
        import extractor
        import db_writer
        from test_campos_comunicado import C179
        res = extractor.ResultadoExtracao(texto=C179, metodo_extracao="ocr", qualidade_ocr="boa", paginas_processadas=1,
                                          hash_documento="h", status_processamento="processado")
        it = discovery.ItemInventario(protocolo="179", ano=2026, titulo_fonte="Comunicado de Acidente - Conceição do Pará/MG",
                                      municipio="Conceição do Pará", data_publicada=None, url_detalhe="https://x", hash_linha="h")
        sb = SB()
        with mock.patch.object(extractor, "extrair", lambda url, acessador=None: res), \
             mock.patch.multiple(db_writer, buscar_regra_evento=mock.DEFAULT, upsert_evento=mock.DEFAULT, upsert_m8_detalhe=mock.DEFAULT,
                                 gravar_score=mock.DEFAULT, gravar_documento=mock.DEFAULT, gravar_evidencias_campo=mock.DEFAULT,
                                 gravar_marco_timeline=mock.DEFAULT, buscar_antecedentes_m8=mock.DEFAULT,
                                 gravar_eventos_relacionados=mock.DEFAULT, gravar_checklist_editorial=mock.DEFAULT,
                                 gravar_job_enriquecimento=mock.DEFAULT) as dbm:
            dbm["buscar_regra_evento"].return_value = None
            dbm["upsert_evento"].return_value = ("EV", True)
            dbm["gravar_evidencias_campo"].return_value = []
            dbm["buscar_antecedentes_m8"].return_value = []
            m.processar_item(sb, "EXE", "SRC", it, empresa_id="EMP")
            detalhe = dbm["upsert_m8_detalhe"].call_args.args[4]
        self.assertEqual(detalhe["modalidade"], "Instalaçao industrial")
        self.assertEqual(detalhe["data_hora_ocorrencia"], "2026-08-29T16:30:00-03:00")
        self.assertEqual(detalhe["produto"], "Rejeito mineral aurífero")
        self.assertIn("vazamento de rejeito", detalhe["descricao_literal"])
        for proibido in ("atingiu_curso_agua", "vitimas", "evacuacao", "bloqueio_via", "saiu_limite_operacao"):
            self.assertNotIn(proibido, detalhe)
        # a data do cabeçalho (29/08) alimentou a régua: ocorrência de 46 dias antes de 14/10 => fora dos 30 dias de ALTA, dentro dos 90 de MEDIA
        self.assertEqual(sb.rows[-1]["versao_score"], "CRIT-V1.2")

    def test_processar_item_no_teto_nao_grava_nada_e_devolve_adiado(self):
        import extractor
        orig = extractor.extrair
        extractor.extrair = lambda url, acessador=None: extractor.ResultadoExtracao(
            texto="", metodo_extracao="nativo", qualidade_ocr=None, paginas_processadas=0, hash_documento="",
            status_processamento="falha_extracao", motivo_falha="limite:limite de 200 requisições por rodada")
        class SBQuebra:
            def table(self, n): raise AssertionError("nada pode ser gravado quando o teto de requisições acaba")
        try:
            r = m.processar_item(SBQuebra(), "EXEC", "SRC", item("Comunicado 05/10/2026"), empresa_id="EMP", acessador=object())
        finally:
            extractor.extrair = orig
        self.assertEqual(r["acao"], "adiado_por_limite")

    def test_erro_de_gravacao_nao_derruba_a_coleta(self):
        class Quebrado:
            def table(self, n): raise RuntimeError("banco fora")
        self.assertIsNone(m._gravar_criticidade_m8(Quebrado(), "E3", item("x"), "EMP", "processado", "provavel"))


if __name__ == "__main__":
    unittest.main()

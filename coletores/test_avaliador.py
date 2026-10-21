import unittest
from datetime import date
from avaliador import avaliar_evento, gerar_ficha_html

class AvaliadorImpactoTest(unittest.TestCase):
    def base(self):
        return {
            "numero_processo": "123/2026",
            "metadados": "Relatório de barragem de rejeitos",
            "texto_fiscal": "O fiscal identificou infiltração de efluentes no aquífero e perda de potabilidade no poço artesiano da comunidade.",
            "fonte_url": "https://meioambiente.mg.gov.br/ato",
            "documento_url": "https://meioambiente.mg.gov.br/relatorio.pdf",
            "data_ultima_movimentacao": "2026-01-01",
            "jurisdicao": "minas gerais",
            "marco_inicial_prescricao": "2025-01-01",
            "inercia_exclusiva_estado": False,
        }

    def test_candidato_exige_setor_e_nexo_ambiental_social(self):
        r = avaliar_evento(self.base(), date(2026, 10, 21))
        self.assertEqual(r["status_triagem"], "candidato_fila_editor")
        self.assertEqual(r["revisao_humana"], "pendente")
        self.assertFalse(r["publicado"])
        self.assertTrue(r["trecho_cobre_os_dois_nexos"])

    def test_cnae_pode_suprir_termo_de_atividade(self):
        e = self.base()
        e["metadados"] = "Relatório de infiltração de efluentes"
        e["cnae"] = "07.10-3/01"
        self.assertEqual(avaliar_evento(e)["status_triagem"], "candidato_fila_editor")

    def test_impacto_precisa_estar_no_texto_do_fiscal(self):
        e = self.base()
        e["texto_fiscal"] = "Vistoria realizada na área."
        e["texto_documento"] = "aquífero e poço artesiano"
        self.assertEqual(avaliar_evento(e)["motivo_status"], "sem_indicio_ambiental_subterraneo")

    def test_nao_confunde_substrings_com_atividade(self):
        e = self.base()
        e["metadados"] = "Tesouro estadual e obras urbanas"
        e["cnae"] = "49.30-2/01"
        self.assertEqual(avaliar_evento(e)["motivo_status"], "sem_atividade_mineraria_direta_ou_cnae_alvo")

    def test_descarta_sem_atividade_direta_ou_cnae(self):
        e = self.base()
        e["metadados"] = "Relatório genérico de contaminação"
        e["cnae"] = "49.30-2/01"
        self.assertEqual(avaliar_evento(e)["motivo_status"], "sem_atividade_mineraria_direta_ou_cnae_alvo")

    def test_descarta_sem_nexo_social(self):
        e = self.base()
        e["texto_fiscal"] = "Contaminação do solo por metais pesados próxima à cava da mina."
        self.assertEqual(avaliar_evento(e)["motivo_status"], "sem_indicio_de_afetacao_humana_social")

    def test_nao_inventa_multa_ou_conclusao_prescricional(self):
        r = avaliar_evento(self.base(), date(2026, 10, 21))
        self.assertIsNone(r["auditoria_status"]["valor_multa"])
        self.assertIsNone(r["auditoria_status"]["meses_ate_marco_prescricional_estimado"])
        self.assertIn("não calculado", r["auditoria_status"]["alerta_juridico"])

    def test_anm_ganha_alerta_condicional_de_paralisacao_federal(self):
        e = self.base()
        e.update({"jurisdicao": "ANM", "data_ultima_movimentacao": "2022-01-01",
                  "marco_inicial_prescricao": None})
        r = avaliar_evento(e, date(2026, 10, 21))["auditoria_status"]
        self.assertIn("verificar se o processo aguarda julgamento", r["alerta_juridico"])
        self.assertIsNone(r["meses_ate_marco_prescricional_estimado"])

    def test_dias_parado_e_calculado_com_data_fornecida(self):
        r = avaliar_evento(self.base(), date(2026, 1, 11))
        self.assertEqual(r["auditoria_status"]["dias_desde_ultima_movimentacao"], 10)

    def test_impacto_superficial_e_pescadores_passa_funil_ampliado(self):
        e = self.base()
        e["texto_fiscal"] = "Houve assoreamento do córrego e prejuízo à economia da pesca local."
        r = avaliar_evento(e)
        self.assertEqual(r["status_triagem"], "candidato_fila_editor")
        self.assertIn("assoreamento", r["evidencias_ambientais"])
        self.assertIn("economia da pesca", r["evidencias_sociais"])

    def test_inatividade_annualiza_prioridade_sem_chamar_de_prescricao(self):
        e = self.base()
        e["data_ultima_movimentacao"] = "2025-10-20"
        r = avaliar_evento(e, date(2026, 10, 21))
        self.assertEqual(r["prioridade_exposicao"], "ALTA_RELEVANCIA_ALERTA_VERMELHO")
        self.assertIn("não calculado", r["auditoria_status"]["alerta_juridico"])

    def test_ficha_neutra_escapa_html(self):
        e = self.base()
        e["texto_fiscal"] = "<script>alert(1)</script> Aquífero e poço artesiano afetados."
        e["razao_social_empreendedor"] = "Empresa <Norte>"
        html = gerar_ficha_html(avaliar_evento(e))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<blockquote>", html)

    def test_nao_gera_ficha_para_evento_descartado(self):
        e = self.base()
        e["metadados"] = "Relatório geral"
        e["cnae"] = "49.30"
        with self.assertRaises(ValueError):
            gerar_ficha_html(avaliar_evento(e))

if __name__ == "__main__":
    unittest.main()

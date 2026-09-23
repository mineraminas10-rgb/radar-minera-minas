import unittest

from signals import extrair_evidencias_campo, extrair_signais_m9a


class TestEvidenciasCampoM9A(unittest.TestCase):

    def test_campos_preenchidos_viram_evidencia_literal(self):
        linha = {
            "processo": "830.661/2019", "evento_tipo": "Cessão de direitos minerários",
            "titular": "DVM Mineração", "substancia": "minério de ferro",
            "municipio": "Itabira", "data_evento": "2025-08-01",
        }
        evidencias = extrair_evidencias_campo(linha)
        campos = {e["campo"]: e["trecho_literal"] for e in evidencias}
        self.assertEqual(len(evidencias), 6)
        self.assertEqual(campos["processo"], "830.661/2019")
        self.assertEqual(campos["titular"], "DVM Mineração")

    def test_campos_ausentes_nao_geram_evidencia(self):
        linha = {"processo": "830.661/2019", "evento_tipo": "Cessão", "titular": None,
                  "substancia": "", "municipio": None, "data_evento": "2025-08-01"}
        evidencias = extrair_evidencias_campo(linha)
        campos = {e["campo"] for e in evidencias}
        self.assertNotIn("titular", campos)
        self.assertNotIn("substancia", campos)
        self.assertNotIn("municipio", campos)
        self.assertIn("processo", campos)
        self.assertIn("data_evento", campos)

    def test_consistencia_com_sinal_empresa_relevante(self):
        # se o sinal empresa_relevante disparou, a evidência do campo
        # titular precisa existir pra sustentar essa afirmação
        linha = {"processo": "1/2026", "evento_tipo": "Concessão de lavra",
                  "titular": "Vale S.A.", "substancia": "ferro", "municipio": "Itabira",
                  "data_evento": "2026-01-01"}
        sinais = extrair_signais_m9a(linha)
        evidencias = extrair_evidencias_campo(linha)
        campos = {e["campo"] for e in evidencias}
        if sinais.empresa_relevante:
            self.assertIn("titular", campos)


if __name__ == "__main__":
    unittest.main()

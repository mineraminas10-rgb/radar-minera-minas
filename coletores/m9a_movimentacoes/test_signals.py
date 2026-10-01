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


class TestClassificacaoPorDicionario(unittest.TestCase):
    """Achado/correção de 28/09/2026 — ver classificacao_scm.py. Classificar
    sempre a partir de descricao_tipo_evento (dicionário), nunca de
    evento_tipo (narrativa livre)."""

    def test_autorizacao_extracao_bate_com_nome_do_dicionario_sem_de(self):
        linha = {
            "processo": "830.649/2020",
            "descricao_tipo_evento": "AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL",
            "id_tipo_evento": 2325,
            "evento_tipo": "texto narrativo qualquer, não deveria importar pra classificação",
            "substancia": "MINÉRIO DE FERRO", "titular": "AGUAS FERREAS MINERACAO LTDA",
            "municipio": "Rio Casca", "data_evento": "2026-07-22",
        }
        sinais = extrair_signais_m9a(linha)
        self.assertTrue(sinais.autorizacao_extracao)
        self.assertTrue(sinais.mineral_estrategico)

    def test_autorizacao_extracao_nao_dispara_para_mero_requerimento(self):
        # sufixo PROTOC (em trâmite) não deveria contar como autorização já
        # concedida — mesma guia, mas ainda não decidida
        linha = {
            "processo": "1/2020", "descricao_tipo_evento": "AUT PESQ/GUIA UTILIZAÇÃO REQUERIMENTO PROTOC",
            "id_tipo_evento": 283, "substancia": "ferro", "titular": "X", "municipio": "Y", "data_evento": "2020-01-01",
        }
        sinais = extrair_signais_m9a(linha)
        self.assertFalse(sinais.autorizacao_extracao)

    def test_evento_tipo_narrativo_nao_influencia_classificacao(self):
        # mesmo dicionário, narrativas diferentes (uma com "de", outra sem)
        # — o resultado de sinais tem que ser idêntico nos dois casos
        base = {
            "processo": "830.649/2020", "descricao_tipo_evento": "AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL",
            "id_tipo_evento": 2325, "substancia": "MINÉRIO DE FERRO", "titular": "X", "municipio": "Y",
            "data_evento": "2026-07-22",
        }
        linha_a = dict(base, evento_tipo="GUIA DE UTILIZAÇÃO GU - 405/2026")
        linha_b = dict(base, evento_tipo="texto completamente diferente, sem menção a guia nenhuma")
        self.assertEqual(extrair_signais_m9a(linha_a), extrair_signais_m9a(linha_b))


class TestAreaHaLigadaAoPipeline(unittest.TestCase):
    """Achado/correção de 28/09/2026: area_ha (Processo.txt.QTAreaHA) agora
    chega em `linha` e alimenta dimensao_objetiva de verdade."""

    def test_dimensao_objetiva_dispara_com_area_preenchida(self):
        linha = {"processo": "1/2020", "descricao_tipo_evento": "x", "substancia": "ferro",
                  "titular": "X", "municipio": "Y", "data_evento": "2020-01-01", "area_ha": "1468.73"}
        self.assertTrue(extrair_signais_m9a(linha).dimensao_objetiva)

    def test_dimensao_objetiva_nao_dispara_sem_area(self):
        linha = {"processo": "1/2020", "descricao_tipo_evento": "x", "substancia": "ferro",
                  "titular": "X", "municipio": "Y", "data_evento": "2020-01-01"}
        self.assertFalse(extrair_signais_m9a(linha).dimensao_objetiva)

    def test_area_ha_vira_evidencia_gravavel(self):
        linha = {"processo": "1/2020", "evento_tipo": "x", "titular": "X", "substancia": "ferro",
                  "municipio": "Y", "data_evento": "2020-01-01", "area_ha": "1468.73"}
        evidencias = extrair_evidencias_campo(linha)
        campos = {e["campo"]: e["trecho_literal"] for e in evidencias}
        self.assertEqual(campos.get("area_ha"), "1468.73")


if __name__ == "__main__":
    unittest.main()

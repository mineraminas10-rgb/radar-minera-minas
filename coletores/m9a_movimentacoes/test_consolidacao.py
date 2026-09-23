"""
Testes de consolidacao.py contra os cenários dos 5 casos de controle da
Carta M9A (§11) e dos testes de aceitação M9A-A05/A06 (§14) — só a parte
de CHAVES/AGRUPAMENTO, que não depende de rede (dados sintéticos aqui,
não a amostra real do SCM).
"""
import unittest
from consolidacao import Ato, chave_caso_editorial, consolidar_atos, normalizar_descricao, houve_alteracao_material


class TestConsolidacao(unittest.TestCase):

    def test_kinross_dois_processos_mesma_cessao_consolidam_em_um_caso(self):
        # M9A-A05: "Agrupa os dois processos Kinross em um caso e preserva
        # ambos na evidência."
        ato1 = Ato(processo="830.161/2025", descricao="Cessão total de direito de pesquisa de ouro",
                   data_evento="2025-09-10", empresa="Kinross", substancia="ouro", municipio="Vazante")
        ato2 = Ato(processo="830.533/2025", descricao="Cessão total de direito de pesquisa de ouro",
                   data_evento="2025-09-10", empresa="Kinross", substancia="ouro", municipio="Vazante")
        casos = consolidar_atos([ato1, ato2])
        self.assertEqual(len(casos), 1, "os dois processos deveriam cair no mesmo caso editorial")
        atos_do_caso = list(casos.values())[0]
        self.assertEqual(len(atos_do_caso), 2, "os dois atos/processos precisam estar preservados na evidência")
        processos_preservados = {a.processo for a in atos_do_caso}
        self.assertEqual(processos_preservados, {"830.161/2025", "830.533/2025"})

    def test_itaminas_penhora_republicacoes_nao_duplicam_noticia(self):
        # M9A-A06: "Agrupa as publicações da penhora da Itaminas sem criar
        # notícia duplicada."
        # mesma data do ATO (a republicação não muda quando o fato
        # aconteceu, só quando foi visto de novo — "data de carregamento"
        # na linguagem da carta, que não faz parte da chave de identidade)
        ato1 = Ato(processo="005.962/1956", descricao="Averbação de penhora de direito minerário",
                   data_evento="2026-06-01", empresa="Itaminas", substancia="ferro", municipio="Sarzedo")
        ato2 = Ato(processo="005.962/1956", descricao="Republicação de averbação de penhora de direito minerário",
                   data_evento="2026-06-01", empresa="Itaminas", substancia="ferro", municipio="Sarzedo")
        casos = consolidar_atos([ato1, ato2])
        self.assertEqual(len(casos), 1)

    def test_processos_de_empresas_diferentes_nao_consolidam(self):
        ato1 = Ato(processo="830.161/2025", descricao="Cessão total", data_evento="2025-09-10",
                   empresa="Kinross", substancia="ouro", municipio="Vazante")
        ato2 = Ato(processo="000.334/1973", descricao="Procedimento de decaimento", data_evento="1973-01-01",
                   empresa="AngloGold", substancia="ouro e prata", municipio="Itabirito")
        casos = consolidar_atos([ato1, ato2])
        self.assertEqual(len(casos), 2, "processos de empresas/datas/municípios diferentes não deveriam consolidar")

    def test_familia_decaimento_e_intimacao_do_mesmo_processo_consolidam(self):
        ato1 = Ato(processo="000.334/1973", descricao="Instauração de decaimento", data_evento="1973-05-01",
                   empresa="AngloGold", substancia="ouro", municipio="Itabirito")
        ato2 = Ato(processo="000.334/1973", descricao="Intimação para defesa", data_evento="1973-06-01",
                   empresa="AngloGold", substancia="ouro", municipio="Itabirito")
        casos = consolidar_atos([ato1, ato2])
        self.assertEqual(len(casos), 1)
        self.assertEqual(len(list(casos.values())[0]), 2)

    def test_alteracao_material_dispara_nova_versao(self):
        anterior = {"titular": "Empresa A", "situacao": "ativo", "area": "100"}
        novo_igual = {"titular": "Empresa A", "situacao": "ativo", "area": "100"}
        novo_diferente = {"titular": "Empresa A", "situacao": "cancelado", "area": "100"}
        self.assertFalse(houve_alteracao_material(anterior, novo_igual))
        self.assertTrue(houve_alteracao_material(anterior, novo_diferente))

    def test_normalizar_descricao_ignora_acento_e_case(self):
        self.assertEqual(normalizar_descricao("Cessão Total"), normalizar_descricao("cessao total"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

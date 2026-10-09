"""
Testes de consolidacao.py contra os cenários dos 5 casos de controle da
Carta M9A (§11) e dos testes de aceitação M9A-A05/A06 (§14) — só a parte
de CHAVES/AGRUPAMENTO, que não depende de rede (dados sintéticos aqui,
não a amostra real do SCM).
"""
import unittest
from consolidacao import (
    Ato, chave_caso_editorial, consolidar_atos, normalizar_descricao, houve_alteracao_material,
    extrair_identificador_instrumento, buscar_processos_por_titular_no_universo,
)


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

    # ------------------------------------------------------------------
    # Regra 4b (28/09/2026) — sequência processual do mesmo instrumento.
    # Textos abaixo são os reais recuperados do SCM Microdados para o
    # processo 830.649/2020 (ver ETAPA3_ADENDO_FONTE_PRIMARIA), usados
    # aqui só como amostra de teste — a regra em si (extrair_identificador_
    # instrumento/chave_caso_editorial) não tem nada hardcoded pra este
    # processo, é regex sobre o padrão "Nº NNN/AAAA" genérico da ANM.
    # ------------------------------------------------------------------
    def test_extrai_numero_instrumento_de_narrativa_com_marcador_n(self):
        self.assertEqual(
            extrair_identificador_instrumento(
                "Autoriza a emissão de Guia de Utilização 830.649/2020-AGUAS FERREAS MINERACAO LTDA-"
                "RIO CASCA/MG, SÃO PEDRO DOS FERROS/MG - Guia n° 61/2023 - GERÊNCIA REGIONAL/MG-"
                "300.000 toneladas/ano-MINÉRIO DE FERRO"
            ),
            "61/2023",
        )
        self.assertEqual(
            extrair_identificador_instrumento(
                "Prorroga por 03 (três) anos o prazo de validade da guia de utilização. "
                "830.649/2020-AGUAS FERREAS MINERACAO LTDA-GUIA DE UTILIZAÇÃO N°61/2023 - GERÊNCIA REGIONAL/MG"
            ),
            "61/2023",
        )

    def test_nao_confunde_numero_do_proprio_documento_sem_marcador_n(self):
        # "GU - 405/2026" é o número do PRÓPRIO despacho de prorrogação,
        # não do instrumento sendo prorrogado — não deve ser extraído
        # quando aparece sozinho, sem o marcador "Nº" explícito.
        self.assertIsNone(extrair_identificador_instrumento(
            "Relação SEÇÃO 1 - GUIA DE UTILIZAÇÃO  GU - 405/2026 - Gerência Regional / MG"
        ))

    def test_emissao_e_prorrogacao_da_mesma_guia_consolidam_apesar_de_datas_diferentes(self):
        ato_emissao = Ato(
            processo="830.649/2020",
            descricao="AUT PESQ/GUIA UTILIZAÇÃO AUTORIZADA PUBL",
            data_evento="2023-02-14", empresa="AGUAS FERREAS MINERACAO LTDA",
            substancia="MINÉRIO DE FERRO", municipio="Rio Casca; São Pedro dos Ferros",
            id_tipo_evento=285,
            texto_narrativo="Autoriza a emissão de Guia de Utilização 830.649/2020-AGUAS FERREAS MINERACAO "
                             "LTDA-RIO CASCA/MG, SÃO PEDRO DOS FERROS/MG - Guia n° 61/2023 - GERÊNCIA "
                             "REGIONAL/MG-300.000 toneladas/ano-MINÉRIO DE FERRO (uso: Industrial)- "
                             "Vigência da Guia:3 ANOS",
        )
        ato_prorrogacao = Ato(
            processo="830.649/2020",
            descricao="AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL",
            data_evento="2026-07-22", empresa="AGUAS FERREAS MINERACAO LTDA",
            substancia="MINÉRIO DE FERRO", municipio="Rio Casca; São Pedro dos Ferros",
            id_tipo_evento=2325,
            texto_narrativo="Prorroga por 03 (três) anos o prazo de validade da guia de utilização. "
                             "830.649/2020-AGUAS FERREAS MINERACAO LTDA-GUIA DE UTILIZAÇÃO N°61/2023 - "
                             "GERÊNCIA REGIONAL/MG",
        )
        casos = consolidar_atos([ato_emissao, ato_prorrogacao])
        self.assertEqual(len(casos), 1, "emissão e prorrogação da mesma guia deveriam cair no mesmo caso")
        atos_do_caso = list(casos.values())[0]
        self.assertEqual(len(atos_do_caso), 2, "os dois atos precisam continuar distintos (não fundidos)")
        datas = {a.data_evento for a in atos_do_caso}
        self.assertEqual(datas, {"2023-02-14", "2026-07-22"})

    def test_instrumentos_diferentes_nao_consolidam(self):
        ato_guia_61 = Ato(processo="1/2020", descricao="x", data_evento="2020-01-01", empresa="A",
                           texto_narrativo="Guia n° 61/2023")
        ato_guia_99 = Ato(processo="1/2020", descricao="x", data_evento="2021-01-01", empresa="A",
                           texto_narrativo="Guia n° 99/2019")
        casos = consolidar_atos([ato_guia_61, ato_guia_99])
        self.assertEqual(len(casos), 2)

    def test_busca_antecedentes_no_universo_encontra_outros_processos_do_titular(self):
        universo = [
            Ato(processo="1/2020", descricao="x", data_evento="2020-01-01", empresa="Empresa X"),
            Ato(processo="2/2021", descricao="y", data_evento="2021-01-01", empresa="Empresa X"),
            Ato(processo="3/2022", descricao="z", data_evento="2022-01-01", empresa="Empresa Y"),
        ]
        antecedentes = buscar_processos_por_titular_no_universo(universo, titular="Empresa X", processo_atual="1/2020")
        self.assertEqual(antecedentes, ["2/2021"])

    def test_busca_antecedentes_sem_titular_retorna_vazio(self):
        self.assertEqual(buscar_processos_por_titular_no_universo([], titular=None, processo_atual="1/2020"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

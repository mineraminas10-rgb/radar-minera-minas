import unittest

from checklist_editorial import (
    derivar_checklist_m9a,
    RESPOSTA_CONFIRMADO,
    RESPOSTA_NAO_LOCALIZADO,
    RESPOSTA_REQUER_APURACAO,
)


class TestChecklistEditorialM9A(unittest.TestCase):

    def test_caso_completo_confirmado_maioria(self):
        respostas = derivar_checklist_m9a(
            titular="Kinross Brasil Mineração S.A.", municipio="Paracatu",
            data_evento="2025-08-01", descricao="Cessão de direitos minerários",
            efeito_operacional="comprovado", quantidade_processos_no_caso=2,
            teve_antecedentes=True,
        )
        self.assertEqual(len(respostas), 12)
        self.assertEqual(respostas[1], RESPOSTA_CONFIRMADO)
        self.assertEqual(respostas[2], RESPOSTA_CONFIRMADO)
        self.assertEqual(respostas[3], RESPOSTA_CONFIRMADO)
        self.assertEqual(respostas[4], RESPOSTA_CONFIRMADO)
        self.assertEqual(respostas[5], RESPOSTA_REQUER_APURACAO)  # SIGMINE não ingerido ainda
        self.assertEqual(respostas[6], RESPOSTA_CONFIRMADO)
        self.assertEqual(respostas[7], RESPOSTA_CONFIRMADO)  # efeito comprovado
        self.assertEqual(respostas[8], RESPOSTA_CONFIRMADO)  # ato É uma decisão da ANM
        self.assertEqual(respostas[9], RESPOSTA_REQUER_APURACAO)  # SEI/recurso — §8 pendente
        self.assertEqual(respostas[10], RESPOSTA_REQUER_APURACAO)
        self.assertEqual(respostas[11], RESPOSTA_CONFIRMADO)  # múltiplos processos no caso
        self.assertEqual(respostas[12], RESPOSTA_REQUER_APURACAO)

    def test_campos_ausentes_viram_nao_localizado(self):
        respostas = derivar_checklist_m9a(
            titular=None, municipio=None, data_evento=None, descricao=None,
            efeito_operacional=None, quantidade_processos_no_caso=1, teve_antecedentes=False,
        )
        self.assertEqual(respostas[2], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[3], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[4], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[6], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[8], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[11], RESPOSTA_NAO_LOCALIZADO)

    def test_efeito_nao_comprovado_vira_nao_localizado_na_pergunta_7(self):
        respostas = derivar_checklist_m9a(
            titular="Empresa X", municipio="Itabira", data_evento="2026-01-01",
            descricao="Decisão de decaimento", efeito_operacional="nao_comprovado",
        )
        self.assertEqual(respostas[7], RESPOSTA_NAO_LOCALIZADO)

    def test_efeito_provavel_fica_pendente_de_apuracao(self):
        respostas = derivar_checklist_m9a(
            titular="Empresa X", descricao="Decisão de decaimento", efeito_operacional="provavel",
        )
        self.assertEqual(respostas[7], RESPOSTA_REQUER_APURACAO)

    def test_um_unico_processo_sem_antecedente_nao_localizado_no_historico(self):
        respostas = derivar_checklist_m9a(
            titular="Empresa X", quantidade_processos_no_caso=1, teve_antecedentes=False,
        )
        self.assertEqual(respostas[11], RESPOSTA_NAO_LOCALIZADO)


if __name__ == "__main__":
    unittest.main()

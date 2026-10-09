import unittest

from checklist_editorial import (
    derivar_checklist_m8,
    RESPOSTA_CONFIRMADO,
    RESPOSTA_NAO_LOCALIZADO,
    RESPOSTA_NAO_APLICAVEL,
    RESPOSTA_REQUER_APURACAO,
)


class TestChecklistEditorialM8(unittest.TestCase):

    def test_extracao_falhou_tudo_requer_apuracao(self):
        respostas = derivar_checklist_m8(extracao_falhou=True, faixa_vinculo="contextual")
        self.assertEqual(len(respostas), 12)
        self.assertTrue(all(r == RESPOSTA_REQUER_APURACAO for r in respostas.values()))

    def test_caso_completo_confirmado_maioria_confirmado(self):
        respostas = derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo="confirmado",
            empresa_citada="Mineradora X", local_descrito="Rodovia MG-030, km 12",
            municipio="Nova Lima", data_hora_ocorrencia="2026-05-01T10:00:00",
            volume_quantidade=500.0, descricao_literal="tombamento de carreta com minério de ferro",
            modalidade="tombamento", score_gravidade_calculado=True, teve_antecedentes=True,
        )
        self.assertEqual(respostas[1], RESPOSTA_CONFIRMADO)   # o que aconteceu
        self.assertEqual(respostas[2], RESPOSTA_CONFIRMADO)   # quem
        self.assertEqual(respostas[3], RESPOSTA_CONFIRMADO)   # onde
        self.assertEqual(respostas[4], RESPOSTA_CONFIRMADO)   # quando
        self.assertEqual(respostas[5], RESPOSTA_CONFIRMADO)   # dimensão
        self.assertEqual(respostas[6], RESPOSTA_CONFIRMADO)   # conduta
        self.assertEqual(respostas[7], RESPOSTA_CONFIRMADO)   # consequência (gravidade calculada)
        self.assertEqual(respostas[8], RESPOSTA_NAO_APLICAVEL)  # M8 não tem decisão/autorização
        self.assertEqual(respostas[9], RESPOSTA_NAO_APLICAVEL)  # nem situação processual
        self.assertEqual(respostas[10], RESPOSTA_REQUER_APURACAO)  # próximo marco sempre humano
        self.assertEqual(respostas[11], RESPOSTA_CONFIRMADO)  # teve antecedentes
        self.assertEqual(respostas[12], RESPOSTA_REQUER_APURACAO)  # contraditório não implementado

    def test_campos_ausentes_viram_nao_localizado(self):
        respostas = derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo="provavel",
            empresa_citada=None, local_descrito=None, municipio=None,
            data_hora_ocorrencia=None, volume_quantidade=None,
            descricao_literal=None, modalidade=None,
            score_gravidade_calculado=True, teve_antecedentes=False,
        )
        self.assertEqual(respostas[2], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[3], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[4], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[5], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[6], RESPOSTA_NAO_LOCALIZADO)
        self.assertEqual(respostas[11], RESPOSTA_NAO_LOCALIZADO)

    def test_faixa_descartada_consequencia_nao_aplicavel(self):
        respostas = derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo="descartado",
            empresa_citada=None, local_descrito="São João del-Rei", municipio="São João del-Rei",
            descricao_literal="derramamento de tinta industrial",
            score_gravidade_calculado=False,
        )
        # caso descartado por não ser minerário: consequência ambiental do
        # M8 não se aplica (o módulo só mede gravidade de acidente minerário)
        self.assertEqual(respostas[7], RESPOSTA_NAO_APLICAVEL)

    def test_faixa_provavel_sem_gravidade_calculada_fica_pendente(self):
        # não deveria acontecer na prática (main.py sempre calcula gravidade
        # pra faixas provavel/confirmado), mas a função não deve fingir que
        # sabe a consequência se ninguém passou score_gravidade_calculado=True
        respostas = derivar_checklist_m8(
            extracao_falhou=False, faixa_vinculo="provavel",
            descricao_literal="algo", score_gravidade_calculado=False,
        )
        self.assertEqual(respostas[7], RESPOSTA_REQUER_APURACAO)


if __name__ == "__main__":
    unittest.main()

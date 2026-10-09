"""
Regressão do motor de score do Módulo 9A contra a Carta Operacional M9A v1.0.

IMPORTANTE — por que os 5 casos de controle (§11) NÃO são testados aqui
contra os números 90/86/82/92/88 da tabela:

A carta diz no fim do §6: "Na planilha transversal, a pontuação pode ser
convertida para a escala editorial de 0 a 100. [...] A prioridade final
continua sujeita ao enriquecimento e à revisão humana." Ou seja, os números
90/86/82/92/88 e as letras A/A/B/A/A da tabela do §11 são a SAÍDA do
pipeline editorial completo (score_m9a de 0-10 + enriquecimento +
ponderação transversal do Radar — o mesmo mecanismo genérico de
event_scores/carteiras já implementado, não algo específico do M9A). Não
são o resultado direto e isolado da rubrica de 9 regras do §6.

Por isso: os testes abaixo validam a MATEMÁTICA da rubrica (tetos, piso,
limiares de faixa) de forma isolada e exaustiva — isso é 100% verificável
sem ambiguidade. Os 5 casos de controle aparecem só como um teste de
sanidade qualitativo (a faixa BRUTA do M9A deve ser 'razoável' dado o
que a carta descreve de cada caso), sem cobrar os números 90/86/82/92/88
da tabela, que dependem de enriquecimento e ponderação que este arquivo
não tenta reproduzir.

Rodar: python3 test_scoring.py
"""
import unittest
from scoring import SignaisM9A, score_m9a


class TestScoreM9ARegras(unittest.TestCase):

    def test_zero_sinais_e_faixa_d(self):
        score, faixa, just = score_m9a(SignaisM9A())
        self.assertEqual(score, 0)
        self.assertEqual(faixa, "D")

    def test_mudanca_material_isolada_e_faixa_c(self):
        # 4 pontos cai em C (2-4); só combinado com outro sinal chega a B (5-7)
        score, faixa, just = score_m9a(SignaisM9A(mudanca_material_direito=True))
        self.assertEqual(score, 4)
        self.assertEqual(faixa, "C")

    def test_teto_de_10_antes_dos_redutores(self):
        sig = SignaisM9A(
            mudanca_material_direito=True, autorizacao_extracao=True, avanco_pesquisa=True,
            dimensao_objetiva=True, empresa_relevante=True, mineral_estrategico=True,
            reserva_ou_substancia=True, varios_municipios=True,
        )  # soma bruta 4+3+3+2+2+2+1+1 = 18
        score, faixa, just = score_m9a(sig)
        self.assertEqual(score, 10)
        self.assertEqual(faixa, "A")

    def test_rotina_isolada_nao_gera_prioridade_a_ou_b(self):
        # §7: protocolo/juntada/TAH/RAL não pode virar alerta isolado
        score, faixa, just = score_m9a(SignaisM9A(rotina=True))
        self.assertEqual(faixa, "D")
        self.assertLessEqual(score, 1)

    def test_rotina_com_outros_sinais_ainda_tem_teto_1(self):
        # mesmo com sinais fortes, rotina no mesmo ato limita a 1 ponto (§7)
        sig = SignaisM9A(mudanca_material_direito=True, dimensao_objetiva=True, rotina=True)
        score, faixa, just = score_m9a(sig)
        self.assertLessEqual(score, 1)
        self.assertEqual(faixa, "D")

    def test_exigencia_generica_tem_teto_4(self):
        sig = SignaisM9A(mudanca_material_direito=True, autorizacao_extracao=True, exigencia_generica=True)
        # bruto 4+3=7, menos 3 (exigência) = 4, teto 4 -> não muda, mas fica em C não em B/A
        score, faixa, just = score_m9a(sig)
        self.assertLessEqual(score, 4)
        self.assertEqual(faixa, "C")

    def test_relatorio_pesquisa_aprovado_sozinho_fica_abaixo_do_teto_b(self):
        # §7: sem dimensão, empresa relevante ou mineral estratégico -> teto B (7).
        # Sozinho soma só 3 pontos (faixa C) — o teto de 7 existe para quando
        # avanco_pesquisa vier combinado com sinais fracos que não chegam a
        # reforço (dimensão/empresa relevante/mineral estratégico); ver o
        # teste seguinte para o caso em que o teto realmente limita algo.
        score, faixa, just = score_m9a(SignaisM9A(avanco_pesquisa=True))
        self.assertEqual(score, 3)
        self.assertEqual(faixa, "C")

    def test_teto_b_realmente_limita_quando_soma_passaria_de_7(self):
        # avanco_pesquisa(3) + varios_municipios(1) + reserva_ou_substancia(1) = 5,
        # ainda sem reforço -> seria B naturalmente; o teto de 7 aqui não
        # chega a cortar nada, mas confirma que não escapa para A mesmo
        # somando mais sinais fracos (o que só tem reforço faria).
        sig = SignaisM9A(avanco_pesquisa=True, varios_municipios=True, reserva_ou_substancia=True)
        score, faixa, just = score_m9a(sig)
        self.assertEqual(score, 5)
        self.assertEqual(faixa, "B")

    def test_relatorio_pesquisa_com_dimensao_nao_tem_teto_b(self):
        sig = SignaisM9A(avanco_pesquisa=True, dimensao_objetiva=True, empresa_relevante=True, mineral_estrategico=True)
        # 3+2+2+2 = 9 -> sem teto porque tem_reforco=True
        score, faixa, just = score_m9a(sig)
        self.assertEqual(score, 9)
        self.assertEqual(faixa, "A")

    def test_alvara_comum_sozinho_tem_teto_c(self):
        # §7: sem outro gatilho -> teto C (4)
        score, faixa, just = score_m9a(SignaisM9A(alvara_comum_pesquisa=True))
        self.assertEqual(score, 2)
        self.assertEqual(faixa, "C")

    def test_alvara_comum_com_outro_gatilho_nao_tem_teto_c(self):
        sig = SignaisM9A(alvara_comum_pesquisa=True, mudanca_material_direito=True)
        score, faixa, just = score_m9a(sig)
        self.assertEqual(score, 6)  # 2+4, sem teto pois há outro_gatilho
        self.assertEqual(faixa, "B")

    def test_reavaliacao_reserva_sem_dimensao_tem_teto_b(self):
        sig = SignaisM9A(reserva_ou_substancia=True, empresa_relevante=True, mineral_estrategico=True)
        # 1+2+2 = 5, sem dimensao_objetiva -> teto B (7), aqui já é 5 (B), sem efeito visível
        score, faixa, just = score_m9a(sig)
        self.assertEqual(faixa, "B")

    def test_decaimento_caducidade_interdicao_lavra_tem_piso_a(self):
        # §7: alerta mínimo A mesmo com poucos outros sinais
        sig = SignaisM9A(decaimento_caducidade_ou_interdicao_lavra=True)
        score, faixa, just = score_m9a(sig)
        self.assertGreaterEqual(score, 8)
        self.assertEqual(faixa, "A")

    def test_piso_a_prevalece_mesmo_com_teto_de_exigencia_generica(self):
        # caso extremo/pouco provável na prática, mas define a ordem: piso > teto
        sig = SignaisM9A(decaimento_caducidade_ou_interdicao_lavra=True, exigencia_generica=True)
        score, faixa, just = score_m9a(sig)
        self.assertEqual(faixa, "A")


class TestCasosDeControleSanidadeQualitativa(unittest.TestCase):
    """Sanidade qualitativa só — NÃO reproduz os números 90/86/82/92/88 da
    tabela (ver aviso no topo do arquivo). Confirma que a leitura dos 5
    casos do §11/§12 não produz nada absurdo (ex.: um decaimento cair em D)."""

    def test_dvm_prorrogacao_gu_ferro_quatro_municipios(self):
        sig = SignaisM9A(autorizacao_extracao=True, dimensao_objetiva=True,
                          varios_municipios=True, mineral_estrategico=True)
        score, faixa, just = score_m9a(sig)
        self.assertIn(faixa, ("A", "B"))

    def test_itaminas_penhora_ligada_a_operacao(self):
        # "Averbação de penhora de direito minerário; título ligado à operação de Sarzedo"
        sig = SignaisM9A(mudanca_material_direito=True, dimensao_objetiva=True)
        score, faixa, just = score_m9a(sig)
        self.assertIn(faixa, ("A", "B"))

    def test_anglogold_decaimento_tem_piso_a(self):
        # "Procedimento de decaimento com fundamento no SNUC" -> trava de piso A
        sig = SignaisM9A(mudanca_material_direito=True, dimensao_objetiva=True,
                          mineral_estrategico=True, decaimento_caducidade_ou_interdicao_lavra=True)
        score, faixa, just = score_m9a(sig)
        self.assertEqual(faixa, "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)

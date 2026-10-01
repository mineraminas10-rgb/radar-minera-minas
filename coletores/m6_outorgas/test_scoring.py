"""
Regressão do motor de score do Módulo 6 contra a Função de score M6 v1
(Carta Operacional M6 v0.8 §43.3/43.4/43.5) e contra o caso ouro Rima
Industrial da Carta de Homologação M6-V1.0 §4.2 (a única vez em que a
carta publica a decomposição completa dos 8 componentes — por isso é o
único caso testado ponto a ponto; os outros 7 casos congelados (carta de
homologação §7) só têm score final e prioridade divulgados, sem a
decomposição, e são travados como constantes em test_regressao_m6.py,
não recalculados aqui).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scoring import (  # noqa: E402
    ComponenteScore, TravasM6, calcular_score_m6, classificar_faixa, MAXIMOS,
)


class TestFaixas(unittest.TestCase):
    def test_faixa_a(self):
        self.assertEqual(classificar_faixa(80), "A")
        self.assertEqual(classificar_faixa(100), "A")

    def test_faixa_b(self):
        self.assertEqual(classificar_faixa(60), "B")
        self.assertEqual(classificar_faixa(79), "B")

    def test_faixa_c(self):
        self.assertEqual(classificar_faixa(35), "C")
        self.assertEqual(classificar_faixa(59), "C")

    def test_faixa_d(self):
        self.assertEqual(classificar_faixa(0), "D")
        self.assertEqual(classificar_faixa(34), "D")

    def test_fora_de_escopo_nunca_entra_em_a_b_c_d_mesmo_com_pontos_altos(self):
        self.assertEqual(classificar_faixa(95, fora_de_escopo=True), "Fora")


def _componentes_vazios(**overrides):
    base = {nome: ComponenteScore(pontos=0, justificativa="") for nome in MAXIMOS}
    base.update(overrides)
    return base


class TestCasoOuroRimaIndustrial(unittest.TestCase):
    """Carta de Homologação M6-V1.0 §4.2 — decomposição exata divulgada:
    8/20, 3/20, 6/15, 12/15, 9/10, 10/10, 4/5, 5/5 = 57, Prioridade C."""

    def test_soma_exata_57_prioridade_c(self):
        componentes = {
            "consequencia_operacional_regulatoria": ComponenteScore(8, "indeferimento mantido para um poço; efeito sobre a operação não comprovado"),
            "dimensao_hidrica_fisica": ComponenteScore(3, "sem vazão, horas, volume ou participação do poço na demanda da unidade"),
            "risco_conflito_interesse_publico": ComponenteScore(6, "descumprimento de condicionante comprovado; dano, escassez e conflito não demonstrados"),
            "materialidade_evento": ComponenteScore(12, "manutenção formal de indeferimento após percurso recursal ou revisional"),
            "novidade_sinal_temporal": ComponenteScore(9, "ato novo de setembro de 2026 e intervalo excepcionalmente longo"),
            "cruzamentos_historico": ComponenteScore(10, "portaria de 2010, requerimento de 2015, seis indeferimentos em 2022 e ato de 2026"),
            "relevancia_empresa_projeto": ComponenteScore(4, "operação industrial de grande porte ligada à cadeia mineral e metalúrgica"),
            "potencial_exclusividade": ComponenteScore(5, "ângulo depende da ligação entre documentos pouco visíveis e separados no tempo"),
        }
        score, faixa, memoria = calcular_score_m6(componentes, fora_de_escopo=False)
        self.assertEqual(score, 57)
        self.assertEqual(faixa, "C")
        self.assertEqual(memoria["score_final"], 57)


class TestLimitesEValidacao(unittest.TestCase):
    def test_componente_faltando_levanta_erro(self):
        componentes = _componentes_vazios()
        del componentes["potencial_exclusividade"]
        with self.assertRaises(ValueError):
            calcular_score_m6(componentes)

    def test_componente_acima_do_maximo_levanta_erro(self):
        componentes = _componentes_vazios(
            consequencia_operacional_regulatoria=ComponenteScore(21, "acima do máximo de 20")
        )
        with self.assertRaises(ValueError):
            calcular_score_m6(componentes)

    def test_componente_negativo_levanta_erro(self):
        componentes = _componentes_vazios(
            consequencia_operacional_regulatoria=ComponenteScore(-1, "")
        )
        with self.assertRaises(ValueError):
            calcular_score_m6(componentes)


class TestTravas(unittest.TestCase):
    def test_trava_de_a_limita_a_79(self):
        componentes = {nome: ComponenteScore(MAXIMOS[nome], "max") for nome in MAXIMOS}  # soma = 100
        travas = TravasM6(parecer_sem_decisao_ou_recurso_pendente=True)
        score, faixa, memoria = calcular_score_m6(componentes, travas=travas)
        self.assertEqual(score, 79)
        self.assertEqual(faixa, "B")
        self.assertIn("trava de A", " ".join(memoria["travas_aplicadas"]))

    def test_trava_de_b_limita_a_59(self):
        componentes = {nome: ComponenteScore(MAXIMOS[nome], "max") for nome in MAXIMOS}
        travas = TravasM6(vinculo_apenas_presumido=True)
        score, faixa, memoria = calcular_score_m6(componentes, travas=travas)
        self.assertEqual(score, 59)
        self.assertEqual(faixa, "C")

    def test_redutor_so_reduz_nunca_aumenta(self):
        componentes = _componentes_vazios(
            materialidade_evento=ComponenteScore(10, "registro antigo")
        )
        travas = TravasM6(redutor_pontos=15, motivo_redutor="registro antigo sem fato novo")
        score, faixa, memoria = calcular_score_m6(componentes, travas=travas)
        self.assertEqual(score, 0)  # 10 - 15 clampado em 0, nunca negativo
        self.assertEqual(faixa, "D")

    def test_score_nunca_excede_100(self):
        componentes = {nome: ComponenteScore(MAXIMOS[nome], "max") for nome in MAXIMOS}
        score, faixa, memoria = calcular_score_m6(componentes)
        self.assertEqual(score, 100)
        self.assertEqual(faixa, "A")


if __name__ == "__main__":
    unittest.main()

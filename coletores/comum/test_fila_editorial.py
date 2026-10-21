import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fila_editorial


class FilaEditorialTests(unittest.TestCase):
    def test_m8_usa_vinculo_e_banda_da_carteira_sem_piso_bruto_adicional(self):
        self.assertEqual(fila_editorial.elegibilidade_m8("provavel", "B")[0], True)
        self.assertEqual(fila_editorial.elegibilidade_m8("confirmado", "A")[0], True)
        self.assertEqual(fila_editorial.elegibilidade_m8("contextual", "A")[0], False)
        self.assertEqual(fila_editorial.elegibilidade_m8("confirmado", "C")[0], False)

    def test_m9a_usa_prioridade_sem_comparar_escalas_de_score(self):
        # Score bruto do M9A é 0–10; a elegibilidade deve usar a prioridade
        # final da régua editorial, sem um corte inventado de 50 pontos.
        for prioridade in ("A", "B"):
            self.assertTrue(fila_editorial.elegibilidade_m9a(prioridade)[0])
        for prioridade in ("C", "D", None, ""):
            self.assertFalse(fila_editorial.elegibilidade_m9a(prioridade)[0])


if __name__ == "__main__":
    unittest.main()

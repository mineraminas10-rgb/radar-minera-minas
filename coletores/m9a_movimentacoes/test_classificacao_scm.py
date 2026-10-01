import unittest

from classificacao_scm import normalizar_termo, contem_termo, sufixo_situacao, classificar


class TestNormalizarTermo(unittest.TestCase):

    def test_remove_preposicao_de(self):
        # achado de 28/09/2026: "GUIA UTILIZAÇÃO" (dicionário Evento.txt,
        # IDEvento=285/2325 reais) e "GUIA DE UTILIZAÇÃO" (narrativa livre
        # do mesmo caso) precisam normalizar pro mesmo texto.
        self.assertEqual(normalizar_termo("GUIA UTILIZAÇÃO"), normalizar_termo("GUIA DE UTILIZAÇÃO"))
        self.assertEqual(normalizar_termo("GUIA UTILIZAÇÃO"), "guia utilizacao")

    def test_remove_acento_e_case(self):
        self.assertEqual(normalizar_termo("Autorização"), normalizar_termo("AUTORIZACAO"))

    def test_vazio(self):
        self.assertEqual(normalizar_termo(None), "")
        self.assertEqual(normalizar_termo(""), "")


class TestContemTermo(unittest.TestCase):

    def test_bate_com_ou_sem_preposicao_no_termo_de_referencia(self):
        texto_norm = normalizar_termo("AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL")
        # a lista de referência do sistema pode escrever "guia de utilização"
        # (com "de") mesmo quando o texto real não tem — precisa bater igual
        self.assertTrue(contem_termo(texto_norm, "guia de utilizacao"))
        self.assertTrue(contem_termo(texto_norm, "guia utilizacao"))


class TestSufixoSituacao(unittest.TestCase):

    def test_publ_e_concluido(self):
        self.assertEqual(sufixo_situacao(normalizar_termo("AUT PESQ/GUIA UTILIZAÇÃO AUTORIZADA PUBL")), "concluido")

    def test_protoc_e_em_tramite(self):
        self.assertEqual(sufixo_situacao(normalizar_termo("AUT PESQ/GUIA UTILIZAÇÃO REQUERIMENTO PROTOC")), "em_tramite")

    def test_indeferida_e_negativo(self):
        self.assertEqual(sufixo_situacao(normalizar_termo("AUT PESQ/GUIA UTILIZAÇÃO INDEFERIDA PUBL")), "negativo")


class TestClassificar(unittest.TestCase):

    def test_dois_textos_do_mesmo_ato_classificam_igual(self):
        # o achado central: o mesmo IDEvento=2325 tem nome de dicionário
        # ("sem de") e narrativa OBEvento ("com de") diferentes — ambos
        # precisam produzir a mesma leitura de 'contem' depois de
        # normalizados, para o pipeline não depender de qual texto chegou.
        dicionario = classificar(2325, "AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL")
        narrativa_como_se_fosse_dicionario = classificar(2325, "GUIA DE UTILIZAÇÃO GU - 405/2026")
        self.assertTrue(dicionario.contem("guia de utilizacao"))
        self.assertTrue(narrativa_como_se_fosse_dicionario.contem("guia de utilizacao"))

    def test_override_vazio_por_desenho(self):
        # não deve existir nenhuma regra específica pro IDEvento=2325 (nem
        # pra nenhum outro) — ver docstring do módulo.
        from classificacao_scm import _OVERRIDE_POR_ID_EVENTO
        self.assertEqual(_OVERRIDE_POR_ID_EVENTO, {})


if __name__ == "__main__":
    unittest.main()

"""Campos estruturados do comunicado (cabeçalhos REAIS lidos em produção em 15/10/2026; texto da SEMAD/NEA)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import campos_comunicado as cc

C179 = """COMUNICADO DE ACIDENTE AMBIENTAL
N° Protocolo: 179/2026
MODALIDADE DO ACIDENTE: Instalaçao industrial
LOCAL: Mina Turmalina - Fazenda Satinoco s/n, Rodovia MG-423, km 18
MUNICÍPIO: Conceição do Pará/MG
DATA/HORA DA OCORRÊNCIA: 29/08/2026 - 16:30:00
DATA/HORA DO COMUNICADO AO NEA: 30/08/2026 - 13:41:00
FONTE(S) DE INFORMAÇÕES: Flávia Toledo Ramos
BREVE DESCRIÇÃO DA OCORRÊNCIA: Conforme relatado ao NEA, houve um vazamento de rejeito
tratado, atingindo um canal de drenagem e com possibilidade de ter atingido um córrego.
PRODUTO: Rejeito mineral aurífero | NÚMERO ONU: --| CLASSE DE RISCO: --
Núcleo de Prevenção e Emergência Ambiental
Cidade Administrativa Presidente Tancredo Neves - Edifício Minas - 1º andar
"""

C182 = """COMUNICADO DE ACIDENTE AMBIENTAL
N° Protocolo: 182/2026
MODALIDADE DO ACIDENTE: Transporte Rodoviário
LOCAL: Rodovia BR 135, Km 625 (+200m - sentido sul)
MUNICÍPIO: Curvelo/MG
DATA/HORA DA OCORRÊNCIA: 01/09/2026 - 06:54:00
DATA/HORA DO COMUNICADO AO NEA: 01/09/2026 - 16:16:00
FONTE(S) DE INFORMAÇÕES: Concessionária da via
BREVE DESCRIÇÃO DA OCORRÊNCIA: Segundo informações repassadas ao NEA, ocorreu um
incidente quando a carreta do veículo veio a desatrelar do cavalo mecânico, com vazamento de óleo hidráulico,
adentrando para área de refúgio fora da pista e sobre o solo. A empresa ainda não se pronunciou sobre
a limpeza da área.
PRODUTO: Óleo hidráulico/isolante/resíduo oleoso | NÚMERO ONU: | CLASSE DE RISCO:
Núcleo de Prevenção e Emergência Ambiental
"""

C200 = """COMUNICADO DE ACIDENTE AMBIENTAL
N° Protocolo: 200/2026
MODALIDADE DO ACIDENTE: Transporte Rodoviário
LOCAL: Rodovia MGC 452, km 29
MUNICÍPIO: Monte Alegre de Minas/MG
DATA/HORA DA OCORRÊNCIA: 30/09/2026 - 14:00:00
DATA/HORA DO COMUNICADO AO NEA: 30/09/2026 - 15:50:00
FONTE(S) DE INFORMAÇÕES: Representante da transportadora
BREVE DESCRIÇÃO DA OCORRÊNCIA: Segundo informações repassadas ao NEA, no dia
30/09/2026, ocorreu tombamento de veículo sobre a ponte do Córrego
Lajeado, seguido da queda da carga. Produto nas margens e no leito do referido Córrego. Até o momento sem
informação a cerca de mortandade de peixes devido ao acidente.
PRODUTO: Composto Orgânico - torta de filtro | NÚMERO ONU: 3077 | CLASSE DE RISCO: 9
Núcleo de Prevenção e Emergência Ambiental
"""


class TestCamposComunicado(unittest.TestCase):
    def test_cabecalho_do_179(self):
        c = cc.extrair_campos(C179)
        self.assertTrue(c["cabecalho_reconhecido"])
        self.assertEqual(c["protocolo_lido"], "179/2026")
        self.assertEqual(c["modalidade"], "Instalaçao industrial")
        self.assertEqual(c["municipio"], "Conceição do Pará/MG")
        self.assertEqual(c["rodovia"], "MG-423")
        self.assertEqual(c["km"], "18")
        self.assertEqual(c["data_hora_ocorrencia"], "2026-08-29T16:30:00-03:00")
        self.assertEqual(c["data_hora_comunicacao"], "2026-08-30T13:41:00-03:00")
        self.assertEqual(c["atraso_comunicacao_minutos"], 21 * 60 + 11)
        self.assertEqual(c["produto"], "Rejeito mineral aurífero")
        self.assertIsNone(c["numero_onu"])      # "--" = não informado
        self.assertIsNone(c["classe_risco"])
        self.assertIn("vazamento de rejeito tratado", c["descricao_literal"])
        self.assertNotIn("PRODUTO", c["descricao_literal"])

    def test_onu_e_classe_vazios_nao_roubam_o_proximo_rotulo(self):
        c = cc.extrair_campos(C182)
        self.assertEqual(c["rodovia"], "BR-135")
        self.assertEqual(c["km"], "625")
        self.assertEqual(c["produto"], "Óleo hidráulico/isolante/resíduo oleoso")
        self.assertIsNone(c["numero_onu"])
        self.assertIsNone(c["classe_risco"])    # não pode virar "Núcleo..." nem "1º andar"

    def test_onu_e_classe_preenchidos(self):
        c = cc.extrair_campos(C200)
        self.assertEqual(c["numero_onu"], "3077")
        self.assertEqual(c["classe_risco"], "9")
        self.assertEqual(c["rodovia"], "MGC-452")

    def test_narrativa_so_vira_indicio_com_estado(self):
        c = cc.extrair_campos(C179)
        self.assertEqual(c["indicios_narrativos"]["curso_dagua"], "incerto")    # "possibilidade de ter atingido um córrego"
        c = cc.extrair_campos(C200)
        self.assertEqual(c["indicios_narrativos"]["curso_dagua"], "afirmado")
        c = cc.extrair_campos(C182)
        self.assertEqual(c["indicios_narrativos"]["solo"], "afirmado")

    def test_narrativa_nunca_preenche_colunas_booleanas_de_fato_confirmado(self):
        d = cc.para_detalhe(cc.extrair_campos(C200))
        for proibido in ("atingiu_curso_agua", "vitimas", "evacuacao", "bloqueio_via", "atingiu_solo",
                         "risco_estrutura", "risco_abastecimento", "saiu_limite_operacao", "indicios_narrativos"):
            self.assertNotIn(proibido, d)
        self.assertEqual(d["modalidade"], "Transporte Rodoviário")

    def test_negacao_e_ausencia_de_recursos_hidricos(self):
        d = "Veículo se incendiou. Não foi verificado vazamento. Sem recursos hídricos nas proximidades."
        r = cc._indicios_narrativos(d)
        self.assertEqual(r["incendio"], "afirmado")
        self.assertNotIn("curso_dagua", r)   # "recursos hídricos" não é tema de curso d'água; nada é inferido

    def test_data_inexistente_ou_ausente_vira_none(self):
        c = cc.extrair_campos("MODALIDADE DO ACIDENTE: X\nDATA/HORA DA OCORRÊNCIA: 31/02/2026 - 10:00:00\nPRODUTO: Y")
        self.assertIsNone(c["data_hora_ocorrencia"])
        self.assertFalse(c["cabecalho_reconhecido"])

    def test_atraso_negativo_nao_e_inventado(self):
        t = ("MODALIDADE DO ACIDENTE: X\nDATA/HORA DA OCORRÊNCIA: 10/09/2026 - 10:00:00\n"
             "DATA/HORA DO COMUNICADO AO NEA: 09/09/2026 - 10:00:00\nPRODUTO: Y")
        self.assertIsNone(cc.extrair_campos(t)["atraso_comunicacao_minutos"])

    def test_rotulo_minusculo_na_narrativa_nao_e_rotulo(self):
        t = ("MODALIDADE DO ACIDENTE: Transporte\nBREVE DESCRIÇÃO DA OCORRÊNCIA: o produto: foi derramado, local: pista.\n"
             "PRODUTO: Diesel | NÚMERO ONU: 1202 | CLASSE DE RISCO: 3\n")
        c = cc.extrair_campos(t)
        self.assertEqual(c["produto"], "Diesel")
        self.assertEqual(c["numero_onu"], "1202")
        self.assertIn("local: pista", c["descricao_literal"])

    def test_texto_vazio_ou_ilegivel(self):
        for t in (None, "", "lixo de ocr sem rotulos"):
            c = cc.extrair_campos(t)
            self.assertFalse(c["cabecalho_reconhecido"])
            self.assertEqual(c["campos_lidos"], 0)
            self.assertEqual(cc.para_detalhe(c), {})


if __name__ == "__main__":
    unittest.main()

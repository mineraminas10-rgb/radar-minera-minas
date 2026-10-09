"""
Regressão do motor de score do Módulo 8 contra a Carta Operacional M8 v1.0.

IMPORTANTE sobre o que este arquivo prova e o que não prova:

- score_vinculo é testado com os 21 casos congelados (10 positivos + 10
  negativos + 1 limítrofe, carta §11/§12/§13). Os sinais (SignaisVinculo)
  de cada caso foram derivados A MÃO a partir do texto "fato esperado" /
  "produto ou ocorrência" que a própria carta dá para cada caso — isso é
  uma leitura fiel do que a carta descreve, mas não é o texto integral do
  documento real (que teria muito mais detalhe). Serve para provar que a
  ARITMÉTICA e os LIMIARES da regra estão implementados corretamente e que
  as travas (município sozinho, concentrado de pigmento, carga de minério
  em transporte rodoviário) funcionam. NÃO prova que um extrator de texto
  automático vai identificar esses sinais certo em um documento real —
  isso só pode ser validado com amostra real (extractor.py, pendente).

- score_gravidade é testado com valores de sinais explícitos (unit tests
  isolados dos limiares), não com os 10 casos positivos da amostra —
  os resumos de uma linha da carta não trazem detalhe suficiente para
  derivar com confiança todos os 6 sinais de gravidade de cada caso (ex.:
  "aumento de turbidez... associado a vazamento em adutora da Copasa" não
  diz se ultrapassou limite da operação, se há risco de abastecimento
  etc. — isso exige o documento completo). Marcar como pendente de
  validação contra os 10 casos reais quando os documentos chegarem.

Rodar: python3 -m pytest test_scoring.py -v   (ou: python3 test_scoring.py)
"""
import sys
import unittest
from scoring import SignaisVinculo, SignaisGravidade, score_vinculo, score_gravidade, calcular_atraso_minutos
import datetime


class TestScoreVinculoRegras(unittest.TestCase):
    """Testes isolados de cada trava/regra do §8, independentes da amostra."""

    def test_municipio_minerador_sozinho_nao_e_prova_suficiente(self):
        # M8-A05
        sig = SignaisVinculo(municipio_minerador=True)
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, 0)
        self.assertEqual(faixa, "descartado")

    def test_municipio_minerador_conta_so_como_desempate_com_evidencia_direta(self):
        sig = SignaisVinculo(material_mineral=True, municipio_minerador=True)
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, 6)  # 5 + 1
        self.assertEqual(faixa, "provavel")

    def test_concentrado_pigmento_nao_e_concentrado_mineral(self):
        # M8-A06 — o extrator não deve marcar material_mineral=True para
        # "Concentrado Alcatone" (pigmento p/ tintas). Aqui testamos que,
        # SE o extrator classificar corretamente (material_mineral=False),
        # o produto não-minerário é descartado.
        sig = SignaisVinculo(produto_causa_nao_mineraria=True)
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, -4)
        self.assertEqual(faixa, "descartado")

    def test_carga_de_minerio_nao_e_descartada_so_pela_modalidade_rodoviaria(self):
        # M8-A07
        sig = SignaisVinculo(material_mineral=True, acidente_rodoviario_comum=True)
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, 5)  # redutor não se aplica: há evidência direta (material_mineral)
        self.assertEqual(faixa, "provavel")

    def test_acidente_rodoviario_comum_sem_vinculo_e_descartado(self):
        sig = SignaisVinculo(acidente_rodoviario_comum=True)
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, -3)
        self.assertEqual(faixa, "descartado")

    def test_teto_de_10_pontos_positivos_antes_dos_redutores(self):
        sig = SignaisVinculo(
            modalidade_mineracao=True, mina_identificada=True,
            material_mineral=True, insumo_estrutura_vinculada=True,
            municipio_minerador=True,
        )  # soma bruta 4+4+5+2+1 = 16
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(score, 10)
        self.assertEqual(faixa, "confirmado")


class TestScoreGravidadeLimiares(unittest.TestCase):

    def test_zero_sinais_e_arquivo_contextual(self):
        score, nivel = score_gravidade(SignaisGravidade())
        self.assertEqual(score, 0)
        self.assertEqual(nivel, "arquivo_contextual")

    def test_sete_pontos_e_alerta_imediato(self):
        sig = SignaisGravidade(
            atingiu_ou_pode_atingir_curso_dagua=True,  # 3
            ultrapassou_limites_operacao=True,          # 2
            rejeito_ou_produto_perigoso_ou_volume_significativo=True,  # 2
        )
        score, nivel = score_gravidade(sig)
        self.assertEqual(score, 7)
        self.assertEqual(nivel, "alerta_imediato")

    def test_quatro_pontos_e_pauta_apuracao(self):
        sig = SignaisGravidade(ultrapassou_limites_operacao=True, risco_estrutural_ou_interrupcao_abastecimento=True)
        score, nivel = score_gravidade(sig)
        self.assertEqual(score, 4)
        self.assertEqual(nivel, "pauta_apuracao")

    def test_um_ponto_e_registro_acompanhamento(self):
        sig = SignaisGravidade(comunicacao_mais_de_6_horas=True)
        score, nivel = score_gravidade(sig)
        self.assertEqual(score, 1)
        self.assertEqual(nivel, "registro_acompanhamento")


class TestAtrasoComunicacao(unittest.TestCase):

    def test_caso_turmalina_atraso_21h11(self):
        # M8-A08: "cerca de 21 horas e 11 minutos no caso da Mina Turmalina"
        tz = datetime.timezone(datetime.timedelta(hours=-3))
        ocorrencia = datetime.datetime(2026, 8, 29, 10, 0, tzinfo=tz)
        comunicacao = ocorrencia + datetime.timedelta(hours=21, minutes=11)
        atraso = calcular_atraso_minutos(ocorrencia, comunicacao)
        self.assertEqual(atraso, 21 * 60 + 11)
        self.assertGreater(atraso, 6 * 60)  # aciona +1 no score de gravidade


# ============================================================================
# Amostra congelada — 10 positivos, 10 negativos, 1 limítrofe (carta §11/12/13)
# Sinais derivados à mão do texto da carta (ver aviso no topo do arquivo).
# ============================================================================

POSITIVOS = [
    ("179/2026 Conceição do Pará (Mina Turmalina)",
     SignaisVinculo(mina_identificada=True, material_mineral=True)),
    ("163/2026 Conceição do Mato Dentro (barragem, sirene)",
     SignaisVinculo(mina_identificada=True, insumo_estrutura_vinculada=True)),
    ("160/2026 Nova Lima (Mina Mutuca — turbidez = sedimento da operação, carta §8 lista 'sedimento' em material_mineral)",
     SignaisVinculo(mina_identificada=True, material_mineral=True)),
    ("156/2026 Congonhas (Mina de Viga, Vale/CSN citadas)",
     SignaisVinculo(mina_identificada=True, material_mineral=True)),
    ("148/2026 Sabará (AngloGold — turbidez a jusante das operações = sedimento da operação)",
     SignaisVinculo(mina_identificada=True, material_mineral=True)),
    ("138/2026 Mariana (Mina da Fazenda, polímero)",
     SignaisVinculo(mina_identificada=True, insumo_estrutura_vinculada=True)),
    ("131/2026 Conceição do Mato Dentro (Anglo American, nitrato de amônia)",
     SignaisVinculo(mina_identificada=True, insumo_estrutura_vinculada=True)),
    ("128/2026 Barão de Cocais (carga de minério granulado, tombamento rodoviário)",
     SignaisVinculo(material_mineral=True, acidente_rodoviario_comum=True)),
    ("106/2026 Itabira (Mina de Periquito, Vale — diesel em área externa da mina)",
     SignaisVinculo(mina_identificada=True, insumo_estrutura_vinculada=True)),
    ("68/2026 Itatiaiuçu (Mineração Usiminas, sumps)",
     SignaisVinculo(mina_identificada=True, insumo_estrutura_vinculada=True)),
]

NEGATIVOS = [
    ("183/2026 Mariana (Concentrado Alcatone — pigmento p/ tintas)",
     SignaisVinculo(produto_causa_nao_mineraria=True)),
    ("166/2026 Paracatu (Lifewood 60 — produto industrial)",
     SignaisVinculo(produto_causa_nao_mineraria=True)),
    ("175/2026 Três Marias (carvão vegetal, transporte comum)",
     SignaisVinculo(acidente_rodoviario_comum=True)),
    ("177/2026 Três Marias (óleos lubrificantes)",
     SignaisVinculo(produto_causa_nao_mineraria=True)),
    ("172/2026 Virgem da Lapa (emulsão asfáltica)",
     SignaisVinculo(produto_causa_nao_mineraria=True)),
    ("147/2026 São Gonçalo do Rio Abaixo (cimento asfáltico, usina de asfalto)",
     SignaisVinculo(produto_causa_nao_mineraria=True)),
    ("140/2026 Nova Era (leite cru refrigerado)",
     SignaisVinculo(acidente_rodoviario_comum=True)),
    ("126/2026 Sabará (emulsão asfáltica — município minerador, ocorrência não minerária)",
     SignaisVinculo(municipio_minerador=True, produto_causa_nao_mineraria=True)),
    ("115/2026 João Monlevade (tintas, acidente rodoviário comum)",
     SignaisVinculo(acidente_rodoviario_comum=True)),
    ("76/2026 Itatiaiuçu (rompimento de barramento na Fazenda do Caju, sem vínculo minerário)",
     SignaisVinculo()),  # nenhum sinal positivo nem redutor específico — nada aponta pro setor
]

LIMITROFE = (
    "191/2026 São João del-Rei (coque verde de petróleo, tombamento)",
    SignaisVinculo(cadeia_mineral_industrial_nao_confirmada=True),
    # Carta §13: "a carga possui relação com cadeias mineral e industrial,
    # mas o documento não comprova por si só vínculo com uma mineradora,
    # mina ou operação mineral" — nem confirma nem descarta, deve seguir
    # para revisão. Ver comentário em scoring.py sobre este sinal ser uma
    # adição minha além das 7 regras literais do §8 — pendente de
    # confirmação da Rapha.
)


class TestAmostraM8Congelada(unittest.TestCase):

    def test_todos_os_positivos_ficam_confirmados_ou_provaveis(self):
        # M8-A02: "Classifica os 10 positivos como confirmados ou revisão
        # confirmada, sem perder nenhum deles."
        falhas = []
        for nome, sig in POSITIVOS:
            score, faixa, just = score_vinculo(sig)
            if faixa not in ("confirmado", "provavel"):
                falhas.append(f"{nome}: score={score} faixa={faixa}")
        self.assertEqual(falhas, [], "positivos perdidos (foram p/ contextual/descartado):\n" + "\n".join(falhas))

    def test_todos_os_negativos_ficam_contextuais_ou_descartados(self):
        # M8-A03: "Descarta os 10 negativos com o motivo correto e sem
        # encaminhá-los como pauta minerária."
        falhas = []
        for nome, sig in NEGATIVOS:
            score, faixa, just = score_vinculo(sig)
            if faixa in ("confirmado", "provavel"):
                falhas.append(f"{nome}: score={score} faixa={faixa} (deveria ser contextual/descartado)")
        self.assertEqual(falhas, [], "negativos viraram pauta minerária:\n" + "\n".join(falhas))

    def test_caso_limitrofe_vai_para_revisao_nao_confirma_nem_descarta(self):
        # M8-A04: mantém o coque verde de petróleo na revisão manual.
        nome, sig = LIMITROFE
        score, faixa, just = score_vinculo(sig)
        self.assertEqual(faixa, "provavel")
        self.assertEqual(score, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

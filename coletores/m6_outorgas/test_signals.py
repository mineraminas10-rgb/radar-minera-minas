"""
Regressão de signals.py contra a Carta de Homologação M6-V1.0 §3
("Gabarito de segmentação e classificação") e §23 da Carta M6 v0.8
("Regra semântica obrigatória").
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from signals import (  # noqa: E402
    classificar_ato, tem_vinculo_mineral, SinaisVinculoMineral,
    VINCULO_CONFIRMADO, VINCULO_NAO_MINERAL_CONFIRMADO, VINCULO_INDETERMINADO,
)


class TestClassificarAtoNuncaUsaCabecalhoOuNomeArquivo(unittest.TestCase):
    """Os 5 atos de 22 e 23/09 vêm de arquivos cujo cabeçalho diz
    'Cancelamentos' — a carta exige que NENHUM seja classificado como
    cancelamento (critério M6 A03)."""

    def test_rima_fica_mantido_indeferimento(self):
        trecho = "Fica mantido o indeferimento da Portaria 00429, nos termos do artigo 7 da Portaria de Outorga 03250/2010."
        self.assertEqual(classificar_ato(trecho), "manutencao_indeferimento")

    def test_plascar_fica_mantido_arquivamento(self):
        trecho = "Fica mantido o arquivamento do processo referente a Plascar Indústria de Componentes Plásticos Ltda."
        self.assertEqual(classificar_ato(trecho), "manutencao_arquivamento")

    def test_unimed_fica_mantido_indeferimento(self):
        trecho = "Fica mantido o indeferimento referente a Unimed BH."
        self.assertEqual(classificar_ato(trecho), "manutencao_indeferimento")

    def test_codemig_anula_arquivamento(self):
        trecho = "Anula o arquivamento publicado em 6 de janeiro de 2026 da Portaria 18.03.0001187.2025, por autotutela."
        self.assertEqual(classificar_ato(trecho), "anulacao_arquivamento")

    def test_nenhum_resultado_e_cancelamento(self):
        trechos = [
            "Fica mantido o indeferimento da Portaria 00429.",
            "Fica mantido o arquivamento do processo de Plascar.",
            "Fica mantido o arquivamento do processo de Alan Alves Pedroza.",
            "Fica mantido o arquivamento do processo da Associação Versailles Ville de France.",
            "Fica mantido o indeferimento referente a Unimed BH.",
            "Anula o arquivamento da Portaria 18.03.0001187.2025, processo 00722/2025, por autotutela.",
        ]
        for trecho in trechos:
            self.assertNotIn("cancelamento", classificar_ato(trecho), msg=trecho)

    def test_titulo_do_arquivo_nunca_entra_na_funcao(self):
        # A função só recebe o trecho decisório — o título "Cancelamentos"
        # do arquivo não é parâmetro desta função. Isso é estrutural: não
        # há como classificar_ato() enxergar o nome do arquivo.
        import inspect
        assinatura = inspect.signature(classificar_ato)
        self.assertEqual(list(assinatura.parameters), ["trecho_literal"])

    def test_verbo_nao_identificado_nao_vira_default_silencioso(self):
        self.assertEqual(classificar_ato("Texto sem nenhum verbo decisório reconhecível."), "indeterminado")

    def test_retificacao(self):
        self.assertEqual(classificar_ato("Onde se lê 'João', leia-se 'João da Silva'."), "retificacao")

    def test_concessao(self):
        self.assertEqual(classificar_ato("Autoriza a emissão de outorga para captação de água."), "concessao_outorga")


class TestFiltroBaratoVinculoMineral(unittest.TestCase):
    """Carta de Homologação M6-V1.0, critério M6 A08: os quatro atos
    evidentemente não minerais (Plascar, Alan Alves Pedroza, Associação
    Versailles Ville de France, Unimed BH) são eliminados antes da
    chamada cara de IA — e nunca por serem 'nome desconhecido', só por
    ausência de finalidade/atividade mineral documentada."""

    def test_plascar_sem_vinculo_mineral(self):
        # A carta não divulga a finalidade exata deste ato (só o rótulo
        # final "fora do núcleo mineral") — texto de teste abaixo é uma
        # suposição razoável (água para processo industrial não-mineral,
        # consumo humano/sanitário da planta), não extraída da carta.
        sinais = SinaisVinculoMineral(
            titular="Plascar Indústria de Componentes Plásticos Ltda",
            finalidade_uso="abastecimento e consumo humano na planta industrial de componentes plásticos",
        )
        status, motivo = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_NAO_MINERAL_CONFIRMADO)

    def test_unimed_sem_vinculo_mineral(self):
        sinais = SinaisVinculoMineral(titular="Unimed BH", finalidade_uso="uso hospitalar/saúde")
        status, _ = tem_vinculo_mineral(sinais)
        # "saúde"/"hospitalar" não estão na lista explícita de termos
        # não-minerais — sem finalidade que module um dos dois lados, o
        # resultado correto é indeterminado (apuração humana), não uma
        # eliminação automática por "nome não parece empresa mineradora".
        self.assertEqual(status, VINCULO_INDETERMINADO)

    def test_rima_com_vinculo_mineral_documentado(self):
        # A carta associa a Rima à "cadeia mineral e metalúrgica" como
        # justificativa de relevância — o vínculo vem da ATIVIDADE
        # documentada, nunca do nome da empresa sozinho.
        sinais = SinaisVinculoMineral(
            titular="Rima Industrial S A",
            atividade_associada="unidade industrial ligada à cadeia de mineração e metalurgia",
        )
        status, motivo = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_CONFIRMADO)

    def test_codemig_vinculo_indeterminado_fica_em_apuracao_nao_descartado(self):
        # Carta de Homologação M6-V1.0 §5: "o nome Codemig é um sinal [...]
        # mas não prova vínculo mineral daquele ato [...] permanece em
        # revisão controlada" — isto é indeterminado, não "confirmado
        # não-mineral" (Plascar/Unimed), e a diferença importa: Codemig
        # não é eliminado, fica pendente de apuração.
        sinais = SinaisVinculoMineral(
            titular="Codemig",
            finalidade_uso="hipótese turística ou hidromineral não confirmada no processo",
        )
        status, _ = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_INDETERMINADO)

    def test_nome_da_empresa_sozinho_nunca_decide(self):
        # Mesmo "Vale" no nome não basta sem finalidade/atividade mineral
        # documentada (carta §44.9: "nunca afirmar relação [...] apenas
        # porque pertencem à mesma empresa").
        sinais = SinaisVinculoMineral(titular="Vale Agropecuária e Turismo Ltda", finalidade_uso="turismo rural")
        status, _ = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_NAO_MINERAL_CONFIRMADO)

    def test_municipio_minerador_sozinho_nunca_decide(self):
        # Carta §43.4: "mesmo que ocorra em município minerador" não basta.
        sinais = SinaisVinculoMineral(titular="Qualquer Ltda", finalidade_uso="irrigação de hortaliças")
        status, _ = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_NAO_MINERAL_CONFIRMADO)

    def test_portaria_coletiva_agricola_fora_de_escopo(self):
        sinais = SinaisVinculoMineral(
            titular="Diversos (portaria coletiva)",
            finalidade_uso="agricultura, irrigação, consumo humano e animal, limpeza, agroindústria, lazer e turismo",
        )
        status, _ = tem_vinculo_mineral(sinais)
        self.assertEqual(status, VINCULO_NAO_MINERAL_CONFIRMADO)


if __name__ == "__main__":
    unittest.main()

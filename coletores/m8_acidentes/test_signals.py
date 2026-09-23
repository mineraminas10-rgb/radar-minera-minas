import unittest

from signals import (
    extrair_signais_vinculo,
    extrair_evidencias_vinculo,
    extrair_evidencias_gravidade,
)


class TestEvidenciasVinculo(unittest.TestCase):

    def test_material_mineral_gera_evidencia_com_trecho(self):
        texto = "Houve derramamento de minério de ferro na pista da rodovia."
        evidencias = extrair_evidencias_vinculo(texto)
        campos = {e["campo"] for e in evidencias}
        self.assertIn("material_mineral", campos)
        # o trecho literal precisa conter a palavra que disparou o sinal
        ev_material = next(e for e in evidencias if e["campo"] == "material_mineral")
        self.assertIn("minério", ev_material["trecho_literal"].lower())

    def test_negacao_nao_gera_evidencia_falsa(self):
        # mesmo texto do teste de sinais que comprova a guarda de negação —
        # aqui a garantia é que a evidência (não só o booleano) respeita a
        # negação: não faz sentido gravar um trecho como "prova" de vínculo
        # minerário quando o próprio texto nega o vínculo.
        texto = "Comunicado sem vínculo minerário comprovado; produto é pigmento industrial."
        evidencias = extrair_evidencias_vinculo(texto)
        campos = {e["campo"] for e in evidencias}
        self.assertNotIn("modalidade_mineracao", campos)

    def test_sem_sinais_lista_vazia(self):
        texto = "Vazamento de óleo lubrificante de caminhão de carga geral."
        evidencias = extrair_evidencias_vinculo(texto)
        campos = {e["campo"] for e in evidencias}
        self.assertNotIn("material_mineral", campos)
        self.assertNotIn("modalidade_mineracao", campos)

    def test_dedup_mesmo_trecho_nao_repete(self):
        # duas palavras da mesma lista na mesma frase não devem gerar duas
        # evidências idênticas pro mesmo campo+trecho
        texto = "atividade minerária de mineração intensa na região"
        evidencias = extrair_evidencias_vinculo(texto)
        pares = [(e["campo"], e["trecho_literal"]) for e in evidencias]
        self.assertEqual(len(pares), len(set(pares)))


class TestEvidenciasGravidade(unittest.TestCase):

    def test_curso_dagua_gera_evidencia(self):
        texto = "O material atingiu o córrego próximo à captação de água do município."
        evidencias = extrair_evidencias_gravidade(texto)
        campos = {e["campo"] for e in evidencias}
        self.assertIn("atingiu_ou_pode_atingir_curso_dagua", campos)

    def test_vitimas_evacuacao_gera_evidencia(self):
        texto = "Houve evacuação preventiva de moradores próximos à estrutura."
        evidencias = extrair_evidencias_gravidade(texto)
        campos = {e["campo"] for e in evidencias}
        self.assertIn("vitimas_evacuacao_bloqueio_ou_risco_comunidade", campos)


class TestConsistenciaComSignais(unittest.TestCase):
    """As evidências e os sinais booleanos têm que concordar: se o sinal
    booleano é True, tem que existir pelo menos uma evidência pro campo
    correspondente (checklist: 'exigir ao menos uma evidência ativa para
    cada frase factual')."""

    def test_todo_sinal_positivo_tem_evidencia(self):
        texto = "Comunicado de tombamento envolvendo minério de ferro e nitrato de amônia na barragem."
        sinais = extrair_signais_vinculo(texto)
        evidencias = extrair_evidencias_vinculo(texto)
        campos_com_evidencia = {e["campo"] for e in evidencias}

        mapa_sinal_para_campo = {
            "modalidade_mineracao": sinais.modalidade_mineracao,
            "material_mineral": sinais.material_mineral,
            "insumo_estrutura_vinculada": sinais.insumo_estrutura_vinculada,
        }
        for campo, valor in mapa_sinal_para_campo.items():
            if valor:
                self.assertIn(campo, campos_com_evidencia, f"sinal {campo}=True sem evidência correspondente")


if __name__ == "__main__":
    unittest.main()

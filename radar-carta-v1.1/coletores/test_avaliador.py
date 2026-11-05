import unittest
from datetime import date
from avaliador import avaliar_evento
from comum.portas_editoriais import avaliar_descoberta, _semantica

class TestCartaV11(unittest.TestCase):
    def test_ambiental_isolado_abre_porta_sem_exigir_social(self):
        r = avaliar_descoberta({"titulo":"Mineração relata contaminação de aquífero","fonte_url":"https://oficial.gov.br/a"})
        self.assertEqual(r["resultado_pre_filtro"], "CLASSIFICAR_AGORA")
        self.assertIn("P1_DANO_OU_RISCO_AMBIENTAL", r["portas_editoriais_ativadas"])

    def test_decisao_regulatoria_abre_porta_independente(self):
        r = avaliar_descoberta({"titulo":"Evento de mineração","texto_documento":"Decisão regulatória publicada.","processo_anm":"123","fonte_url":"https://oficial.gov.br/a"})
        self.assertIn("P4_DECISAO_REGULATORIA_MATERIAL", r["portas_editoriais_ativadas"])

    def test_ausencia_de_conteudo_vai_para_revisao(self):
        r = avaliar_evento({"numero_processo":"123","fonte_url":"https://oficial.gov.br/a"})
        self.assertEqual(r["status_triagem"], "em_revisao")
        self.assertEqual(r["resultado_pre_filtro"], "NAO_AVALIAVEL")

    def test_alegacao_e_rotulada_sem_confirmar_nexo(self):
        r = avaliar_descoberta({"titulo":"Mineração","texto_documento":"Segundo moradores, houve contaminação do córrego.","fonte_url":"https://oficial.gov.br/a"})
        sinais = r["portas_editoriais_ativadas"]["P1_DANO_OU_RISCO_AMBIENTAL"]
        self.assertEqual(sinais[0]["natureza"], "ALEGACAO_OU_INVESTIGACAO")

    def test_negativa_nao_abre_porta_de_dano(self):
        r = avaliar_descoberta({"titulo":"Mineração","texto_documento":"Não foi constatada contaminação do solo.","fonte_url":"https://oficial.gov.br/a"})
        self.assertNotIn("P1_DANO_OU_RISCO_AMBIENTAL", r["portas_editoriais_ativadas"])
        self.assertEqual(r["resultado_pre_filtro"], "PENDENTE_DE_EVIDENCIA")

    def test_watchlist_sem_novidade_fica_em_monitoramento(self):
        e = {"titulo":"Empresa minerária","empresa_watchlist":True,"fonte_url":"https://oficial.gov.br/a"}
        self.assertEqual(avaliar_descoberta(e)["resultado_pre_filtro"], "MONITORAMENTO_ESTRATEGICO")
        e["evento_novo"] = True
        self.assertIn("P8_ENTIDADE_PROJETO_OU_ATIVO_ESTRATEGICO", avaliar_descoberta(e)["portas_editoriais_ativadas"])

    def test_vinculo_contextual_permanece_pendente(self):
        e={"titulo":"Decisão publicada","evidencias_contextuais":[{"tipo":"municipio","valor":"Mariana"},{"tipo":"empresa","valor":"X"}],"fonte_url":"https://oficial.gov.br/a"}
        self.assertEqual(avaliar_descoberta(e)["resultado_pre_filtro"], "PENDENTE_DE_EVIDENCIA")

    def test_cnae_qualifica_vinculo_mas_nao_altera_score_ou_checklist(self):
        r=avaliar_descoberta({"titulo":"Auto de infração","cnae":"07.10-3/01","fonte_url":"https://oficial.gov.br/a"})
        self.assertEqual(r["vinculo_minerario"],"DIRETO")
        self.assertIsNone(r["score_editorial"])
        self.assertIsNone(r["checklist_12"])

    def test_semantica_distingue_pedido_de_decisao(self):
        self.assertEqual(_semantica("Pedido de licença protocolado."),"PEDIDO_AINDA_NAO_DECIDIDO")
        self.assertEqual(_semantica("O órgão indeferiu o pedido."),"DECISAO_NEGATIVA")

    def test_avaliador_antigo_ambiental_mais_social_nao_e_mais_gate(self):
        e={"numero_processo":"123","metadados":"Mineração de ouro","texto_fiscal":"O órgão publicou decisão sobre a licença.","fonte_url":"https://oficial.gov.br/a"}
        r=avaliar_evento(e,date(2026,10,21))
        self.assertEqual(r["status_triagem"],"candidato_fila_editor")
        self.assertEqual(r["resultado_pre_filtro"],"CLASSIFICAR_AGORA")
        self.assertEqual(r["revisao_humana"],"pendente")
        self.assertFalse(r["publicado"])

    def test_termo_nao_minerario_nao_e_vinculo_direto(self):
        r=avaliar_descoberta({"titulo":"Tesouro estadual e obras urbanas","cnae":"49.30-2/01","fonte_url":"https://oficial.gov.br/a"})
        self.assertEqual(r["resultado_pre_filtro"],"FORA_DO_ESCOPO")

if __name__ == "__main__":
    unittest.main()

"""Testes da régua CRIT-V1.2 (comum/criticidade.py). Todos os tipos SCM abaixo existem na base real."""
import copy
import json
import unittest
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import criticidade as c

HOJE = date(2026, 10, 14)
PAR = c.carregar_parametros()


def m9a(tipo, data="2026-08-01", titular="Empresa Qualquer Ltda", subst="GRANITO", area=100, mun=1, ev=True, par=PAR):
    return c.classificar_m9a({"tipo_scm": tipo, "data_ato": data, "titular": titular, "substancia": subst,
                              "area_ha": area, "n_municipios": mun, "tem_evidencia": ev}, par, HOJE)


# ---------------------------------------------------------------- premissas corrigidas
def test_p1_pedido_de_cessao_nunca_vale_como_efetivado():
    r = m9a("AUT PESQ/TRANSF DIREITOS-CESSÃO TOTAL PROTOC", titular="Kinross Brasil", subst="MINÉRIO DE OURO", area=2000)
    assert r.fase == "pedido" and r.nivel == "BAIXA" and r.prioridade == "D"
    assert "pedido_nunca_vale_como_ato_efetivado" in r.motivos


def test_p1_cessao_efetivada_com_reforcos_e_atual_sobe():
    r = m9a("AUT PESQ/TRANSF DIREITOS-CESSÃO TOTAL APROVADA PUBL", titular="Kinross Brasil", subst="MINÉRIO DE OURO", area=1096)
    assert r.fase == "efetiva" and r.nivel == "ALTA" and r.prioridade == "B"


def test_p2_rotina_anula_todos_os_gatilhos():
    # TAH com empresa relevante, mineral estratégico e área enorme continua ROTINA
    r = m9a("AUT PESQ/TAH - PAGAMENTO EFETUADO", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=5000, mun=3)
    assert r.nivel == "ROTINA" and r.prioridade == "D" and not r.selecionavel
    assert r.motivos == ["rotina_anula_gatilhos"]


def test_p2_rotina_vence_palavra_de_cessao():
    r = m9a("REQ LAV/CUMPRIMENTO EXIGÊNCIA PROTOC")
    assert r.nivel == "ROTINA"
    r = m9a("REQ PESQ/DOCUMENTO DIVERSO PROTOC", titular="Vale")
    assert r.nivel == "ROTINA"


def test_rotina_nao_casa_por_substring():
    # 'art' (ART) só casa como palavra inteira; 'particular' não é rotina
    assert c._contem(c.normalizar("PARTICULAR").split(), ["art"]) is False
    assert c._contem(c.normalizar("APRESENTA ART").split(), ["art"]) is True


# ---------------------------------------------------------------- níveis por ato
def test_decaimento_de_concessao_de_lavra_recente_e_critico():
    r = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", titular="AngloGold", subst="OURO")
    assert r.nivel == "CRITICO" and r.prioridade == "A" and r.selecionavel


def test_decaimento_de_pesquisa_e_alta():
    r = m9a("AUT PESQ/DECAIMENTO ALVARÁ PESQUISA PUBL", data="2026-05-05")
    assert r.objeto == "perda_titulo" and r.nivel == "ALTA"


def test_penhor_averbado_com_ferro_e_alta_se_recente_e_baixa_se_antigo():
    novo = m9a("ONERAÇÃO DIREITOS - PENHOR AVERBADO", data="2026-06-01", subst="FERRO")
    assert novo.objeto == "gravame" and novo.nivel == "ALTA"
    velho = m9a("ONERAÇÃO DIREITOS - PENHOR AVERBADO", data="2018-08-01", subst="FERRO")
    assert velho.nivel == "BAIXA" and velho.idade_dias > 1095


def test_guia_de_utilizacao_concedida_com_area_e_alta():
    r = m9a("AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL", data="2026-08-11", subst="MINÉRIO DE FERRO", area=688)
    assert r.objeto == "autorizacao_extracao" and r.nivel == "ALTA"


def test_alvara_de_pesquisa_antigo_de_empresa_relevante_nao_e_prioridade():
    r = m9a("AUT PESQ/ALVARÁ DE PESQUISA 03 ANOS PUBL", data="2018-07-26", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=1666)
    assert r.nivel == "BAIXA" and not r.selecionavel


def test_alvara_recente_com_reforco_e_media():
    r = m9a("AUT PESQ/ALVARÁ DE PESQUISA 03 ANOS PUBL", data="2026-09-01", titular="NEXA RECURSOS MINERAIS", subst="MINÉRIO DE ZINCO")
    assert r.nivel == "MEDIA" and r.prioridade == "C" and r.selecionavel


def test_pedido_de_servidao_e_edital_ficam_baixa():
    assert m9a("CONC LAV/ÁREA SERVIDÃO CONCEDIDA PUBL", data="2026-09-01", titular="USIMINAS").nivel == "MEDIA"
    assert m9a("AUT PESQ/ÁREA DISPONIBILIDADE PARA PESQUISA - EDITAL PUBL", data="2026-09-01").nivel == "BAIXA"


def test_fase_indefinida_tem_teto_media():
    r = m9a("PORTARIA CONCESSÃO DE LAVRA", data="2026-09-01", titular="Vale", subst="FERRO", area=900)
    assert r.fase == "indefinida" and r.nivel == "MEDIA" and "fase_indefinida_teto_MEDIA" in r.motivos


def test_fase_negativa_baixa():
    r = m9a("REQ LAV/TRANSF DIREITOS -CESSÃO TOTAL INDEFERIDA PUBL", data="2026-09-01", titular="Vale", subst="FERRO")
    assert r.fase == "negativa" and r.nivel == "BAIXA"


# ---------------------------------------------------------------- atualidade parametrizada
def test_cascata_de_idade_critico_180_alta_365_media_1095():
    base = "CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL"
    assert m9a(base, data="2026-05-05").nivel == "CRITICO"          # 162 d
    assert m9a(base, data="2026-03-01").nivel == "ALTA"             # 227 d
    assert m9a(base, data="2025-06-01").nivel == "MEDIA"            # 500 d
    assert m9a(base, data="2022-01-01").nivel == "BAIXA"           # > 1095 d


def test_sem_data_confiavel_teto_baixa():
    r = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data=None)
    assert r.nivel == "BAIXA" and "data_desconhecida_teto_BAIXA" in r.motivos


def test_limites_vem_dos_parametros_nao_do_codigo():
    par2 = copy.deepcopy(PAR)
    par2["m9a"]["atualidade_dias"] = {"CRITICO": 400, "ALTA": 800, "MEDIA": 1500}
    par2["versao_parametros"] = "CRIT-PARAMS-V9.9"
    base = "CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL"
    antigo = m9a(base, data="2026-03-01")                        # 227 d: ALTA com V1.0
    novo = m9a(base, data="2026-03-01", par=par2)                # com limites maiores: CRITICO
    assert antigo.nivel == "ALTA" and novo.nivel == "CRITICO"
    assert novo.versao_parametros == "CRIT-PARAMS-V9.9" and antigo.versao_parametros == "CRIT-PARAMS-V1.2"


def test_limiar_de_area_e_listas_sao_parametros():
    par2 = copy.deepcopy(PAR)
    par2["m9a"]["area_min_ha"] = 100
    t = "AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL"
    assert m9a(t, data="2026-08-11", area=200, subst="GRANITO").nivel == "MEDIA"     # 200 < 500
    assert m9a(t, data="2026-08-11", area=200, subst="GRANITO", par=par2).nivel == "ALTA"


def test_sem_evidencia_nao_rebaixa_em_silencio_vira_potencial_critico():
    r = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", ev=False)
    assert r.nivel == c.ESTADO_POTENCIAL_CRITICO and r.nivel_potencial == "CRITICO"
    assert r.prioridade is None and not r.selecionavel and "pendente_de_evidencia" in r.bloqueios
    assert r.evidencia_suficiente is False and r.pendencia == "evidencia_estruturada"
    assert "potencial_CRITICO_aguarda_evidencia_estruturada" in r.motivos


# ---------------------------------------------------------------- casos curados (sem tipo SCM)
def test_curado_classificado_por_texto_livre():
    r = c.classificar_m9a({"tipo_texto": "Procedimento de decaimento de concessão Instauração de processo administrativo",
                           "data_ato": "2026-05-05", "titular": "ANGLOGOLD ASHANTI CORREGO DO SITIO MINERACAO S.A.",
                           "substancia_texto": "ouro", "area_ha": 1852.42, "tem_evidencia": True}, PAR, HOJE)
    assert r.nivel == "CRITICO" and "classificado_por_texto_livre_sem_tipo_scm" in r.motivos


def test_area_de_texto_formato_brasileiro():
    assert c.area_de_texto("Concessão de ouro e prata com 1.852,42 ha; risco") == 1852.42
    assert c.area_de_texto("688,08 ha em quatro municípios; pilha de 2,1 ha") == 688.08
    assert c.area_de_texto("sem número") is None


# ---------------------------------------------------------------- M8
def m8(**kw):
    base = {"status_processamento": "processado", "faixa_vinculo": "confirmado", "data_ocorrencia": "2026-10-04",
            "confirmados": {}, "sinais_textuais": {}, "score_gravidade": 3, "tem_evidencia": True}
    base.update(kw)
    return c.classificar_m8(base, PAR, HOJE)


def test_m8_falha_de_extracao_nao_e_avaliavel():
    r = m8(status_processamento="falha_extracao")
    assert r.nivel == "NAO_AVALIAVEL" and not r.avaliavel and not r.selecionavel and r.prioridade is None
    assert r.motivos == ["nao_avaliavel_falha_de_extracao"]


def test_m8_vinculo_insuficiente_e_rotina():
    assert m8(faixa_vinculo="contextual").nivel == "ROTINA"
    assert m8(faixa_vinculo="descartado").nivel == "ROTINA"


def test_m8_curso_dagua_so_textual_e_media_nunca_alta():
    r = m8(sinais_textuais={"curso_dagua": True, "rejeito": True})
    assert r.nivel == "MEDIA" and "agravante_apenas_textual_nao_verificado" in r.motivos


def test_m8_fato_confirmado_sobe_e_idade_desce():
    assert m8(confirmados={"vitimas": True}, data_ocorrencia="2026-10-10").nivel == "CRITICO"
    assert m8(confirmados={"atingiu_curso_agua": True}, data_ocorrencia="2026-10-01").nivel == "ALTA"      # 13 d
    assert m8(confirmados={"vitimas": True}, data_ocorrencia="2026-09-20").nivel == "ALTA"                  # 24 d > 15 d
    assert m8(confirmados={"vitimas": True}, data_ocorrencia="2026-08-20").nivel == "MEDIA"                 # 55 d
    assert m8(confirmados={"vitimas": True}, data_ocorrencia="2026-01-20").nivel == "BAIXA"                 # > 90 d


def test_m8_vinculo_provavel_limita_a_media():
    r = m8(faixa_vinculo="provavel", confirmados={"vitimas": True}, data_ocorrencia="2026-10-10")
    assert r.nivel == "MEDIA" and "vinculo_provavel_teto_MEDIA" in r.motivos


# ---------------------------------------------------------------- seleção
def cand(i, nivel, pr, pont, idade, evq=1):
    return {"id_evento": i, "nivel": nivel, "prioridade": pr, "pontuacao": pont, "idade_dias": idade,
            "qualidade_evidencia": evq, "avaliavel": True}


def test_selecao_ordem_piso_e_corte():
    lista = [cand("a", "BAIXA", "D", 100, 1), cand("b", "MEDIA", "C", 50, 30), cand("c", "CRITICO", "A", 0, 100),
             cand("d", "ALTA", "B", 75, 10), cand("e", "MEDIA", "C", 50, 10), cand("f", "ROTINA", "D", 0, 1),
             cand("g", "MEDIA", "C", 50, 10)]
    r = c.selecionar(lista, PAR, limite=3)
    assert [x["id_evento"] for x in r["escolhidos"]] == ["c", "d", "e"]          # critico, alta, media mais recente (e antes de g pela chave)
    assert [x["id_evento"] for x in r["cortados_por_limite"]] == ["g", "b"]
    assert [x["id_evento"] for x in r["abaixo_do_piso"]] == ["a", "f"] or {x["id_evento"] for x in r["abaixo_do_piso"]} == {"a", "f"}


def test_selecao_baixa_e_rotina_ficam_fora_mesmo_com_menos_de_20():
    r = c.selecionar([cand("a", "BAIXA", "D", 100, 1), cand("b", "ROTINA", "D", 0, 1)], PAR)
    assert r["escolhidos"] == [] and len(r["abaixo_do_piso"]) == 2


def test_selecao_e_deterministica_e_independente_da_ordem_de_entrada():
    lista = [cand(str(i), "MEDIA", "C", 25, 10 + (i % 3)) for i in range(30)]
    a = c.selecionar(lista, PAR)["escolhidos"]
    b = c.selecionar(list(reversed(lista)), PAR)["escolhidos"]
    assert [x["id_evento"] for x in a] == [x["id_evento"] for x in b] and len(a) == 20


def test_nao_avaliavel_nunca_e_selecionado():
    x = cand("a", "MEDIA", "C", 50, 10)
    x["avaliavel"] = False
    assert c.selecionar([x], PAR)["escolhidos"] == []


# ---------------------------------------------------------------- parâmetros
def test_parametros_v1_consistentes():
    assert PAR["versao_regra"] == c.VERSAO_REGRA == "CRIT-V1.2"
    assert PAR["prioridade_derivada"] == {"CRITICO": "A", "ALTA": "B", "MEDIA": "C", "BAIXA": "D", "ROTINA": "D", "NAO_AVALIAVEL": None,
                                          "POTENCIAL_CRITICO_PENDENTE_EVIDENCIA": None, "POTENCIAL_ALTA_PENDENTE_EVIDENCIA": None}
    assert PAR["m8"]["atualidade_dias"] == {"CRITICO": 15, "ALTA": 30, "MEDIA": 90}
    assert PAR["piso_selecao"] == ["MEDIA", "ALTA", "CRITICO"]
    assert PAR["m9a"]["atualidade_dias"] == {"CRITICO": 180, "ALTA": 365, "MEDIA": 1095}
    assert PAR["m9a"]["area_min_ha"] == 500
    assert PAR["m9a"]["janela_leitura_dias"] == PAR["m9a"]["atualidade_dias"]["MEDIA"]


class TestGravacaoCriticidade(unittest.TestCase):
    """criticidade_db: nova versão de score sem apagar o histórico e sem empilhar linhas idênticas."""

    class _Q:
        def __init__(self, sb, tab): self.sb, self.tab, self.f, self.op, self.payload = sb, tab, {}, "select", None
        def select(self, *_): return self
        def eq(self, k, v): self.f[k] = v; return self
        def update(self, p): self.op, self.payload = "update", p; return self
        def insert(self, p): self.op, self.payload = "insert", p; return self
        def execute(self):
            class R: pass
            r = R()
            rows = self.sb.rows
            if self.op == "select":
                r.data = [x for x in rows if all(x.get(k) == v for k, v in self.f.items())]
            elif self.op == "update":
                for x in rows:
                    if all(x.get(k) == v for k, v in self.f.items()): x.update(self.payload)
                r.data = []
            else:
                rows.append(dict(self.payload, id=len(rows) + 1)); r.data = []
            return r

    class _SB:
        def __init__(self, rows): self.rows = rows
        def table(self, n): return TestGravacaoCriticidade._Q(self, n)

    def _res(self, tipo="Portaria de lavra", data="2026-09-01"):
        import criticidade_db  # noqa: F401
        par = c.carregar_parametros()
        return c.classificar_m9a({"tipo_scm": tipo, "data_ato": data, "titular": "Vale S.A.", "substancia": "ferro",
                                  "area_ha": 800, "n_municipios": 1, "tem_evidencia": True}, par, date(2026, 10, 14))

    def test_grava_nova_versao_preserva_legada_e_nao_duplica(self):
        import criticidade_db as db
        legado = {"id": 99, "event_id": "E1", "versao_score": "SCORE-M9A-V0.2", "prioridade": "A", "vigente": True,
                  "estagio": "preliminar", "componentes": {"score_m9a": 80}}
        sb = self._SB([legado])
        res = self._res()
        self.assertEqual(db.gravar_criticidade(sb, "E1", res), "gravado")
        self.assertEqual(len(sb.rows), 2)
        self.assertFalse(sb.rows[0]["vigente"])                      # legado preservado, só deixou de ser vigente
        self.assertEqual(sb.rows[0]["prioridade"], "A")
        novo = sb.rows[1]
        self.assertTrue(novo["vigente"])
        self.assertEqual(novo["versao_score"], "CRIT-V1.2")
        self.assertEqual(novo["prioridade"], res.prioridade)
        self.assertEqual(db.gravar_criticidade(sb, "E1", res), "inalterado")     # reexecução não empilha
        self.assertEqual(len(sb.rows), 2)


# ---------------------------------------------------------------- revisão de 14/10/2026 (CRIT-V1.1)
def test_m8_limite_de_requisicoes_e_nao_avaliavel_e_nao_rotina():
    r = m8(status_processamento="falha_extracao", motivo_falha="limite:limite de 200 requisições por rodada")
    assert r.nivel == "NAO_AVALIAVEL" and r.nivel != "ROTINA" and r.prioridade is None
    assert r.motivos == ["nao_avaliavel_documento_nao_aberto_por_limite_de_requisicoes"] and not r.selecionavel


def test_m8_sem_evidencia_suficiente_e_nao_avaliavel():
    r = m8(tem_evidencia=False)
    assert r.nivel == "NAO_AVALIAVEL" and r.motivos == ["nao_avaliavel_sem_evidencia_suficiente"]


def test_m8_lido_sem_vinculo_continua_rotina():
    r = m8(faixa_vinculo="contextual")
    assert r.nivel == "ROTINA" and r.avaliavel


def test_m9a_tipo_desconhecido_e_nao_avaliavel():
    r = m9a("")
    assert r.nivel == "NAO_AVALIAVEL" and r.prioridade is None and not r.selecionavel


def test_nao_avaliavel_nunca_e_selecionado_e_ordena_por_ultimo():
    na = m9a("")
    assert not c.selecionar([{"nivel": na.nivel, "prioridade": na.prioridade, "pontuacao": 0, "idade_dias": None,
                              "avaliavel": False, "id_evento": "x"}], PAR)["escolhidos"]
    assert c.chave_ordenacao({"nivel": "NAO_AVALIAVEL", "prioridade": None, "id_evento": "x"}, PAR["niveis"])[0] == 1


PRORROGACAO = "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA- 01 ANO PUBL"


def test_prorrogacao_prazo_lavra_tem_objeto_proprio_e_nao_cai_em_outro():
    r = m9a(PRORROGACAO, data="2026-08-01", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=900)
    assert r.objeto == "prorrogacao_prazo_requerer_lavra"


def test_prorrogacao_prazo_lavra_decisao_recente_e_media_e_reforco_so_pontua():
    sem = m9a(PRORROGACAO, data="2026-08-01")
    com = m9a(PRORROGACAO, data="2026-08-01", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=900, mun=3)
    assert sem.nivel == com.nivel == "MEDIA"                  # empresa/mineral/área NÃO mudam o nível
    assert com.pontuacao > sem.pontuacao and "prorrogacao_prazo_lavra_decisao_recente" in com.motivos


def test_prorrogacao_prazo_lavra_decisao_antiga_e_baixa():
    r = m9a(PRORROGACAO, data="2025-06-01", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=900)   # 500 d > 365 d
    assert r.nivel == "BAIXA" and "prorrogacao_prazo_lavra_decisao_antiga_ou_sem_data" in r.motivos
    assert m9a(PRORROGACAO, data="2013-05-09", titular="VALE S.A.").nivel == "BAIXA"


def test_prorrogacao_prazo_lavra_pedido_e_baixa_mesmo_recente():
    r = m9a("AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA PROTOC", data="2026-09-30", titular="VALE S.A.", subst="FERRO", area=900)
    assert r.fase == "pedido" and r.nivel == "BAIXA"


def test_prorrogacao_prazo_lavra_nunca_cai_em_outro_em_nenhuma_fase_ou_data():
    variantes = ("AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA PROTOC", "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA- 01 ANO PUBL",
                 "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA INDEFERIDO PUBL", "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA- 01 ANO CONCEDIDA",
                 "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA - 02 ANOS PUBL", "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA NEGADA")
    for tipo in variantes:
        for data in ("2026-09-30", "2013-05-09", None):
            r = m9a(tipo, data=data, titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=900)
            assert r.objeto == "prorrogacao_prazo_requerer_lavra", (tipo, data)
            if r.fase in ("pedido", "negativa") or data != "2026-09-30":
                assert r.nivel == "BAIXA", (tipo, data)       # pedido/negativa/antigo/sem data: sempre BAIXA


def test_janela_recente_da_prorrogacao_e_parametro():
    par2 = copy.deepcopy(PAR)
    par2["m9a"]["prorrogacao_prazo_lavra"]["atualidade_dias_recente"] = 700
    assert m9a(PRORROGACAO, data="2025-06-01").nivel == "BAIXA"
    assert m9a(PRORROGACAO, data="2025-06-01", par=par2).nivel == "MEDIA"


def test_prorrogacao_de_prazo_de_alvara_nao_e_prorrogacao_de_lavra():
    assert m9a("AUT PESQ/PRORROGAÇÃO PRAZO ALVARÁ-S PUBL", data="2026-08-01").objeto == "outro"


def test_rotina_anula_art_exigencia_retificacao_republicacao_procuracao():
    for tipo in ("AUT PESQ/ANOTAÇÃO DE RESPONSABILIDADE TÉCNICA JUNTADA", "REQ LAV/EXIGÊNCIA FORMAL PROTOC",
                 "AUT PESQ/RETIFICAÇÃO DE ALVARÁ PUBL", "AUT PESQ/REPUBLICAÇÃO ALVARÁ PUBL",
                 "REQ PESQ/PROCURAÇÃO JUNTADA", "AUT PESQ/JUNTADA SEM EFEITO"):
        r = m9a(tipo, data="2026-09-30", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=5000, mun=4)
        assert r.nivel == "ROTINA", tipo
        assert r.motivos == ["rotina_anula_gatilhos"], tipo


def test_caso_curado_e_provisorio_e_registra_origem():
    r = c.classificar_m9a({"tipo_scm": None, "tipo_texto": "Penhora de direito minerário", "data_ato": "2026-01-15",
                           "titular": "ITAMINAS", "substancia_texto": "ferro", "area_ha": 0, "n_municipios": 1,
                           "tem_evidencia": True}, PAR, HOJE)
    assert r.provisoria and r.origem_classificacao == "curada"
    assert "classificacao_provisoria_origem_curada" in r.motivos
    comp = r.como_componentes()
    assert comp["provisoria"] is True and comp["origem_classificacao"] == "curada"
    ofic = m9a("AUT PESQ/PENHORA PUBL", data="2026-01-15")
    assert not ofic.provisoria and ofic.origem_classificacao == "tipo_oficial"


def test_ate_20_e_teto_nao_cota():
    cand = [{"nivel": "ALTA", "prioridade": "B", "pontuacao": 50, "idade_dias": 10, "avaliavel": True, "id_evento": f"e{i}"} for i in range(5)]
    cand += [{"nivel": "BAIXA", "prioridade": "D", "pontuacao": 100, "idade_dias": 1, "avaliavel": True, "id_evento": f"b{i}"} for i in range(40)]
    sel = c.selecionar(cand, PAR)
    assert len(sel["escolhidos"]) == 5 and all(x["nivel"] == "ALTA" for x in sel["escolhidos"])


# ---------------------------------------------------------------- ajustes finais de 14/10/2026 (CRIT-V1.2)
def m8(**kw):
    e = {"status_processamento": "processado", "faixa_vinculo": "confirmado", "data_ocorrencia": "2026-10-04",
         "confirmados": {}, "sinais_textuais": {}, "score_gravidade": 5, "tem_evidencia": True}
    e.update(kw)
    return c.classificar_m8(e, PAR, HOJE)


def curado(tipo, data, titular="ANGLOGOLD ASHANTI", subst="ouro", area=1852.42, ev=False):
    return c.classificar_m9a({"tipo_texto": tipo, "data_ato": data, "titular": titular, "substancia_texto": subst,
                              "area_ha": area, "n_municipios": 1, "tem_evidencia": ev}, PAR, HOJE)


def test_falta_de_evidencia_em_alta_vira_potencial_alta_e_nao_media():
    r = m9a("AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL", data="2026-08-11", titular="Vale", subst="MINÉRIO DE FERRO",
            area=688, mun=4, ev=False)
    assert r.nivel == c.ESTADO_POTENCIAL_ALTA and r.nivel_potencial == "ALTA"
    assert r.prioridade is None and not r.selecionavel and r.evidencia_suficiente is False
    assert r.nivel != "MEDIA"


def test_potencial_que_a_idade_ja_rebaixou_para_media_nao_vira_estado_potencial():
    # ALTA com 400 dias desce para MEDIA pela idade; sem evidência fica MEDIA, mas NÃO selecionável
    r = m9a("AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL", data="2025-09-01", subst="MINÉRIO DE FERRO", area=688, ev=False)
    assert r.nivel == "MEDIA" and not r.selecionavel and "evidencia_insuficiente" in r.bloqueios


def test_recalculo_quando_a_evidencia_chega_vira_nivel_definitivo():
    sem = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", ev=False)
    com = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", ev=True)
    assert sem.nivel == c.ESTADO_POTENCIAL_CRITICO and com.nivel == "CRITICO" and com.selecionavel and com.prioridade == "A"
    assert sem.versao_regra == com.versao_regra == "CRIT-V1.2"


def test_curado_nunca_e_definitivo_nem_com_evidencia_mas_sobe_do_pendente():
    sem = curado("Procedimento de decaimento de concessão Instauração de processo administrativo", "2026-05-05")
    com = curado("Procedimento de decaimento de concessão Instauração de processo administrativo", "2026-05-05", ev=True)
    assert sem.provisoria and com.provisoria and sem.origem_classificacao == com.origem_classificacao == "curada"
    assert sem.nivel == c.ESTADO_POTENCIAL_CRITICO
    assert com.nivel == "CRITICO" and not com.selecionavel and "classificacao_provisoria" in com.bloqueios


def test_curado_ganha_tipo_oficial_e_recalcula_pela_mesma_regua():
    com_tipo = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", titular="ANGLOGOLD ASHANTI", subst="ouro",
                   area=1852.42, ev=True)
    assert not com_tipo.provisoria and com_tipo.origem_classificacao == "tipo_oficial" and com_tipo.selecionavel


def test_m8_agravante_so_por_palavra_chave_e_provisorio_e_nao_selecionavel():
    r = m8(sinais_textuais={"curso_dagua": True})
    assert r.nivel == "MEDIA" and r.provisoria and not r.selecionavel
    assert r.origem_classificacao == "agravante_por_palavra_chave" and r.pendencia == "confirmacao_estruturada_do_agravante"


def test_m8_texto_livre_nunca_sobe_acima_de_media_e_confirmacao_estruturada_consolida():
    so_texto = m8(sinais_textuais={"curso_dagua": True, "rejeito": True, "vitimas_ou_comunidade": True, "risco_estrutural": True})
    assert so_texto.nivel == "MEDIA"
    confirmado = m8(confirmados={"atingiu_curso_agua": True}, sinais_textuais={"curso_dagua": True})
    assert confirmado.nivel == "ALTA" and not confirmado.provisoria and confirmado.selecionavel


def test_m8_provisorio_com_vinculo_provavel_continua_media():
    r = m8(faixa_vinculo="provavel", sinais_textuais={"curso_dagua": True, "rejeito": True})
    assert r.nivel == "MEDIA" and r.provisoria and "vinculo_provavel" in r.motivos


def test_m8_nao_avaliavel_continua_estado_proprio_sem_prioridade():
    r = m8(status_processamento="falha_extracao", motivo_falha="limite de 200 requisicoes por rodada", tem_evidencia=False)
    assert r.nivel == c.ESTADO_NAO_AVALIAVEL and r.prioridade is None and not r.selecionavel and r.nivel != "ROTINA"


def test_selecionar_exclui_provisorio_sem_evidencia_e_ja_analisado():
    base = cand("a", "MEDIA", "C", 50, 10)
    prov = dict(cand("b", "ALTA", "B", 75, 10), provisoria=True)
    sem_ev = dict(cand("c", "ALTA", "B", 75, 10), evidencia_suficiente=False)
    ja_ia = dict(cand("d", "CRITICO", "A", 100, 10), ja_analisado_ia=True)
    esc = c.selecionar([base, prov, sem_ev, ja_ia], PAR)["escolhidos"]
    assert [x["id_evento"] for x in esc] == ["a"]


def test_bloqueios_vazios_so_para_caso_consolidado_com_evidencia():
    ok = m9a("CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL", data="2026-05-05", ev=True)
    assert ok.bloqueios == [] and ok.selecionavel
    baixa = m9a("AUT PESQ/TRANSF DIREITOS-CESSÃO TOTAL PROTOC", data="2026-05-05", ev=True)
    assert baixa.bloqueios == ["abaixo_do_piso"]


def test_estados_fora_da_escala_estao_nos_parametros_e_sem_prioridade():
    assert set(PAR["estados_fora_da_escala"]) == set(c.ESTADOS_FORA_DA_ESCALA)
    for e in c.ESTADOS_FORA_DA_ESCALA:
        assert PAR["prioridade_derivada"][e] is None
    assert not (set(c.ESTADOS_FORA_DA_ESCALA) & set(PAR["piso_selecao"]))


def test_prorrogacao_lavra_tres_cenarios_sem_ambiguidade_na_regra():
    t = "AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA- 01 ANO PUBL"
    antiga = m9a(t, data="2013-05-09", titular="VALE S.A.", subst="MINÉRIO DE FERRO", area=900)
    recente = m9a(t, data="2026-06-01")
    pedido = m9a("AUT PESQ/PRORROGAÇÃO PRAZO REQ LAVRA- 01 ANO PROTOC", data="2026-06-01")
    assert antiga.objeto == recente.objeto == pedido.objeto == "prorrogacao_prazo_requerer_lavra"
    assert (antiga.nivel, recente.nivel, pedido.nivel) == ("BAIXA", "MEDIA", "BAIXA")


def test_objetos_propostos_desativados_por_padrao_e_ativados_so_por_parametro():
    t = "CONC LAV/MODIFICAÇÃO DE PAE APROVADO PUBL"
    off = m9a(t, data="2026-08-01", titular="ANGLOGOLD ASHANTI", area=700)
    par2 = copy.deepcopy(PAR)
    par2["m9a"]["usar_objetos_propostos"] = True
    on = m9a(t, data="2026-08-01", titular="ANGLOGOLD ASHANTI", area=700, par=par2)
    assert PAR["m9a"]["usar_objetos_propostos"] is False
    assert off.objeto == "outro" and off.nivel == "BAIXA"
    assert on.objeto == "plano_aproveitamento_economico" and on.nivel == "MEDIA"


def test_objeto_proposto_pedido_continua_baixa_e_recurso_nao_conhecido_baixa():
    par2 = copy.deepcopy(PAR)
    par2["m9a"]["usar_objetos_propostos"] = True
    ped = m9a("REQ PESQ/RECURSO PROTOC", data="2026-08-01", titular="VALE", par=par2)
    nao = m9a("NÃO CONHECE RECONSIDERAÇÃO / RECURSO PUBL", data="2026-08-01", titular="VALE", par=par2)
    assert ped.nivel == "BAIXA" and nao.nivel == "BAIXA" and nao.objeto == "recurso_decisao"


def test_selecao_parametrizada_somente_novos():
    sel = PAR["selecao"]
    assert sel["somente_novos"] is True and sel["exclui_provisoria"] is True and sel["exclui_ja_analisado_ia"] is True
    assert set(sel["status_editorial_novos"]) == {"em_apuracao", "pendente"}

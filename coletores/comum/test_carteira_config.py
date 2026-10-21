import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carteira_config as c


class Res:
    def __init__(self, data):
        self.data, self.error = data, None


class Query:
    def __init__(self, sb, table):
        self.sb, self.name, self.filters = sb, table, []
    def select(self, *_): return self
    def eq(self, key, val):
        self.filters.append((key, val)); return self
    def execute(self):
        rows = self.sb.tables.get(self.name, [])
        return Res([r for r in rows if all(r.get(k) == v for k, v in self.filters)])


class SB:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return Query(self, name)


def banco(**overrides):
    tables = {
        "carteiras": [{"id": "C1", "empresa_id": "E1", "ativa": True,
                       "nome": "Mineração", "banda_a_min": 80,
                       "banda_b_min": 60, "banda_c_min": 40,
                       "criterio_regra": {"tipo_evento": "contaminação"}}],
        "carteira_fontes": [{"empresa_id": "E1", "carteira_id": "C1",
                             "source_id": "S1", "finalidade": "ambos",
                             "usar_varredura_inicial": True}],
        "carteira_pesos": [{"empresa_id": "E1", "carteira_id": "C1",
                            "componente": "dano_risco", "peso": 2}],
        "sources": [{"id": "S1", "empresa_id": "E1", "ativa": True,
                     "url_base": "https://gov.example/lista", "url_secundaria": None,
                     "metodo_captura": "html"}],
    }
    tables.update(overrides)
    return SB(tables)


class TestCarteiraConfig(unittest.TestCase):
    def config(self, sb=None):
        return c.carregar(sb or banco(), empresa_id="E1", carteira_id="C1", source_id="S1")

    def test_carrega_configuracao_vinculada_e_aplica_bandas(self):
        cfg = self.config()
        self.assertEqual(cfg["bandas"], {"A": 80.0, "B": 60.0, "C": 40.0})
        self.assertEqual(c.prioridade_por_score(79.9, cfg), "B")
        self.assertEqual(c.prioridade_por_score(39.9, cfg), "D")

    def test_falha_fechado_para_fonte_sem_vinculo_de_coleta(self):
        sb = banco(carteira_fontes=[])
        with self.assertRaises(c.ErroCarteira): self.config(sb)

    def test_falha_fechado_para_carteira_inativa_e_bandas_invalidas(self):
        tables = banco().tables
        tables["carteiras"][0]["ativa"] = False
        with self.assertRaises(c.ErroCarteira): self.config(SB(tables))
        tables["carteiras"][0].update(ativa=True, banda_a_min=50, banda_b_min=60)
        with self.assertRaises(c.ErroCarteira): self.config(SB(tables))

    def test_criterio_exige_todos_os_campos_sem_apagar_registros(self):
        cfg = self.config()
        self.assertEqual(c.criterios_atendidos({"tipo_evento": "CONTAMINAÇÃO"}, cfg), (True, []))
        self.assertEqual(c.criterios_atendidos({"tipo_evento": "licenciamento"}, cfg),
                         (False, ["tipo_evento"]))
        self.assertEqual(c.criterios_atendidos({}, cfg), (False, ["tipo_evento"]))

    def test_pesos_usam_componentes_0_100_e_sinalizam_os_nao_mapeados(self):
        cfg = self.config()
        score, ausentes = c.score_ponderado(70, {"dano_risco": 90}, cfg)
        self.assertEqual(score, 90)
        self.assertEqual(ausentes, [])
        score, ausentes = c.score_ponderado(70, {"score_dano_risco": 90}, cfg)
        self.assertEqual(score, 90)  # alias exato usado pela interface
        self.assertEqual(ausentes, [])
        score, ausentes = c.score_ponderado(70, {}, cfg)
        self.assertEqual(score, 70)
        self.assertEqual(ausentes, ["dano_risco"])

    def test_nao_usa_score_parcial_quando_um_peso_configurado_falta(self):
        cfg = self.config()
        cfg["pesos"] = [
            {"componente": "dano_risco", "peso": 2},
            {"componente": "score_valor_financeiro", "peso": 1},
        ]
        score, ausentes = c.score_ponderado(70, {"dano_risco": 100}, cfg)
        self.assertEqual(score, 70)
        self.assertEqual(ausentes, ["score_valor_financeiro"])


if __name__ == "__main__":
    unittest.main()

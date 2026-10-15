"""Recálculo automático (CRIT-V1.2): evidência/tipo oficial entram -> mesma régua -> nova versão, histórico preservado."""
import json
import os
import re
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criticidade as c
import criticidade_db as db
import recalcular_criticidade as rc

HOJE = date(2026, 10, 14)
PAR = c.carregar_parametros()
ANGLO = {"id": "E1", "id_evento": "anm-m9a-anglogold-decaimento-000334-1973", "empresa": "ANGLOGOLD ASHANTI CORREGO DO SITIO MINERACAO S.A.",
         "empresa_id": None, "municipio": "Sabará", "data_evento": "2026-05-05", "tipo_evento": "Procedimento de decaimento de concessão",
         "decisao": "Instauração de processo administrativo de decaimento", "atividade": "Mineração de ouro",
         "palavras_chave": "ouro; decaimento", "titulo_fato": "ANM instaura decaimento", "impacto_dimensionado": "1.852,42 ha"}


def ev(campo, trecho, sup=False):
    return {"campo_sustentado": campo, "trecho_literal": trecho, "superseded": sup}


class TestReclassificacao(unittest.TestCase):
    def test_sem_evidencia_fica_potencial_critico_provisorio(self):
        r = rc.reclassificar_m9a(ANGLO, [], PAR, HOJE)
        self.assertEqual(r.nivel, c.ESTADO_POTENCIAL_CRITICO)
        self.assertTrue(r.provisoria)
        self.assertFalse(r.selecionavel)

    def test_com_evidencia_mas_sem_tipo_oficial_continua_provisorio_e_nao_selecionavel(self):
        r = rc.reclassificar_m9a(ANGLO, [ev("titular", "ANGLOGOLD ASHANTI")], PAR, HOJE)
        self.assertEqual(r.nivel, "CRITICO")
        self.assertTrue(r.provisoria)
        self.assertFalse(r.selecionavel)

    def test_com_tipo_oficial_vira_definitiva_pela_mesma_regua(self):
        evid = [ev("descricao_tipo_evento", "CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL"), ev("titular", "ANGLOGOLD ASHANTI"),
                ev("substancia", "MINÉRIO DE OURO"), ev("area_ha", "1852.42")]
        r = rc.reclassificar_m9a(ANGLO, evid, PAR, HOJE)
        self.assertEqual((r.nivel, r.prioridade, r.provisoria, r.origem_classificacao), ("CRITICO", "A", False, "tipo_oficial"))
        self.assertTrue(r.selecionavel)
        self.assertEqual(r.versao_regra, "CRIT-V1.2")

    def test_evidencia_superseded_nao_conta(self):
        r = rc.reclassificar_m9a(ANGLO, [ev("titular", "X", sup=True)], PAR, HOJE)
        self.assertEqual(r.nivel, c.ESTADO_POTENCIAL_CRITICO)


class _SB:  # banco falso mínimo para criticidade_db.gravar_criticidade
    def __init__(self, rows):
        self.rows = rows

    class _Q:
        def __init__(self, sb, op=None, payload=None):
            self.sb, self.op, self.payload, self.f = sb, op, payload, {}

        def select(self, *_):
            return self

        def eq(self, k, v):
            self.f[k] = v
            return self

        def update(self, p):
            self.op, self.payload = "u", p
            return self

        def insert(self, p):
            self.op, self.payload = "i", p
            return self

        def execute(self):
            m = [r for r in self.sb.rows if all(r.get(k) == v for k, v in self.f.items())]
            if self.op == "i":
                self.sb.rows.append(dict(self.payload, id=len(self.sb.rows) + 1))
            elif self.op == "u":
                for r in m:
                    r.update(self.payload)
            return type("R", (), {"data": m if self.op is None else None})()

    def table(self, _):
        return _SB._Q(self)


class _Fonte:
    def __init__(self, evidencias):
        self._ev = evidencias

    def pendentes(self):
        return [{"event_id": "E1"}]

    def evento(self, _):
        return ANGLO

    def evidencias(self, _):
        return self._ev


class TestRecalculoGrava(unittest.TestCase):
    def test_historico_preservado_e_idempotente(self):
        pend = rc.reclassificar_m9a(ANGLO, [], PAR, HOJE)
        sb = _SB([])
        db.gravar_criticidade(sb, "E1", pend)
        self.assertEqual(len(sb.rows), 1)
        evid = [ev("descricao_tipo_evento", "CONC LAV/DECAIMENTO CONCESSÃO LAVRA INSTAURADO PUBL"), ev("titular", "ANGLOGOLD ASHANTI"),
                ev("substancia", "MINÉRIO DE OURO"), ev("area_ha", "1852.42")]
        r1 = rc.recalcular_pendentes(sb, PAR, HOJE, fonte=_Fonte(evid))
        self.assertEqual(r1["gravados"], 1)
        self.assertEqual(len(sb.rows), 2)
        self.assertFalse(sb.rows[0]["vigente"])
        self.assertEqual(sb.rows[0]["componentes"]["criticidade"], c.ESTADO_POTENCIAL_CRITICO)  # linha antiga preservada
        self.assertTrue(sb.rows[1]["vigente"])
        self.assertEqual(sb.rows[1]["componentes"]["criticidade"], "CRITICO")
        r2 = rc.recalcular_pendentes(sb, PAR, HOJE, fonte=_Fonte(evid))
        self.assertEqual((r2["gravados"], r2["inalterados"]), (0, 1))
        self.assertEqual(len(sb.rows), 2)


class TestSqlEspelhaParametros(unittest.TestCase):
    def test_seed_da_migracao_e_igual_ao_json(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "supabase", "migrations_pendentes",
                            "20261014_criticidade_crit_v1.sql")
        if not os.path.exists(base):
            self.skipTest("migração pendente não está na árvore")
        sql = open(base, encoding="utf-8").read()
        m = re.search(r"\$json\$(.*?)\$json\$", sql, flags=re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1)), PAR)

    def test_portao_do_servidor_bloqueia_provisoria_pendente_e_nao_avaliavel(self):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "supabase", "migrations_pendentes",
                            "20261014_criticidade_crit_v1.sql")
        if not os.path.exists(base):
            self.skipTest("migração pendente não está na árvore")
        sql = open(base, encoding="utf-8").read()
        for flag in ("classificacao_provisoria", "pendente_de_evidencia", "nao_avaliavel", "evidencia_insuficiente", "bloqueado_por_falta_de_documento"):
            self.assertIn(flag, sql)
        self.assertIn("status_editorial_novos", sql)


if __name__ == "__main__":
    unittest.main()

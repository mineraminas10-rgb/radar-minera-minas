"""Paridade Python x SQL da regra dos quatro grupos de seleção (CRIT-V1.2).

Só roda quando CRIT_PG_PSQL aponta para um comando psql de um banco de TESTE onde a migração
20261014_criticidade_crit_v1.sql já foi aplicada (nunca produção). Exemplo:
    CRIT_PG_PSQL="psql -h /tmp/pgdata -p 54329 -U pgtest -d crit_t" python -m pytest test_sql_grupo_paridade.py
Sem a variável, o teste é ignorado. Compara as 3.584 combinações de entrada da função
public.criticidade_grupo_selecao_calc com criticidade.grupo_selecao."""
import itertools
import json
import os
import shlex
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import criticidade as c

PSQL = os.environ.get("CRIT_PG_PSQL")
PAR = c.carregar_parametros()
NIVEIS = ["NAO_AVALIAVEL", "POTENCIAL_CRITICO_PENDENTE_EVIDENCIA", "POTENCIAL_ALTA_PENDENTE_EVIDENCIA", "CRITICO", "ALTA", "MEDIA", "BAIXA", "ROTINA"]
STATUS = ["em_apuracao", "pendente", "liberado_para_pre_release", "descartado", "publicado", "novo", None]


def q(v):
    return "null" if v is None else "'" + str(v).replace("'", "''") + "'"


@unittest.skipUnless(PSQL, "CRIT_PG_PSQL não definido (teste de banco de TESTE)")
class TestParidadeSql(unittest.TestCase):
    def test_todas_as_combinacoes(self):
        combos = list(itertools.product(NIVEIS, [True, False], [True, False], [True, False], [False, True], STATUS, [True, False]))
        valores = ",".join(f"({i},{q(n)},{str(av).lower()},{str(ev).lower()},{str(pv).lower()},"
                           f"{'$$[\"x\"]$$' if bl else '$$[]$$'}::jsonb,{q(st)},{str(ia).lower()})"
                           for i, (n, av, ev, pv, bl, st, ia) in enumerate(combos))
        sql = (f"with t(i,crit,av,ev,pv,bl,st,ia) as (values {valores}) "
               f"select i, public.criticidade_grupo_selecao_calc(crit,av,ev,pv,bl,st,ia,$${json.dumps(PAR)}$$::jsonb) from t order by i")
        out = subprocess.run(shlex.split(PSQL) + ["-At", "-F", ";", "-v", "ON_ERROR_STOP=1"], input=sql, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        sql_res = {int(l.split(";")[0]): l.split(";")[1].split("|")[0] for l in out.stdout.strip().splitlines()}
        divergentes = []
        for i, (n, av, ev, pv, bl, st, ia) in enumerate(combos):
            res = c.ResultadoCriticidade("M9A", n, None, 0.0, 10, avaliavel=av, evidencia_suficiente=ev, provisoria=pv,
                                         bloqueios=["x"] if bl else [], motivos=["m"])
            py, _ = c.grupo_selecao(res, PAR, st, ia)
            if py != sql_res[i]:
                divergentes.append((combos[i], py, sql_res[i]))
        self.assertEqual(len(sql_res), len(combos))
        self.assertEqual(divergentes[:5], [], f"{len(divergentes)} divergências")


if __name__ == "__main__":
    unittest.main()

import unittest
import pre_ia as p


class TestMotivos(unittest.TestCase):
    def test_ordem_igual_ao_gate_do_servidor(self):
        # lê o gate.ts e confere que a lista de campos é a mesma, na mesma ordem
        import re, pathlib
        ts = (pathlib.Path(__file__).resolve().parents[2] / "supabase/functions/_shared/gate.ts").read_text(encoding="utf-8")
        trecho = ts[ts.index("const ORDEM"):ts.index("export interface GateEntrada")]
        campos = re.findall(r"\['(\w+)', '\w+'\]", trecho)
        self.assertEqual(tuple(campos), p.CAMPOS_PRE_IA)

    def test_sem_flags_e_elegivel(self):
        self.assertIsNone(p.motivo_de_dispensa({}))

    def test_flag_desconhecida_e_recusada(self):
        with self.assertRaises(ValueError):
            p.motivo_de_dispensa({"inventado": True})

    def test_primeiro_motivo_na_ordem(self):
        self.assertEqual(p.motivo_de_dispensa({"fora_de_escopo": True, "registro_identico": True}), "registro_identico")


class TestM8(unittest.TestCase):
    def f(self, **k):
        base = dict(extracao_falhou=False, faixa_vinculo="provavel", hash_documento="h1", hash_documento_anterior=None)
        base.update(k)
        return p.flags_m8(**base)

    def test_documento_identico_zero_ia(self):
        self.assertEqual(p.motivo_de_dispensa(self.f(hash_documento_anterior="h1")), "registro_identico")

    def test_documento_alterado_pode_seguir(self):
        self.assertIsNone(p.motivo_de_dispensa(self.f(hash_documento_anterior="h0")))

    def test_ja_processado_zero_ia(self):
        self.assertEqual(p.motivo_de_dispensa(self.f(ja_processado=True)), "enriquecimento_ja_concluido")

    def test_falha_de_extracao_nao_pede_ia_para_inventar(self):
        self.assertEqual(p.motivo_de_dispensa(self.f(extracao_falhou=True, faixa_vinculo="contextual")), "bloqueado_por_falta_de_documento")

    def test_nao_minerario_e_descartado_zero_ia(self):
        self.assertEqual(p.motivo_de_dispensa(self.f(faixa_vinculo="descartado")), "descartado_por_regra_deterministica")

    def test_so_provavel_confirmado_ou_ambiguo_elegivel(self):
        self.assertIsNone(p.motivo_de_dispensa(self.f(faixa_vinculo="provavel")))
        self.assertIsNone(p.motivo_de_dispensa(self.f(faixa_vinculo="confirmado")))
        self.assertEqual(p.motivo_de_dispensa(self.f(faixa_vinculo="contextual")), "descartado_por_regra_deterministica")
        self.assertIsNone(p.motivo_de_dispensa(self.f(faixa_vinculo="contextual", caso_ambiguo_elegivel=True)))
        self.assertEqual(p.motivo_de_dispensa(self.f(faixa_vinculo="qualquer")), "descartado_por_regra_deterministica")


class TestM9A(unittest.TestCase):
    def test_famílias_excluídas_fora_de_escopo(self):
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9a(fora_do_recorte=True)), "fora_de_escopo")

    def test_ato_generico(self):
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9a(ato_generico_nao_material=True)), "descartado_por_regra_deterministica")

    def test_republicacao_literal(self):
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9a(republicacao_literal=True)), "republicacao_literal")

    def test_consolidado_sem_delta(self):
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9a(caso_sem_delta=True)), "continuidade_sem_mudanca_material")

    def test_so_mudanca_material_segue(self):
        self.assertIsNone(p.motivo_de_dispensa(p.flags_m9a()))


class TestM9B(unittest.TestCase):
    def test_regras(self):
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9b(hash_estado_identico=True, delta_relevante=True)), "registro_identico")
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9b(continuidade_sem_delta=True)), "continuidade_sem_mudanca_material")
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9b(apenas_ausencia_simples=True, delta_relevante=True)), "descartado_por_regra_deterministica")
        self.assertEqual(p.motivo_de_dispensa(p.flags_m9b()), "continuidade_sem_mudanca_material")
        self.assertIsNone(p.motivo_de_dispensa(p.flags_m9b(delta_relevante=True)))


class TestContador(unittest.TestCase):
    def test_metricas(self):
        c = p.ContadorPreIa()
        c.registrar({"registro_identico": True}); c.registrar({"fora_de_escopo": True}); c.registrar({})
        r = c.resumo()
        self.assertEqual(r["pre_ia_coletados"], 3); self.assertEqual(r["pre_ia_dispensados"], 2)
        self.assertEqual(r["pre_ia_elegiveis"], 1); self.assertEqual(r["chamadas_ia"], 0); self.assertEqual(r["chamadas_ia_evitadas"], 2)


if __name__ == "__main__":
    unittest.main()

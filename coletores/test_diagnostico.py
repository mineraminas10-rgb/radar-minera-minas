import unittest
import base64, json
import diagnostico as d


def jwt(role):
    h = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
    return f"{h}.{p}.assinatura"


class TestChave(unittest.TestCase):
    def test_tipos(self):
        self.assertEqual(d.classificar_chave(None), "vazia")
        self.assertEqual(d.classificar_chave("  "), "vazia")
        self.assertEqual(d.classificar_chave("sb_secret_abc"), "sb_secret")
        self.assertEqual(d.classificar_chave("sb_publishable_abc"), "sb_publishable")
        self.assertEqual(d.classificar_chave(jwt("service_role")), "jwt_service_role")
        self.assertEqual(d.classificar_chave(jwt("anon")), "jwt_anon")
        self.assertEqual(d.classificar_chave("qualquer-coisa"), "desconhecido")

    def test_ambiente_ok_e_nunca_vaza_valor(self):
        r = d.checar_ambiente({"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_SEGREDO123"})
        self.assertNotIn("SEGREDO123", json.dumps(r))
        self.assertIn("sb_secret", r["SUPABASE_SERVICE_ROLE_KEY"])

    def test_ambiente_ausente(self):
        with self.assertRaises(d.ErroEtapa) as c:
            d.checar_ambiente({"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""})
        self.assertIn("SUPABASE_URL", str(c.exception))
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", str(c.exception))

    def test_chave_publica_recusada(self):
        for k in (jwt("anon"), "sb_publishable_x"):
            with self.assertRaises(d.ErroEtapa):
                d.checar_ambiente({"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": k})

    def test_url_invalida(self):
        with self.assertRaises(d.ErroEtapa):
            d.checar_ambiente({"SUPABASE_URL": "http://localhost", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_x"})


class TestEtapas(unittest.TestCase):
    def test_etapa_falha_vira_erroetapa_com_nome(self):
        saidas = []
        e = d.Etapas("X", saida=saidas.append)
        with self.assertRaises(d.ErroEtapa) as c:
            with e.etapa("baixar"):
                raise ValueError("boom")
        self.assertEqual(c.exception.etapa, "baixar")
        self.assertIn("ValueError: boom", c.exception.causa)
        self.assertFalse(e.registro[0]["ok"])
        self.assertTrue(any("FALHOU" in s for s in saidas))

    def test_etapa_ok(self):
        e = d.Etapas("X", saida=lambda s: None)
        with e.etapa("a"):
            pass
        self.assertTrue(e.registro[0]["ok"])
        self.assertIn("| a | ok |", e.markdown())


if __name__ == "__main__":
    unittest.main()

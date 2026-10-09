"""Escopo de coleta: empresa + carteira + fonte. Banco falso em memória, sem rede."""
import unittest
import escopo

URL = "https://exemplo.gov/fonte"


class Q:
    def __init__(self, linhas): self.linhas, self.f = linhas, []
    def select(self, *a, **k): return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def limit(self, n): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [x for x in self.linhas if all(x.get(c) == v for c, v in self.f)]; return r


class SB:
    def __init__(self, **t): self.t = t
    def table(self, n): return Q(self.t.get(n, []))


A, B, CA, CB, CA2 = "emp-a", "emp-b", "cart-a", "cart-b", "cart-a2"


class TestEscopo(unittest.TestCase):
    def mundo(self, duas_empresas=False, vinculos=None):
        fontes = [{"id": "s-a", "empresa_id": A, "url_base": URL}]
        if duas_empresas: fontes.append({"id": "s-b", "empresa_id": B, "url_base": URL})
        return SB(sources=fontes, carteiras=[{"id": CA, "empresa_id": A}, {"id": CB, "empresa_id": B}, {"id": CA2, "empresa_id": A}],
                  carteira_fontes=vinculos if vinculos is not None else [{"carteira_id": CA, "source_id": "s-a", "empresa_id": A}])

    def test_fonte_unica_e_carteira_unica_resolvem_sozinhas(self):
        self.assertEqual(escopo.resolver_escopo(self.mundo(), URL), {"id": "s-a", "empresa_id": A, "carteira_id": CA})

    def test_fonte_em_duas_empresas_exige_empresa_explicita(self):
        with self.assertRaises(escopo.EscopoInvalido) as c: escopo.resolver_escopo(self.mundo(True), URL)
        self.assertIn("RADAR_EMPRESA_ID", str(c.exception))
        r = escopo.resolver_escopo(self.mundo(True, [{"carteira_id": CB, "source_id": "s-b", "empresa_id": B}]), URL, empresa_id=B.upper())
        self.assertEqual((r["id"], r["empresa_id"], r["carteira_id"]), ("s-b", B, CB))

    def test_carteira_de_outra_empresa_e_barrada(self):
        with self.assertRaises(escopo.EscopoInvalido) as c: escopo.resolver_escopo(self.mundo(True), URL, empresa_id=A, carteira_id=CB)
        self.assertIn("outra empresa", str(c.exception))

    def test_carteira_inexistente_e_barrada(self):
        with self.assertRaises(escopo.EscopoInvalido): escopo.resolver_escopo(self.mundo(), URL, carteira_id="nao-existe")

    def test_varias_carteiras_ou_nenhuma_exigem_escolha_explicita(self):
        dois = [{"carteira_id": CA, "source_id": "s-a", "empresa_id": A}, {"carteira_id": CA2, "source_id": "s-a", "empresa_id": A}]
        with self.assertRaises(escopo.EscopoInvalido): escopo.resolver_escopo(self.mundo(vinculos=dois), URL)
        self.assertEqual(escopo.resolver_escopo(self.mundo(vinculos=dois), URL, carteira_id=CA2)["carteira_id"], CA2)
        with self.assertRaises(escopo.EscopoInvalido): escopo.resolver_escopo(self.mundo(vinculos=[]), URL)

    def test_vinculo_de_carteira_de_outra_empresa_nao_conta(self):
        # a fonte s-a é da empresa A; um vínculo com empresa_id B não pode ser usado
        with self.assertRaises(escopo.EscopoInvalido):
            escopo.resolver_escopo(self.mundo(vinculos=[{"carteira_id": CB, "source_id": "s-a", "empresa_id": B}]), URL)

    def test_fonte_ausente_ou_sem_empresa(self):
        with self.assertRaises(escopo.EscopoInvalido): escopo.resolver_escopo(SB(sources=[]), URL)
        with self.assertRaises(escopo.EscopoInvalido): escopo.resolver_escopo(SB(sources=[{"id": "s", "empresa_id": None, "url_base": URL}]), URL)

    def test_empresa_vazia_do_ambiente_conta_como_ausente(self):
        self.assertEqual(escopo.resolver_escopo(self.mundo(), URL, empresa_id="  ", carteira_id="")["empresa_id"], A)


if __name__ == "__main__":
    unittest.main()

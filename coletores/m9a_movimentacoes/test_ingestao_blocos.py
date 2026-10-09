"""Leitura em blocos do SCM == leitura completa em memória (mesmo recorte), com um dump sintético."""
import os, random, tempfile, unittest
import pandas as pd
import ingestao_scm as ing


def escrever(d, nome, linhas):
    cab = ";".join(ing.COLUNAS_POR_ARQUIVO[nome])
    with open(os.path.join(d, nome), "w", encoding="latin-1", newline="") as f:
        f.write(cab + "\n")
        for l in linhas:
            f.write(";".join(l) + "\n")


def dump_sintetico(d, n_eventos=120, seed=7):
    rnd = random.Random(seed)
    escrever(d, "Evento.txt", [["1", "Protocolo de requerimento"], ["2", "Guia de utilização"], ["3", "Auto de infração lavrado"],
                               ["4", "Barragem - alteração"], ["5", "Alvará de pesquisa"], ["6", "Fiscalização realizada"]])
    procs = [f"83{i}.000/2020" for i in range(1, 9)]
    escrever(d, "Processo.txt", [[p, "1", "2020", "1", "n", "1", "1", "1", "1", "2020-01-01", "2020-01-01", "12,5"] for p in procs])
    escrever(d, "Municipio.txt", [["1", "Itabira", "MG"], ["2", "Santos", "SP"], ["3", "Mariana", "MG"]])
    # P1,P2: MG; P3: SP; P4: MG+SP; P5: sem município; P6..8: MG
    pm = {procs[0]: ["1"], procs[1]: ["3"], procs[2]: ["2"], procs[3]: ["1", "2"], procs[5]: ["3"], procs[6]: ["1"], procs[7]: ["3"]}
    escrever(d, "ProcessoMunicipio.txt", [[p, m] for p, ms in pm.items() for m in ms])
    escrever(d, "Substancia.txt", [["1", "Ouro"], ["2", "Ferro"]])
    escrever(d, "ProcessoSubstancia.txt", [[p, "1" if i % 2 else "2", "1", "", "2020-01-01", ""] for i, p in enumerate(procs)])
    escrever(d, "Pessoa.txt", [["1", "11111111000111", "J", "Mineradora A"], ["2", "22222222000122", "J", "Mineradora B"]])
    escrever(d, "ProcessoPessoa.txt", [[p, "1" if i % 2 else "2", "1", "", "", "", "2020-01-01", ""] for i, p in enumerate(procs)])
    ev = []
    for k in range(n_eventos):
        ev.append([rnd.choice(procs), str(rnd.randint(1, 6)), f"2026-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}", f"obs {k}", "" if k % 3 else f"DOU {k}"])
    escrever(d, "ProcessoEvento.txt", ev)
    return ev


def normaliza(df):
    return df.sort_values(["processo", "id_tipo_evento", "data_evento", "evento_tipo"]).reset_index(drop=True)


class TestBlocos(unittest.TestCase):
    def test_equivalencia_com_leitura_completa(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            ref = ing.aplicar_recorte_m9a(ing.carregar_microdados_scm(d))
            for bloco in (1, 7, 50, 10_000):
                got, est = ing.carregar_recorte_m9a_em_blocos(d, tamanho_bloco=bloco)
                pd.testing.assert_frame_equal(normaliza(ref), normaliza(got), check_dtype=False)
                self.assertEqual(est["brutos"], 120)
                self.assertEqual(est["dentro_recorte"], len(ref))
                self.assertEqual(est["brutos"] - est["fora_de_mg"] - est["fora_por_familia"], est["dentro_recorte"])
            self.assertGreater(len(ref), 0)
            self.assertLess(len(ref), 120)

    def test_recorte_nao_traz_famílias_excluidas_nem_fora_de_mg(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            got, _ = ing.carregar_recorte_m9a_em_blocos(d, tamanho_bloco=13)
            self.assertFalse(got["descricao_tipo_evento"].fillna("").str.contains("Auto de infra|Barragem|Fiscaliza").any())
            self.assertTrue((got["uf_mg"] == True).all())  # noqa: E712

    def test_modo_amostra_limita_linhas_lidas(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            got, est = ing.carregar_recorte_m9a_em_blocos(d, tamanho_bloco=10, max_linhas_evento=25)
            self.assertEqual(est["brutos"], 25)
            self.assertTrue(est["amostra"])
            full, _ = ing.carregar_recorte_m9a_em_blocos(d, tamanho_bloco=10)
            self.assertLess(len(got), len(full))

    def test_recorte_vazio_devolve_dataframe_com_colunas(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d, n_eventos=0)
            got, est = ing.carregar_recorte_m9a_em_blocos(d)
            self.assertEqual(len(got), 0)
            self.assertIn("processo", got.columns)

    def test_layout_mudou_numero_de_colunas_falha_claro(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            with open(os.path.join(d, "Evento.txt"), "w", encoding="latin-1") as f:
                f.write("IDEvento;DSEvento;NOVA\n1;x;y\n")
            with self.assertRaises(ValueError) as c:
                ing.carregar_recorte_m9a_em_blocos(d)
            self.assertIn("Evento.txt", str(c.exception))

    def test_arquivo_ausente_falha_claro(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            os.remove(os.path.join(d, "Pessoa.txt"))
            with self.assertRaises(FileNotFoundError):
                ing.carregar_recorte_m9a_em_blocos(d)

    def test_nome_de_coluna_diferente_vira_aviso(self):
        with tempfile.TemporaryDirectory() as d:
            dump_sintetico(d)
            with open(os.path.join(d, "Evento.txt"), "w", encoding="latin-1") as f:
                f.write("Id;Nome\n1;Protocolo\n")
            _, est = ing.carregar_recorte_m9a_em_blocos(d)
            self.assertTrue(any("Evento.txt" in a for a in est["avisos_cabecalho"]))


if __name__ == "__main__":
    unittest.main()

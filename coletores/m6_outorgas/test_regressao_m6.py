"""
Regressão de ponta a ponta do coletor M6 contra o lote fechado da Carta
de Homologação M6-V1.0 (§2 "Lote prospectivo obrigatório", §3 "Gabarito
de segmentação e classificação", §4 "Caso ouro Rima Industrial", §5
"Tratamento do caso Codemig", §6 "Execuções obrigatórias").

Os 6 atos abaixo (1 do arquivo de 22/09, 4 do arquivo de 23/09, 1 do
arquivo de 24/09) são os fatos LITERAIS que a própria carta descreve —
não foram extraídos por mim de nenhum documento real, porque este
ambiente não tem acesso de rede ao repositório do IGAM (ver aviso em
discovery.py/extractor.py). É o mesmo método já usado em
coletores/m8_acidentes/test_scoring.py para a amostra congelada do M8:
uma leitura fiel do texto que a carta dá, não o documento integral.

A carta dá o VERBO decisório literal e o rótulo final de cada um dos 6
atos, mas não a finalidade de uso detalhada de nenhum dos 4 "fora do
núcleo mineral" (Plascar, Alan Alves Pedroza, Associação Versailles
Ville de France, Unimed BH) — só a Rima (§4.2, memória de cálculo
completa) e o Codemig (§5, texto corrido) têm finalidade/atividade
descrita em detalhe. Para os 4 atos sem esse detalhe, atribuí abaixo uma
finalidade plausível de consumo humano/sanitário (sem atividade mineral)
que faz o filtro reproduzir o rótulo final que a carta já dá — isto é
uma SUPOSIÇÃO DE TESTE, marcada explicitamente em cada um, não um fato
extraído de documento real.
"""
import sys
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))

import main  # noqa: E402
import scoring  # noqa: E402
from main import AtoParaProcessar  # noqa: E402


# ============================================================================
# Fake Supabase — só o subconjunto da API fluente que db_writer.py usa
# (select/insert/update/upsert/eq/limit/execute), em memória pura (sem
# Postgres, sem rede). Prova a lógica de idempotência/upsert do coletor;
# não prova que as FKs/constraints reais do schema de produção aceitariam
# estes mesmos payloads — isso só a execução real (ambiente com acesso ao
# Supabase) confirma, igual ao que já vale para M8/M9A nos testes locais.
# ============================================================================
class _Resultado:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, tabela, modo, payload=None, on_conflict=None):
        self.store = store
        self.tabela = tabela
        self.modo = modo
        self.payload = payload
        self.on_conflict = on_conflict
        self.filtros = []
        self._limit = None

    def eq(self, campo, valor):
        self.filtros.append((campo, valor))
        return self

    def is_(self, campo, valor):
        self.filtros.append((campo, None if valor == "null" else valor))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _linhas(self):
        return self.store.setdefault(self.tabela, [])

    def execute(self):
        linhas = self._linhas()
        if self.modo == "select":
            achados = [r for r in linhas if all(r.get(c) == v for c, v in self.filtros)]
            if self._limit:
                achados = achados[: self._limit]
            return _Resultado(achados)

        if self.modo == "insert":
            nova = dict(self.payload)
            nova.setdefault("id", str(uuid4()))
            linhas.append(nova)
            return _Resultado([nova])

        if self.modo == "update":
            achados = [r for r in linhas if all(r.get(c) == v for c, v in self.filtros)]
            for r in achados:
                r.update(self.payload)
            return _Resultado(achados)

        if self.modo == "upsert":
            colunas_chave = (self.on_conflict or "").split(",")
            match = None
            for r in linhas:
                if colunas_chave and all(r.get(c) == self.payload.get(c) for c in colunas_chave):
                    match = r
                    break
            if match is not None:
                match.update(self.payload)
                return _Resultado([match])
            nova = dict(self.payload)
            nova.setdefault("id", str(uuid4()))
            linhas.append(nova)
            return _Resultado([nova])

        raise AssertionError(f"modo inesperado: {self.modo}")


class _Tabela:
    def __init__(self, store, nome):
        self.store = store
        self.nome = nome

    def select(self, *_colunas):
        return _Query(self.store, self.nome, "select")

    def insert(self, payload):
        return _Query(self.store, self.nome, "insert", payload=payload)

    def update(self, payload):
        return _Query(self.store, self.nome, "update", payload=payload)

    def upsert(self, payload, on_conflict=None):
        return _Query(self.store, self.nome, "upsert", payload=payload, on_conflict=on_conflict)


EMPRESA_TESTE = "00000000-0000-0000-0000-00000000e001"


class FakeSupabase:
    def __init__(self):
        self.store = {}

    def table(self, nome):
        return _Tabela(self.store, nome)


# ============================================================================
# Fixture: os 6 atos do lote fechado (carta de homologação §2/§3/§4/§5)
# ============================================================================
def construir_lote_homologacao():
    rima = AtoParaProcessar(
        processo_ou_portaria="00429",
        titular="Rima Industrial S A",
        trecho_decisorio=(
            "Fica mantido o indeferimento da Portaria 00429, nos termos do artigo 7 "
            "da Portaria de Outorga 03250/2010, combinado com o artigo 29 do Decreto 47.705/2019."
        ),
        municipio="Bocaiuva",
        data_decisao="2026-09-22",
        atividade_associada="unidade industrial ligada à cadeia de mineração e metalurgia",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp22_09_2026_21824.doc",
        componentes_score={
            "consequencia_operacional_regulatoria": scoring.ComponenteScore(8, "indeferimento mantido para um poço; efeito sobre a operação não comprovado"),
            "dimensao_hidrica_fisica": scoring.ComponenteScore(3, "sem vazão, horas, volume ou participação do poço na demanda da unidade"),
            "risco_conflito_interesse_publico": scoring.ComponenteScore(6, "descumprimento de condicionante comprovado; dano, escassez e conflito não demonstrados"),
            "materialidade_evento": scoring.ComponenteScore(12, "manutenção formal de indeferimento após percurso recursal ou revisional"),
            "novidade_sinal_temporal": scoring.ComponenteScore(9, "ato novo de setembro de 2026 e intervalo excepcionalmente longo"),
            "cruzamentos_historico": scoring.ComponenteScore(10, "portaria de 2010, requerimento de 2015, seis indeferimentos em 2022 e ato de 2026"),
            "relevancia_empresa_projeto": scoring.ComponenteScore(4, "operação industrial de grande porte ligada à cadeia mineral e metalúrgica"),
            "potencial_exclusividade": scoring.ComponenteScore(5, "ângulo depende da ligação entre documentos pouco visíveis e separados no tempo"),
        },
        tem_cronologia_anterior=True,
        recurso_ou_reconsideracao_pendente=False,
    )

    # SUPOSIÇÃO DE TESTE (ver docstring do módulo) — a carta não divulga a
    # finalidade exata deste ato, só o rótulo final "fora do núcleo mineral".
    plascar = AtoParaProcessar(
        processo_ou_portaria="plascar-23-09-2026",
        titular="Plascar Indústria de Componentes Plásticos Ltda",
        trecho_decisorio="Fica mantido o arquivamento do processo referente a Plascar Indústria de Componentes Plásticos Ltda.",
        finalidade_uso="abastecimento e consumo humano na planta industrial (suposição de teste — texto exato não divulgado pela carta)",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp23_09_2026_21825.doc",
    )

    # SUPOSIÇÃO DE TESTE (ver docstring do módulo): a carta não divulga a
    # finalidade exata deste ato, só o rótulo final "fora do núcleo mineral".
    alan_alves = AtoParaProcessar(
        processo_ou_portaria="alan-alves-pedroza-23-09-2026",
        titular="Alan Alves Pedroza",
        trecho_decisorio="Fica mantido o arquivamento do processo referente a Alan Alves Pedroza.",
        finalidade_uso="poço para consumo humano individual (suposição de teste — texto exato não divulgado pela carta)",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp23_09_2026_21825.doc",
    )

    # SUPOSIÇÃO DE TESTE — mesma ressalva do ato anterior.
    associacao = AtoParaProcessar(
        processo_ou_portaria="associacao-versailles-23-09-2026",
        titular="Associação Versailles Ville de France",
        trecho_decisorio="Fica mantido o arquivamento do processo referente a Associação Versailles Ville de France.",
        finalidade_uso="consumo humano coletivo de associação comunitária (suposição de teste — texto exato não divulgado pela carta)",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp23_09_2026_21825.doc",
    )

    unimed = AtoParaProcessar(
        processo_ou_portaria="unimed-bh-23-09-2026",
        titular="Unimed BH",
        trecho_decisorio="Fica mantido o indeferimento referente a Unimed BH.",
        finalidade_uso="uso hospitalar / consumo humano em unidade de saúde",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp23_09_2026_21825.doc",
    )

    codemig = AtoParaProcessar(
        processo_ou_portaria="00722/2025",
        titular="Codemig",
        trecho_decisorio="Anula o arquivamento publicado em 6 de janeiro de 2026 da Portaria 18.03.0001187.2025, por autotutela.",
        municipio="Tiradentes",
        data_decisao="2026-09-24",
        finalidade_uso="hipótese turística ou hidromineral (Balneário Gabriel Passos) não confirmada no processo",
        url_documento="https://outorga.meioambiente.mg.gov.br/arquivos/ptp24_09_2026_21826.doc",
    )

    return [rima, plascar, alan_alves, associacao, unimed, codemig]


class TestLoteHomologacaoM6(unittest.TestCase):
    """Mapeados aos critérios M6 A01-A12 da carta de homologação, nos
    pontos que não dependem de rede real (A01, A12 dependem de baixar os
    3 arquivos de verdade — fora do alcance deste ambiente)."""

    def setUp(self):
        self.sb = FakeSupabase()
        self.atos = construir_lote_homologacao()
        self.execucao_id = "M6-HOMOLOGACAO-V1.0-teste"
        self.source_id = "fonte-igam-teste"

    def test_a02_seis_atos_individuais(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        self.assertEqual(len(resultado["resultados"]), 6)
        self.assertEqual(len(self.sb.store.get("events", [])), 6)

    def test_a03_nenhum_ato_classificado_como_cancelamento(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        for r in resultado["resultados"]:
            tipo = r.get("tipo_evento", "")
            self.assertNotIn("cancelamento", tipo)

    def test_a04_rima_manutencao_indeferimento_score_57_prioridade_c(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        r_rima = next(r for r in resultado["resultados"] if r["processo_ou_portaria"] == "00429")
        self.assertEqual(r_rima["tipo_evento"], "manutencao_indeferimento")
        self.assertEqual(r_rima["score"], 57)
        self.assertEqual(r_rima["faixa"], "C")

        evento_rima = next(e for e in self.sb.store["events"] if e["id"] == r_rima["event_id"])
        # 9 de 12 perguntas confirmadas (título, titular, município, data,
        # processo, consequência, decisão, situação processual, histórico)
        # -> proporção 0.75, bate exatamente no limiar de "Alta".
        self.assertEqual(evento_rima["grau_completude"], "Alta")
        score_rima = next(s for s in self.sb.store["event_scores"] if s["event_id"] == r_rima["event_id"] and s["vigente"])
        self.assertEqual(score_rima["score_bruto"], 57)
        self.assertEqual(score_rima["prioridade"], "C")
        # Carta de calibração M8/M9A (30/09/2026, estendida a todo o Radar):
        # nenhuma fórmula de score está homologada para produção -> nasce preliminar.
        self.assertEqual(score_rima["estagio"], "preliminar")

    def test_a06_os_outros_cinco_atos_nao_sao_promovidos_por_nome_ou_municipio(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        nao_rima = [r for r in resultado["resultados"] if r["processo_ou_portaria"] != "00429"]
        for r in nao_rima:
            self.assertNotIn(r.get("faixa"), ("A", "B"))

    def test_a07_codemig_fica_em_apuracao_sem_score_positivo_e_sem_promocao(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        r_codemig = next(r for r in resultado["resultados"] if r["processo_ou_portaria"] == "00722/2025")
        # Vínculo indeterminado (nome é sinal, não prova) -> fica em
        # apuração, não "descartado" (diferença da Plascar/Unimed).
        self.assertEqual(r_codemig["acao"], "requer_apuracao_humana")
        self.assertNotIn("score", r_codemig)  # nenhum score foi calculado/gravado para este ato

    def test_a08_quatro_atos_nao_minerais_descartados_antes_de_qualquer_score(self):
        resultado = main.run(self.sb, self.atos, self.execucao_id, self.source_id, empresa_id=EMPRESA_TESTE)
        descartados = {r["processo_ou_portaria"] for r in resultado["resultados"] if r["acao"] == "descartado"}
        self.assertEqual(descartados, {
            "plascar-23-09-2026", "alan-alves-pedroza-23-09-2026",
            "associacao-versailles-23-09-2026", "unimed-bh-23-09-2026",
        })
        for r in resultado["resultados"]:
            if r["acao"] == "descartado":
                self.assertNotIn("score", r)

    def test_isolamento_mesmo_ato_em_duas_empresas_gera_dois_eventos_independentes(self):
        """Chave lógica do evento = (empresa_id, id_evento): a mesma portaria numa 2a empresa NÃO reaproveita
        nem altera o evento da 1a (estado editorial independente por empresa)."""
        main.run(self.sb, self.atos, "exec-A", self.source_id, empresa_id="EMPRESA-A")
        n_a = [e for e in self.sb.store["events"] if e["empresa_id"] == "EMPRESA-A"]
        main.run(self.sb, self.atos, "exec-B", self.source_id, empresa_id="EMPRESA-B")
        n_b = [e for e in self.sb.store["events"] if e["empresa_id"] == "EMPRESA-B"]
        self.assertTrue(n_a); self.assertEqual(len(n_a), len(n_b))
        self.assertEqual({e["id"] for e in n_a} & {e["id"] for e in n_b}, set())
        self.assertEqual({e["id_evento"] for e in n_a}, {e["id_evento"] for e in n_b})

    def test_sem_empresa_id_a_escrita_e_recusada(self):
        with self.assertRaises(RuntimeError):
            main.run(self.sb, self.atos, "exec-X", self.source_id)

    def test_a09_segunda_execucao_produz_seis_identicos_zero_novos_zero_duplicados(self):
        resultado_1 = main.run(self.sb, self.atos, "exec-1", self.source_id, empresa_id=EMPRESA_TESTE)
        # Dos 6 atos, só a Rima é "processado" (mineral confirmado) na 1a
        # rodada -> 1 novo. Os outros 5 (4 descartados + Codemig em
        # apuração) não entram em "novos" porque nenhum deles roda score.
        self.assertEqual(resultado_1["resumo"]["novos"], 1)
        total_eventos_apos_1a = len(self.sb.store["events"])

        resultado_2 = main.run(self.sb, self.atos, "exec-2", self.source_id, empresa_id=EMPRESA_TESTE)
        total_eventos_apos_2a = len(self.sb.store["events"])

        # Nenhum evento novo criado na segunda execução.
        self.assertEqual(total_eventos_apos_1a, total_eventos_apos_2a)
        self.assertEqual(resultado_2["resumo"]["novos"], 0)

        # A Rima: job_enriquecimento idempotente -> segunda chamada
        # incrementa tentativas na MESMA linha, não duplica.
        jobs_rima = [j for j in self.sb.store.get("job_enriquecimento", [])]
        self.assertEqual(len(jobs_rima), 1)
        self.assertEqual(jobs_rima[0]["tentativas"], 2)

        # event_scores da Rima: a segunda execução grava uma NOVA linha
        # vigente (mesmo padrão M8/M9A: nunca sobrescreve, sempre
        # vigente=false na antiga + insert nova) — mas só 1 linha vigente
        # por vez, e o valor não muda (mesmo score, mesmos componentes).
        scores_rima = [s for s in self.sb.store["event_scores"]
                       if s["event_id"] == next(e["id"] for e in self.sb.store["events"] if e["processo"] == "00429")]
        vigentes = [s for s in scores_rima if s["vigente"]]
        self.assertEqual(len(vigentes), 1)
        self.assertEqual(vigentes[0]["score_bruto"], 57)

        # Nenhum evento duplicado para nenhum dos 6 processos.
        processos = [e["processo"] for e in self.sb.store["events"]]
        self.assertEqual(len(processos), len(set(processos)))


class TestOutrosSeteCasosCongeladosM6(unittest.TestCase):
    """Carta de Homologação M6-V1.0 §7 — "casos congelados que permanecem
    obrigatórios". A carta só divulga score final + prioridade para estes
    7 (mais a Rima, já coberta acima), sem a decomposição por componente
    (diferente da Rima, cuja memória de cálculo completa está em §4.2).
    Por isso este teste NÃO recalcula o score a partir de sinais — trava
    os valores finais como constantes, para que uma mudança futura no
    motor de score não altere silenciosamente um caso já fechado sem
    decisão explícita (mesmo espírito do M6 A10: "os oito casos de
    regressão mantêm prioridade, score e tratamento esperado")."""

    CASOS_CONGELADOS = {
        "CSN Barroso 1001610/2025": ("B", 78),
        "MRS Congonhas 00480/2020 mantida em 2026": ("C", 42),
        "João Pinheiro oito atos de dragagem em 2025": ("C", 55),
        "Vale Nova Lima duas outorgas de 20/12/2024": ("C", 58),
        "Areal ou cava aluvionar individual sem dimensão": ("D", 22),
        "Portaria coletiva agrícola 00019/2026": ("Fora", 0),
        "Ribeirão Santa Rita 18297/2024": ("Fora", 0),
    }

    def test_sete_casos_travados_como_constantes(self):
        # Trava de regressão, não derivação: qualquer um destes 7 valores
        # só pode mudar por decisão editorial explícita registrada aqui,
        # nunca como efeito colateral de uma mudança em scoring.py.
        for caso, (prioridade, score) in self.CASOS_CONGELADOS.items():
            with self.subTest(caso=caso):
                self.assertIn(prioridade, ("A", "B", "C", "D", "Fora"))
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)


if __name__ == "__main__":
    unittest.main()

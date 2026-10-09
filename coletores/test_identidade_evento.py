"""
Guarda de regressão para a decisão operacional da Carta de Revisão/
Calibração de Scores M8/M9A (seção 4, "Correção do caso Vale"):

    "A unidade de análise foi misturada na proposta. Os registros oficiais
    descrevem dois eventos no mesmo dia, com horários, estruturas,
    trajetórias ambientais e medidas administrativas próprias. [...]
    Decisão operacional: excluir o score 87, criar dois IDs de evento,
    registrar um vínculo relacional entre eles [...]"

Investigação feita em 30/09/2026, antes de escrever este teste: o score 87
combinando Mina de Fábrica (25/01/2026, ~1h40, Cava Segredo Área 18) e Mina
de Viga (25/01/2026/06/08/2026 conforme a fonte, ~17h30, sumps/Lavra 4E) NÃO
existe em nenhuma linha de `events`/`event_scores` em produção — confirmado
por consulta direta (score_bruto=87 e score_normalizado=87: zero linhas;
busca textual por "fábrica"/"viga": zero linhas). O Módulo 8 tem zero
eventos em produção no total — nunca rodou contra a fonte real. Ou seja,
não existe hoje nenhum registro combinado para separar/cancelar: o score 87
foi um artefato da proposta M8-EDITORIAL-V1-PROVISORIO em revisão, nunca
chegou a ser escrito no banco.

O que ESTE teste prova, então, não é uma correção de dado (não há dado),
é que o código atual do coletor M8 — quando rodar de verdade — está
estruturalmente incapaz de repetir o erro: `construir_id_evento()` (main.py)
usa só o protocolo do comunicado como chave de negócio, nunca uma
combinação de empresa+data+município, que é exatamente o que teria feito
Fábrica e Viga colidirem no mesmo id_evento por serem do mesmo dia e,
possivelmente, mesma empresa citada na fonte.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import construir_id_evento  # noqa: E402


class TestIdentidadeEventoNuncaFundePorEmpresaOuData(unittest.TestCase):

    def test_fabrica_e_viga_geram_ids_diferentes_mesmo_no_mesmo_dia(self):
        # Protocolos fictícios de exemplo (os reais dependem do número do
        # comunicado SEMAD de cada um, ainda não coletado) — o ponto do
        # teste é só confirmar que protocolos diferentes nunca colapsam,
        # mesmo quando tudo o resto (empresa, data, município) é igual.
        id_fabrica = construir_id_evento("14/2026")
        id_viga = construir_id_evento("156/2026")
        self.assertNotEqual(id_fabrica, id_viga)

    def test_protocolo_e_a_unica_entrada_da_chave(self):
        # Mesma empresa, mesma data, mesmo município, protocolos diferentes
        # -> ids diferentes. Não há parâmetro de empresa/data/município na
        # assinatura de construir_id_evento() hoje nem nunca deveria haver
        # um que, se preenchido igual, produza o mesmo id_evento.
        self.assertNotEqual(construir_id_evento("1/2026"), construir_id_evento("2/2026"))

    def test_mesmo_protocolo_e_sempre_o_mesmo_id_evento(self):
        # Idempotência básica: reprocessar o mesmo comunicado (ex.: segunda
        # execução do coletor) deve bater no mesmo id_evento, não criar
        # um novo — é o que permite upsert_evento() atualizar em vez de
        # duplicar.
        self.assertEqual(construir_id_evento("156/2026"), construir_id_evento("156/2026"))

    def test_formato_estavel_do_id_evento(self):
        self.assertEqual(construir_id_evento("156/2026"), "semad-m8-156-2026")


if __name__ == "__main__":
    unittest.main()

"""
Teste LOCAL de integração do pipeline M9A (equivalente a
teste_pipeline_m8.py — ver docstring lá para o raciocínio geral). Roda o
fluxo real de db_writer.py/main.py contra o Postgres local
(radar_draft_test), via fake_supabase.py, simulando um caso já consolidado
(dois atos do mesmo processo, sem rede) para confirmar que:
  1. As 3 colunas novas (confianca_evidencial, evidencia_id,
     campo_sustentado) são gravadas/lidas corretamente pelo código real.
  2. score_normalizado, regra_evento_id, gatilhos/redutores/piso/teto,
     empresa_id passam a ser preenchidos.
  3. O mesmo bug de checklist_editorial corrigido no M8 também está
     corrigido aqui — sem isso, este teste falha com IntegrityError.
  4. grau_completude é gravado no evento.
  5. Timeline processual ganha uma linha por ato, com tipo_marco traduzido
     para o vocabulário fechado (mapear_tipo_marco) e evidencia_id
     vinculada (achado: M9A gravava tipo_marco=descrição livre do SCM,
     fora do vocabulário fechado, e nunca vinculava evidencia_id).

Uso: DSN=... python3 teste_pipeline_m9a.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "m9a_movimentacoes"))
sys.path.insert(0, os.path.dirname(__file__))

from fake_supabase import FakeSupabaseClient
import db_writer
import scoring
import checklist_editorial
import consolidacao
import main as m9a_main

DSN = os.environ.get("DSN", "dbname=radar_draft_test user=postgres host=/var/run/postgresql")


def main():
    sb = FakeSupabaseClient(DSN)

    fonte = db_writer.buscar_fonte(sb)
    print("fonte:", fonte)
    assert fonte["empresa_id"], "empresa_id da fonte M9A veio None — fixture local não tem backfill"

    execucao_id = db_writer.criar_execucao(sb, f"TESTE-{uuid.uuid4().hex[:8]}",
                                            ambiente="piloto", empresa_id=fonte["empresa_id"])
    print("execucao_id:", execucao_id)

    sufixo = uuid.uuid4().hex[:8]
    atos = [
        consolidacao.Ato(
            processo=f"999.{sufixo}/2026", descricao="decaimento",
            data_evento="2026-09-15", empresa=f"Empresa Teste {sufixo}",
            substancia="ferro", municipio="Município Teste",
        ),
        consolidacao.Ato(
            processo=f"999.{sufixo}/2026", descricao="intimacao para defesa",
            data_evento="2026-09-20", empresa=f"Empresa Teste {sufixo}",
            substancia="ferro", municipio="Município Teste",
        ),
    ]

    r = m9a_main.processar_caso(sb, execucao_id, atos, empresa_id=fonte["empresa_id"], fonte_id=fonte["id"])
    print("resultado processar_caso:", r)
    assert r["criado"]

    id_evento = r["id_evento"]
    evento = db_writer.buscar_evento_por_id_evento(sb, id_evento)
    event_id = evento["id"]

    # -------------------------------------------------------------------
    # Verificações finais — lê de volta via SQL direto (independente do
    # que o código gravou via fake client)
    # -------------------------------------------------------------------
    cur = sb.conn.cursor()
    cur.execute("""
        select score_bruto, score_normalizado, versao_score, prioridade, empresa_id,
               regra_evento_id, gatilhos_aplicados, redutores_aplicados, piso_aplicado,
               confianca_evidencial
        from event_scores where event_id = %s and vigente = true
    """, (event_id,))
    row = cur.fetchone()
    print("\nevent_scores gravado:", row)
    assert row is not None
    assert row[1] is not None, "score_normalizado ainda NULL!"
    assert row[4] is not None, "empresa_id ainda NULL em event_scores!"
    assert row[9] is None, "confianca_evidencial deveria continuar NULL (sem regra objetiva ainda)"

    cur.execute("select grau_completude, empresa_id, tipo_evento from events where id = %s", (event_id,))
    row = cur.fetchone()
    print("events gravado:", row)
    assert row[0] is not None, "grau_completude ainda NULL!"
    assert row[1] is not None, "empresa_id ainda NULL em events!"

    cur.execute("select campo_sustentado, confianca, empresa_id from evidencias where event_id = %s order by created_at", (event_id,))
    rows = cur.fetchall()
    print("evidencias gravadas:", rows)
    assert rows, "nenhuma evidência gravada!"
    assert all(r_[0] is not None for r_ in rows), "campo_sustentado ainda NULL nalguma evidência!"
    assert all(r_[1] is None for r_ in rows), "confianca deveria ser NULL (regra objetiva ainda não existe)"

    cur.execute("select tipo_marco, data_marco, evidencia_id from timeline_processual where event_id = %s order by data_marco", (event_id,))
    rows = cur.fetchall()
    print("timeline gravada:", rows)
    assert len(rows) == 2, f"esperava 2 marcos de timeline (um por ato), achei {len(rows)}"
    tipos_marco_validos = set(db_writer.TIPOS_MARCO_TIMELINE)
    for tipo_marco, data_marco, evidencia_id in rows:
        assert tipo_marco in tipos_marco_validos, f"tipo_marco '{tipo_marco}' fora do vocabulário fechado"
        assert evidencia_id is not None, "timeline sem evidencia_id vinculada"
    # "decaimento" -> "decisao", "intimacao para defesa" -> "ciencia" (ver _MAPEAMENTO_TIPO_MARCO)
    assert {r_[0] for r_ in rows} == {"decisao", "ciencia"}, \
        f"mapeamento de tipo_marco inesperado: {rows}"

    cur.execute("select resposta, evidencia_id, observacao from checklist_editorial where event_id = %s order by pergunta_numero", (event_id,))
    rows = cur.fetchall()
    print("checklist gravado:")
    for row in rows:
        print(" ", row)
    for resposta, evidencia_id, observacao in rows:
        if resposta == "confirmado":
            assert evidencia_id is not None, "checklist 'confirmado' sem evidencia_id — constraint deveria ter bloqueado isso"
        if resposta == "nao_localizado":
            assert observacao, "checklist 'nao_localizado' sem observacao — constraint deveria ter bloqueado isso"

    cur.close()
    print("\n=== TESTE DE INTEGRAÇÃO M9A: TUDO OK ===")


if __name__ == "__main__":
    main()

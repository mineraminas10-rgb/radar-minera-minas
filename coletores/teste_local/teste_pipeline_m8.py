"""
Teste LOCAL de integração do pipeline M8 (não é o pytest existente, que só
testa scoring/signals/checklist em isolamento sem banco). Roda o fluxo real
de db_writer.py/main.py contra o Postgres local (radar_draft_test), via
fake_supabase.py, simulando um item já extraído (sem rede) para confirmar
que:
  1. As 3 colunas novas (confianca_evidencial, evidencia_id,
     campo_sustentado) são gravadas/lidas corretamente pelo código real.
  2. score_normalizado, regra_evento_id, gatilhos/redutores/piso/teto,
     empresa_id passam a ser preenchidos.
  3. O bug de checklist_editorial (chk_confirmado_exige_evidencia) está
     mesmo corrigido — sem isso, este teste falha com IntegrityError.
  4. grau_completude é gravado no evento.
  5. Timeline processual passa a ganhar uma linha (achado: M8 nunca
     gravava nenhuma).

Uso: DSN=... python3 teste_pipeline_m8.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "m8_acidentes"))
sys.path.insert(0, os.path.dirname(__file__))

from fake_supabase import FakeSupabaseClient
import db_writer
import scoring
import checklist_editorial

DSN = os.environ.get("DSN", "dbname=radar_draft_test user=postgres host=/var/run/postgresql")


def main():
    sb = FakeSupabaseClient(DSN)

    fonte = db_writer.buscar_fonte(sb)
    print("fonte:", fonte)
    assert fonte["empresa_id"], "empresa_id da fonte M8 veio None — backfill não aplicado na réplica"

    execucao_id = db_writer.criar_execucao(sb, f"TESTE-{uuid.uuid4().hex[:8]}",
                                            ambiente="piloto", empresa_id=fonte["empresa_id"])
    print("execucao_id:", execucao_id)

    id_evento = f"teste-m8-{uuid.uuid4().hex[:8]}"
    campos_evento = {
        "titulo_fato": "Rompimento de estrutura de contenção em pilha de estéril — teste local",
        "municipio": "Município Teste",
        "status_editorial": "em_apuracao",
        "revisao_humana": "Pendente",
        "url_oficial": "https://exemplo.invalido/comunicado-teste",
        "hash_versao": "hash-teste-0001",
        "tipo_evento": "comunicado_acidente_ambiental",
    }
    event_id, criado = db_writer.upsert_evento(sb, id_evento, campos_evento, execucao_id,
                                                empresa_id=fonte["empresa_id"])
    print("event_id:", event_id, "criado:", criado)
    assert criado

    db_writer.upsert_m8_detalhe(sb, event_id, "999999/2026", 2026, {
        "url_lista": "https://exemplo.invalido/lista",
        "url_detalhe": "https://exemplo.invalido/comunicado-teste",
        "score_vinculo": 9.0,
        "faixa_vinculo": "confirmado",
        "justificativa_vinculo": "teste",
        "status_processamento": "processado",
        "versao_regra_score": scoring.VERSAO_REGRA_SCORE,
    })

    sig_v = scoring.SignaisVinculo(modalidade_mineracao=True, mina_identificada=True, material_mineral=True)
    score_v, faixa_v, just_v = scoring.score_vinculo(sig_v)
    sig_g = scoring.SignaisGravidade(atingiu_ou_pode_atingir_curso_dagua=True, vitimas_evacuacao_bloqueio_ou_risco_comunidade=True)
    score_g, nivel_g = scoring.score_gravidade(sig_g)
    prioridade = {"alerta_imediato": "A", "pauta_apuracao": "B",
                  "registro_acompanhamento": "C", "arquivo_contextual": "D"}[nivel_g]

    regra = db_writer.buscar_regra_evento(sb, fonte["id"], "comunicado_acidente_ambiental")
    print("regra_evento encontrada:", regra)

    memoria_v = scoring.montar_memoria_calculo_vinculo(sig_v, just_v)
    memoria_g = scoring.montar_memoria_calculo_gravidade(sig_g)
    db_writer.gravar_score(
        sb, event_id, score_bruto=score_g, prioridade=prioridade,
        componentes={"score_vinculo": score_v, "faixa_vinculo": faixa_v,
                     "score_gravidade": score_g, "nivel_gravidade": nivel_g},
        empresa_id=fonte["empresa_id"],
        score_normalizado=scoring.calcular_score_normalizado(score_g),
        regra_evento_id=regra["id"] if regra else None,
        regra_evento_versao=regra["versao"] if regra else None,
        gatilhos_aplicados={**memoria_v["gatilhos_aplicados"], **memoria_g["gatilhos_aplicados"]},
        redutores_aplicados=memoria_v["redutores_aplicados"],
        piso_aplicado=memoria_v["piso_aplicado"],
        teto_aplicado=memoria_v["teto_aplicado"],
    )

    documento_id = db_writer.gravar_documento(
        sb, event_id, url="https://exemplo.invalido/comunicado-teste.pdf",
        hash_documento="hash-doc-teste", status="processado", paginas_ocr=2,
        empresa_id=fonte["empresa_id"],
    )
    evidencias_entrada = [
        {"campo": "modalidade_mineracao", "trecho_literal": "modalidade: mineração de ferro", "palavra_gatilho": "mineração"},
        {"campo": "descricao_literal", "trecho_literal": "Houve rompimento parcial de estrutura de contenção...", "palavra_gatilho": None},
    ]
    gravadas = db_writer.gravar_evidencias_campo(sb, event_id, documento_id, evidencias_entrada,
                                                  metodo_extracao="nativo", empresa_id=fonte["empresa_id"])
    print("evidencias gravadas:", gravadas)
    assert len(gravadas) == 2
    evidencia_geral = next(g for g in gravadas if g["campo"] == "descricao_literal")

    db_writer.gravar_marco_timeline(sb, event_id, tipo_marco="documento", data_marco="2026-09-20",
                                     trecho_literal="Comunicado publicado em 20/09/2026",
                                     evidencia_id=evidencia_geral["id"], empresa_id=fonte["empresa_id"])

    respostas = checklist_editorial.derivar_checklist_m8(
        extracao_falhou=False, faixa_vinculo=faixa_v,
        empresa_citada=None, local_descrito="Município Teste", municipio="Município Teste",
        descricao_literal="Houve rompimento parcial de estrutura de contenção...",
        score_gravidade_calculado=True, teve_antecedentes=False,
    )
    respostas_finais = db_writer.gravar_checklist_editorial(
        sb, event_id, respostas, prioridade=prioridade, empresa_id=fonte["empresa_id"],
        evidencia_padrao_id=evidencia_geral["id"],
    )
    print("checklist respostas finais:", respostas_finais)

    grau = checklist_editorial.calcular_grau_completude(respostas)
    print("grau_completude calculado:", grau)
    db_writer.upsert_evento(sb, id_evento, {"grau_completude": grau}, execucao_id, empresa_id=fonte["empresa_id"])

    db_writer.gravar_job_enriquecimento(sb, event_id, hash_entrada="hash-teste-0001", status="concluido",
                                         tempo_gasto_segundos=3.2, empresa_id=fonte["empresa_id"])

    # -------------------------------------------------------------------
    # Verificações finais — lê de volta via SQL direto (não via fake
    # client, para confirmar de forma independente do que o código gravou)
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
    assert all(r[0] is not None for r in rows), "campo_sustentado ainda NULL nalguma evidência!"
    assert all(r[1] is None for r in rows), "confianca deveria ser NULL (regra objetiva ainda não existe)"

    cur.execute("select tipo_marco, data_marco, evidencia_id from timeline_processual where event_id = %s", (event_id,))
    rows = cur.fetchall()
    print("timeline gravada:", rows)
    assert len(rows) == 1, f"esperava 1 marco de timeline, achei {len(rows)}"
    assert rows[0][2] is not None, "timeline sem evidencia_id vinculada"

    cur.execute("select resposta, evidencia_id, observacao from checklist_editorial where event_id = %s order by pergunta_numero", (event_id,))
    rows = cur.fetchall()
    print("checklist gravado:")
    for r in rows:
        print(" ", r)
    for resposta, evidencia_id, observacao in rows:
        if resposta == "confirmado":
            assert evidencia_id is not None, "checklist 'confirmado' sem evidencia_id — constraint deveria ter bloqueado isso"
        if resposta == "nao_localizado":
            assert observacao, "checklist 'nao_localizado' sem observacao — constraint deveria ter bloqueado isso"

    cur.close()
    print("\n=== TESTE DE INTEGRAÇÃO M8: TUDO OK ===")


if __name__ == "__main__":
    main()

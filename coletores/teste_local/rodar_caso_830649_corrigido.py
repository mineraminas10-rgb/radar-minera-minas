"""
Script de uma vez (não é teste automatizado permanente) para rodar o
pipeline M9A CORRIGIDO (28/09/2026 — classificacao_scm.py, area_ha,
agrupamento por instrumento, busca de antecedentes no universo) contra os
dois atos REAIS recuperados do SCM Microdados para o processo
830.649/2020, e imprimir o resultado completo para comparação com o
estado atual de produção e com a rodada anterior (Cenário A/B).

Roda contra a réplica local (radar_draft_test), nunca produção.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "m9a_movimentacoes"))
sys.path.insert(0, os.path.dirname(__file__))

from fake_supabase import FakeSupabaseClient
import db_writer
import consolidacao
import main as m9a_main

DSN = os.environ.get("DSN", "dbname=radar_draft_test user=postgres host=/var/run/postgresql")


def main():
    sb = FakeSupabaseClient(DSN)
    fonte = db_writer.buscar_fonte(sb)
    execucao_id = db_writer.criar_execucao(sb, f"TESTE-830649-{uuid.uuid4().hex[:8]}",
                                            ambiente="auditoria_reprocessamento", empresa_id=fonte["empresa_id"])

    ato_emissao = consolidacao.Ato(
        processo="830.649/2020",
        descricao="AUT PESQ/GUIA UTILIZAÇÃO AUTORIZADA PUBL",  # DSEvento real, Evento.txt IDEvento=285
        data_evento="2023-02-14",
        empresa="AGUAS FERREAS MINERACAO LTDA",
        substancia="MINÉRIO DE FERRO",
        municipio="Rio Casca; São Pedro dos Ferros",
        id_tipo_evento=285,
        texto_narrativo=(
            "Autoriza a emissão de Guia de Utilização 830.649/2020-AGUAS FERREAS MINERACAO LTDA-"
            "RIO CASCA/MG, SÃO PEDRO DOS FERROS/MG - Guia n° 61/2023 - GERÊNCIA REGIONAL/MG-"
            "300.000 toneladas/ano-MINÉRIO DE FERRO (uso: Industrial)- Vigência da Guia:3 ANOS"
        ),
        area_ha=1468.73,
    )
    ato_prorrogacao = consolidacao.Ato(
        processo="830.649/2020",
        descricao="AUT PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL",  # DSEvento real, Evento.txt IDEvento=2325
        data_evento="2026-07-22",
        empresa="AGUAS FERREAS MINERACAO LTDA",
        substancia="MINÉRIO DE FERRO",
        municipio="Rio Casca; São Pedro dos Ferros",
        id_tipo_evento=2325,
        texto_narrativo=(
            "Relação SEÇÃO 1 - GUIA DE UTILIZAÇÃO  GU - 405/2026 - Gerência Regional / MG - "
            "Guia de Utilização do Gerente Regional - COROUT - MG || "
            "Prorroga por 03 (três) anos o prazo de validade da guia de utilização. "
            "830.649/2020-AGUAS FERREAS MINERACAO LTDA-GUIA DE UTILIZAÇÃO N°61/2023 - GERÊNCIA REGIONAL/MG"
        ),
        area_ha=1468.73,
    )

    atos = [ato_emissao, ato_prorrogacao]

    # regra 4b (instrumento) — verificar ANTES de rodar o pipeline que os
    # dois atos realmente caem no mesmo caso, como esperado
    casos = consolidacao.consolidar_atos(atos)
    print(f"Número de casos formados pelos 2 atos reais: {len(casos)} (esperado: 1)")

    # universo_atos = só estes 2 (achado real: busca em ProcessoPessoa.txt
    # completo, feita via device_bash em 28/09/2026, achou 0 outros
    # processos pra este titular — ver relatório)
    resultado = m9a_main.processar_caso(sb, execucao_id, atos, empresa_id=fonte["empresa_id"],
                                         fonte_id=fonte["id"], universo_atos=atos)
    print("\n=== resultado processar_caso ===")
    print(resultado)

    event_id = db_writer.buscar_evento_por_id_evento(sb, resultado["id_evento"])["id"]
    cur = sb.conn.cursor()

    cur.execute("""select score_bruto, score_normalizado, versao_score, prioridade,
                          gatilhos_aplicados, redutores_aplicados, piso_aplicado, teto_aplicado
                   from event_scores where event_id=%s and vigente=true""", (event_id,))
    print("\n=== event_scores ===")
    print(cur.fetchone())

    cur.execute("select grau_completude, empresa_id from events where id=%s", (event_id,))
    print("\n=== events.grau_completude ===")
    print(cur.fetchone())

    cur.execute("""select pergunta_numero, resposta, evidencia_id is not null as tem_evidencia, observacao
                   from checklist_editorial where event_id=%s order by pergunta_numero""", (event_id,))
    print("\n=== checklist_editorial ===")
    for row in cur.fetchall():
        print(" ", row)

    cur.execute("""select tipo_marco, data_marco, trecho_literal, evidencia_id is not null as tem_evidencia
                   from timeline_processual where event_id=%s order by data_marco""", (event_id,))
    print("\n=== timeline_processual ===")
    for row in cur.fetchall():
        print(" ", row)

    cur.execute("select campo_sustentado, trecho_literal from evidencias where event_id=%s order by created_at",
                (event_id,))
    print("\n=== evidencias ===")
    for row in cur.fetchall():
        print(" ", row)

    cur.close()


if __name__ == "__main__":
    main()

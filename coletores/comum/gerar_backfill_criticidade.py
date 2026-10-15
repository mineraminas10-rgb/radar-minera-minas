"""Gera (NÃO aplica) o SQL de backfill CRIT-V1.2 a partir do CSV da simulação. Uso:
   python gerar_backfill_criticidade.py simulacao_criticidade_v1_2.csv saida.sql"""
import csv, json, os, sys

PAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "criticidade_parametros_v1_2.json")


def gerar(csv_path, sql_path, modulos=("M9A",)):
    """`modulos`: por decisão de 14/10/2026 o backfill do M8 só é discutido DEPOIS de reprocessar os casos sem texto,
    então o padrão gera apenas o M9A."""
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"), delimiter=";") if r["modulo"] in modulos]
    par = json.load(open(PAR, encoding="utf-8"))
    vals = []
    for r in rows:
        comp = {"criticidade": r["criticidade"], "prioridade_derivada": r["prioridade_depois"] or None, "pontuacao": float(r["pontuacao"]),
                "idade_dias": int(r["idade_dias"]) if r["idade_dias"] else None, "objeto": r["objeto"], "fase": r["fase"] or None,
                "reforcos": [x for x in r["reforcos"].split("+") if x], "motivos": r["motivos"].split(";") if r["motivos"] else [],
                "avaliavel": r["avaliavel"] == "True", "selecionavel": r["selecionavel"] == "True",
                "origem_classificacao": r["origem_classificacao"], "provisoria": r["provisoria"] == "True",
                "n_evidencias_banco": int(r["n_evidencias_banco"] or 0),
                "nivel_potencial": r["nivel_potencial"] or None, "nivel_antes_idade": r["nivel_antes_idade"] or None,
                "evidencia_suficiente": r["evidencia_suficiente"] == "True", "pendencia": r["pendencia"] or None,
                "bloqueios": [x for x in r["bloqueios"].split("+") if x], "evidencia_usada": r["evidencia_usada"],
                "versao_regra": par["versao_regra"], "versao_parametros": par["versao_parametros"], "modulo": r["modulo"],
                "origem": "backfill_simulacao_2026-10-14"}
        js = json.dumps(comp, ensure_ascii=False).replace("'", "''")
        just = r["motivos"].replace("'", "''")
        prio = f"'{r['prioridade_depois']}'" if r["prioridade_depois"] else "null"
        vals.append(f"('{r['uid']}'::uuid,{prio},{float(r['pontuacao'])},'{js}'::jsonb,'{just}')")
    nl = "\n"
    m8_nota = ("-- Este arquivo grava o ESTADO ATUAL do M8 (inclui NAO_AVALIAVEL): os 153 sem texto continuam bloqueados e serao\n"
               "-- reclassificados por nova versao (historico preservado) depois de corrigir o coletor e recuperar os textos."
               if "M8" in modulos else
               "-- O backfill do M8 NAO esta incluido neste arquivo (ver o arquivo _m8, aplicado so se autorizado).")
    sql = f"""-- =====================================================================================
-- BACKFILL PENDENTE (NAO APLICADO) - CRIT-V1.2 sobre {len(rows)} eventos ({'+'.join(modulos)}), simulacao de 14/10/2026.
{m8_nota}
-- Aplicar SOMENTE apos aprovacao expressa e DEPOIS da migracao 20261014_criticidade_crit_v1.sql.
-- Nao apaga nenhum score: a linha vigente anterior apenas passa a vigente=false (historico preservado).
-- =====================================================================================
begin;
create temporary table _crit_backfill (event_id uuid primary key, prioridade text, pontuacao numeric, componentes jsonb, justificativa text) on commit drop;
insert into _crit_backfill values
{(","+nl).join(vals)};

-- 1) a linha vigente (estagio preliminar) desses eventos deixa de ser vigente; nada e apagado
update public.event_scores s set vigente = false
  from _crit_backfill b
 where s.event_id = b.event_id and s.vigente and s.estagio = 'preliminar' and s.versao_score <> 'CRIT-V1.2';  -- reexecutar nao troca a vigente

-- 2) nova versao CRIT-V1.2 (uma por evento; reexecutar nao duplica)
insert into public.event_scores (event_id, score_bruto, score_normalizado, versao_score, componentes, prioridade,
                                 justificativa_score, vigente, empresa_id, gatilhos_aplicados, redutores_aplicados, estagio)
select b.event_id, b.pontuacao, b.pontuacao, 'CRIT-V1.2', b.componentes, b.prioridade::public.prioridade_editorial,
       b.justificativa, true, e.empresa_id, '{{}}'::jsonb, '{{}}'::jsonb, 'preliminar'
  from _crit_backfill b join public.events e on e.id = b.event_id
 where not exists (select 1 from public.event_scores x where x.event_id = b.event_id and x.versao_score = 'CRIT-V1.2' and x.vigente);

-- 3) trava de seguranca: se nao houver exatamente {len(rows)} linhas CRIT-V1.2 vigentes para estes eventos, a transacao inteira e desfeita
do $$
declare n int;
begin
  select count(*) into n from public.event_scores s join _crit_backfill b on b.event_id = s.event_id
   where s.versao_score = 'CRIT-V1.2' and s.vigente and s.estagio = 'preliminar';
  if n <> {len(rows)} then
    raise exception 'backfill CRIT-V1.2: esperado {len(rows)} linhas vigentes, encontrado % - desfazendo', n;
  end if;
end $$;
commit;

-- Verificacao esperada: {len(rows)} linhas CRIT-V1.2 vigentes.
-- Rollback (so o backfill; o historico legado nunca foi apagado):
--   delete from public.event_scores where versao_score='CRIT-V1.2' and componentes->>'origem'='backfill_simulacao_2026-10-14';
--   depois reativar, por evento, a linha legada mais recente (update ... set vigente=true).
"""
    open(sql_path, "w", encoding="utf-8").write(sql)
    return len(rows)


if __name__ == "__main__":
    mods = tuple(sys.argv[3].split(",")) if len(sys.argv) > 3 else ("M9A",)
    print(gerar(sys.argv[1], sys.argv[2], mods))

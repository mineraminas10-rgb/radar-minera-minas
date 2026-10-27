"""Paridade: o banco (fila_editorial) tem de dar EXATAMENTE o que as regras antigas do index.html (JS) davam, em centenas de cenários."""
import json, os, random, subprocess, sys
tmp, index, host, port = sys.argv[1:5]
env = dict(os.environ, PGHOST=host, PGPORT=port, PGUSER='postgres', PGDATABASE='postgres', PGTZ='UTC', PGOPTIONS='-c client_min_messages=warning')
EMP = '33333333-3333-3333-3333-333333333333'
rnd = random.Random(20261019)
STATUS = ['em_apuracao'] * 6 + ['publicado', 'pronto_para_publicar', 'arquivado', 'descartado', 'novo']
DATAS = ['2024-03-01', '2025-10-10', '2026-06-01', '2026-08-15', '2026-09-30', '2026-10-10', '2026-10-19', None]
CRITS = [None, 'CRITICO', 'POTENCIAL_CRITICO_PENDENTE_EVIDENCIA', 'ALTA', 'POTENCIAL_ALTA_PENDENTE_EVIDENCIA', 'MEDIA', 'BAIXA', 'ROTINA']
VALS = [0, 10, 35, 39, 39.9, 40, 41, 50, 59, 59.9, 60, 61, 70, 79, 79.9, 80, 81, 90, 100]
UPD = [None, None, None, '2026-08-01T00:00:00Z', '2026-09-15T00:00:00Z', '2026-10-15T00:00:00Z', '2026-10-19T12:00:00Z']
cen = []
for n in range(1, 701):
    comp = {}
    crit = rnd.choice(CRITS)
    if crit: comp['criticidade'] = crit
    imp = rnd.choice([None, None, None, 'critico', 'relevante', 'menor'])
    if imp: comp['atualizacao_material'] = {'impacto': imp}
    u = rnd.choice(UPD)
    if u: comp['ultima_atualizacao_material'] = u
    if rnd.random() < 0.15: comp['publicado_antes'] = True
    if rnd.random() < 0.05: comp['ineditismo'] = False
    if rnd.random() < 0.25: comp['reforcos'] = rnd.choice([['x'], []])
    es = rnd.choice([None, None, True, False])
    if es is not None: comp['evidencia_suficiente'] = es
    if rnd.random() < 0.08: comp['pendencias_bloqueantes'] = ['p']
    score = None if rnd.random() < 0.1 else {'estagio': rnd.choice(['final', 'final', 'preliminar', 'preliminar', 'editorial']), 'valor': rnd.choice(VALS)}
    ev = [{'trecho_literal': rnd.choice(['t', None, ''])} for _ in range(rnd.choice([0, 0, 1, 2, 3]))]
    cen.append(dict(id='e3000000-0000-0000-0000-%012d' % n, status=rnd.choice(STATUS), data_evento=rnd.choice(DATAS), created_at='2026-09-01T00:00:00Z',
                    url_oficial=rnd.choice([None, 'http://x']), comp=comp, score=score, evidencias=ev, documentos=[{} for _ in range(rnd.choice([0, 0, 1, 2]))]))
def lit(v): return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"
sql = ["set timezone = 'UTC';"]
for c in cen:
    sql.append("insert into public.events(id, empresa_id, titulo_fato, status_editorial, data_evento, created_at, url_oficial) values (%s, '%s', 'P', %s, %s, %s, %s);"
               % (lit(c['id']), EMP, lit(c['status']), lit(c['data_evento']), lit(c['created_at']), lit(c['url_oficial'])))
    if c['score']:
        s = c['score']
        sql.append("insert into public.event_scores(event_id, vigente, estagio, score_normalizado, score_relevancia, versao_score, componentes, prioridade) values (%s, true, %s, %s, %s, 'V', %s::jsonb, 'B');"
                   % (lit(c['id']), lit(s['estagio']), s['valor'], s['valor'] if s['estagio'] == 'editorial' else 'null', lit(json.dumps(c['comp']))))
    else:
        sql.append("insert into public.event_scores(event_id, vigente, componentes, prioridade) values (%s, true, %s::jsonb, 'B');" % (lit(c['id']), lit(json.dumps(c['comp']))))
    for e in c['evidencias']:
        sql.append("insert into public.evidencias(event_id, trecho_literal) values (%s, %s);" % (lit(c['id']), lit(e['trecho_literal'])))
    for _ in c['documentos']:
        sql.append("insert into public.documentos(event_id, url) values (%s, 'u');" % lit(c['id']))
open(f'{tmp}/cenarios_carga.sql', 'w').write('\n'.join(sql))
subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-f', f'{tmp}/cenarios_carga.sql'], env=env, check=True)
# cenários sem score vigente: o JS recebe vig=null; no SQL há uma linha só com componentes (sem score) — equivalente a "sem score"
for c in cen:
    if not c['score']: c['score'] = None
json.dump(cen, open(f'{tmp}/cenarios.json', 'w'))
q = "set timezone='UTC'; set radar.agora = '2026-10-20T00:00:00Z'; select public.fila_editorial('%s')" % EMP
out = subprocess.run(['psql', '-X', '-At', '-c', q], env=env, check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1]
banco = json.loads(out)
js = json.loads(subprocess.run(['node', os.path.join(os.path.dirname(__file__), 'paridade_js.cjs'), index, f'{tmp}/cenarios.json'], check=True, capture_output=True, text=True).stdout)
erros = []
db = {x['event_id']: x for x in banco}
if len(db) != len(cen): erros.append(f'banco devolveu {len(db)} de {len(cen)} eventos')
for c in cen:
    b, j = db[c['id']], js['saida'][c['id']]
    pe = b['prioridade_editorial']
    got = dict(codigo=pe['codigo'], motivo=pe['motivo'], texto=pe['texto'], aviso=pe['aviso'], inedito=b['ineditismo']['inedito'], atualizado=b['atual']['atualizado'],
               qualidade=b['qualidade_evidencia'], situacao=b['situacao']['codigo'], criticidade=b['criticidade'], decisorio=b['decisao']['score_decisorio'],
               valor=(None if b['decisao']['score_valor'] is None else float(b['decisao']['score_valor'])), material_ts=b['atual']['material_ts'])
    exp = dict(j); exp['valor'] = None if exp['valor'] is None else float(exp['valor'])
    for k in got:
        if got[k] != exp[k]: erros.append(f"{c['id'][-4:]} {k}: banco={got[k]!r} js={exp[k]!r} | {c['status']} {c['data_evento']} {c['comp']} {c['score']}")
ordem_banco = [x['event_id'] for x in sorted(banco, key=lambda x: x['ordem'])]
if ordem_banco != js['ordem']:
    i = next(i for i, (a, b) in enumerate(zip(ordem_banco, js['ordem'])) if a != b)
    erros.append(f'ordem difere na posição {i}: banco={ordem_banco[i][-4:]} js={js["ordem"][i][-4:]}')
dist = {}
for x in banco: dist[x['prioridade_editorial']['codigo']] = dist.get(x['prioridade_editorial']['codigo'], 0) + 1
print('cenários:', len(cen), '| distribuição A/B/C/D/PENDENTE no banco:', dict(sorted(dist.items())))
if erros:
    print('FALHA: %d divergências' % len(erros)); print('\n'.join(erros[:15])); sys.exit(1)
print('OK: banco == regras antigas do index.html em todos os cenários (prioridade, motivo, texto, aviso, ineditismo, atualidade, evidência, situação e ORDEM da fila)')

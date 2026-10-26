"""Prioridade editorial derivada (separada de event_scores.prioridade, que é histórica/CRIT). Supabase SIMULADO, sem rede."""
import pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_operacao_assistida import abrir
from test_fila_editorial import carregar, card, titulos, FINAL, PRELIM, mostrar_todos

EV = [dict(id='e1', trecho_literal='t', resumo_extraido='r')]       # evidência suficiente (qualidade >= 2)

def pe(pg):
    return pg.evaluate("Object.fromEntries(filaData.map(i=>[i.event.titulo_fato, [i.prioridadeEditorial.codigo, i.prioridadeEditorial.motivo]]))")

CASOS = [
    # (titulo, caso, esperado)
    ('ALTA 35 gatilho',        dict(score=FINAL(35), comp=dict(criticidade='ALTA'), prio='B', data='2026-10-10'), 'C'),
    ('CRITICO 35',             dict(score=FINAL(35), comp=dict(criticidade='CRITICO'), prio='A', data='2026-10-10'), 'C'),
    ('CRITICO 90',             dict(score=FINAL(90), comp=dict(criticidade='CRITICO'), prio='A', data='2026-10-10'), 'A'),
    ('CRITICO provisorio 20',  dict(score=PRELIM(20), comp=dict(criticidade='CRITICO'), prio='A', data='2026-10-10'), 'A'),
    ('ALTA 45',                dict(score=FINAL(45), comp=dict(criticidade='ALTA'), prio='B', data='2026-01-01'), 'B'),
    ('ALTA provisorio',        dict(score=PRELIM(70), comp=dict(criticidade='ALTA'), prio='B', data='2026-10-10'), 'PENDENTE'),
    ('MEDIA 45',               dict(score=FINAL(45), comp=dict(criticidade='MEDIA'), prio='C', data='2026-10-10'), 'C'),
    ('MEDIA 70 atual',         dict(score=FINAL(70), comp=dict(criticidade='MEDIA'), prio='C', data='2026-10-10'), 'B'),
    ('MEDIA 70 antigo',        dict(score=FINAL(70), comp=dict(criticidade='MEDIA'), prio='C', data='2025-10-10'), 'C'),
    ('MEDIA 35',               dict(score=FINAL(35), comp=dict(criticidade='MEDIA'), prio='C', data='2026-10-10'), 'D'),
    ('BAIXA 90',               dict(score=FINAL(90), comp=dict(criticidade='BAIXA'), prio='D', data='2026-10-10'), 'D'),
    ('ROTINA 50',              dict(score=FINAL(50), comp=dict(criticidade='ROTINA'), prio='D', data='2026-10-10'), 'D'),
    ('ALTA 85 com evidencia',  dict(score=FINAL(85), comp=dict(criticidade='ALTA'), prio='B', data='2026-10-10', evid=EV), 'A'),
    ('ALTA 85 sem evidencia',  dict(score=FINAL(85), comp=dict(criticidade='ALTA', evidencia_suficiente=False), prio='B', data='2026-10-10', evid=EV), 'B'),
    ('MEDIA 85 sem gatilho',   dict(score=FINAL(85), comp=dict(criticidade='MEDIA'), prio='C', data='2026-10-10', evid=EV), 'B'),
    ('MEDIA 85 reforco',       dict(score=FINAL(85), comp=dict(criticidade='MEDIA', reforcos=['curso_dagua']), prio='C', data='2026-10-10', evid=EV), 'A'),
    ('Atualizacao critica',    dict(score=FINAL(50), comp=dict(criticidade='MEDIA', atualizacao_material=dict(impacto='critico'), ultima_atualizacao_material='2026-10-15T00:00:00Z'), prio='C', data='2026-10-10'), 'A'),
    ('Atualizacao relevante',  dict(score=FINAL(50), comp=dict(criticidade='BAIXA', atualizacao_material=dict(impacto='relevante')), prio='D', data='2026-10-10'), 'B'),
    ('MEDIA provisorio 99',    dict(score=PRELIM(99), comp=dict(criticidade='MEDIA'), prio='C', data='2026-10-10'), 'PENDENTE'),
    ('Sem score',              dict(data='2026-10-10'), 'PENDENTE'),
    ('Sem criticidade 50',     dict(score=FINAL(50), data='2026-10-10'), 'C'),
    ('Sem criticidade 35',     dict(score=FINAL(35), data='2026-10-10'), 'D'),
]

def casos():
    return [dict(k=i + 1, titulo=t, **c) for i, (t, c, _) in enumerate(CASOS)]

def test_regras_da_prioridade_editorial_caso_a_caso():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos()); mostrar_todos(pg, True)
        got = pe(pg)
        erros = {t: (got[t][0], esp) for t, _, esp in CASOS if got[t][0] != esp}
        assert not erros, erros
        br.close()

def test_alta_35_com_gatilho_forte_mostra_C_com_aviso_e_nao_B():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos())
        c = card(pg, 'ALTA 35 gatilho')
        assert c['sit'] == 'SCORE_BAIXO_COM_GATILHO_FORTE'
        assert pg.evaluate("[...document.querySelectorAll('#filaWrap .card')].find(x=>x.querySelector('.titulo').textContent==='ALTA 35 gatilho').querySelector('.ind-prio .prio').textContent") == 'C'
        assert 'Score baixo, mantido por gatilho forte' in c['txt'] and 'AVALIAR' in c['txt']
        assert 'Criticidade' in c['txt'] and 'Alta' in c['txt']
        br.close()

def test_prioridade_historica_do_crit_e_preservada_e_so_aparece_em_detalhes():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos())
        assert pg.evaluate("filaData.find(i=>i.event.titulo_fato==='ALTA 35 gatilho').prioridade") == 'B'    # event_scores.prioridade intacta
        assert pg.evaluate("filaData.find(i=>i.event.titulo_fato==='ALTA 35 gatilho').event.event_scores[0].prioridade") == 'B'
        assert 'Prioridade CRIT (histórica): B' in card(pg, 'ALTA 35 gatilho')['html'].replace('&nbsp;', ' ')
        assert pg.evaluate("window.__updates.length") == 0
        br.close()

def test_provisorio_nao_rebaixa_e_aparece_como_pendente():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos())
        c = card(pg, 'MEDIA provisorio 99')
        assert 'PENDENTE' in c['txt'] and '99 · Provisório' in c['txt']
        assert pe(pg)['CRITICO provisorio 20'][0] == 'A'          # criterio sem score continua valendo
        br.close()

def test_filtro_de_prioridade_usa_a_prioridade_editorial():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos()); mostrar_todos(pg, True)
        def filtra(v):
            pg.evaluate("(v)=>{document.getElementById('fPrioridade').value=v; renderFila();}", v); return set(titulos(pg))
        esperado = lambda cod: {t for t, _, e in CASOS if e == cod}
        assert filtra('C') == esperado('C') and 'ALTA 35 gatilho' in filtra('C') and 'ALTA 35 gatilho' not in filtra('B')   # a B historica nao vale mais
        assert filtra('PENDENTE') == esperado('PENDENTE')
        assert filtra('A') == esperado('A') and filtra('D') == esperado('D')
        assert pg.evaluate("[...document.querySelectorAll('#fPrioridade option')].map(o=>o.value)") == ['', 'A', 'B', 'C', 'D', 'PENDENTE']
        br.close()

def test_ordem_atualizado_prioridade_editorial_criticidade_atualidade_score_evidencia():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [
            dict(k=1, titulo='Alta 35 (C)',         score=FINAL(35), comp=dict(criticidade='ALTA'), data='2026-10-19'),
            dict(k=2, titulo='Media 70 (B)',        score=FINAL(70), comp=dict(criticidade='MEDIA'), data='2026-09-01'),
            dict(k=3, titulo='Critico 90 (A)',      score=FINAL(90), comp=dict(criticidade='CRITICO'), data='2026-01-01'),
            dict(k=4, titulo='Pendente provisorio', score=PRELIM(95), comp=dict(criticidade='MEDIA'), data='2026-10-19'),
            dict(k=5, titulo='Media 35 (D)',        score=FINAL(35), comp=dict(criticidade='MEDIA'), data='2026-10-19'),
            dict(k=6, titulo='Atualizado (C)',      score=FINAL(45), comp=dict(criticidade='MEDIA', ultima_atualizacao_material='2026-10-18T00:00:00Z'), data='2026-02-01'),
            dict(k=7, titulo='Alta 70 (B)',         score=FINAL(70), comp=dict(criticidade='ALTA'), data='2026-08-01'),
        ]); mostrar_todos(pg, True)
        # ATUALIZADO primeiro; A; B (ALTA antes de MEDIA); C; pendente; D
        assert titulos(pg) == ['Atualizado (C)', 'Critico 90 (A)', 'Alta 70 (B)', 'Media 70 (B)', 'Alta 35 (C)', 'Pendente provisorio', 'Media 35 (D)']
        br.close()


# ---- gravidade != urgência: o fato pode ser CRITICO e a prioridade editorial baixa -------------------------------------------
def texto_prio(pg, titulo):
    return pg.evaluate("(t)=>[...document.querySelectorAll('#filaWrap .card')].find(x=>x.querySelector('.titulo').textContent===t).querySelector('.motivoPrio').innerText", titulo)

def test_caso1_acidente_grave_antigo_ja_publicado_sem_novidade_fica_D_e_explica():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Acidente grave antigo', status='publicado', pre='Texto', score=FINAL(90), comp=dict(criticidade='CRITICO'), prio='A', data='2026-02-10', evid=EV)])
        mostrar_todos(pg, True)
        assert pe(pg)['Acidente grave antigo'] == ['D', 'JA_PUBLICADO_SEM_NOVIDADE']
        c = card(pg, 'Acidente grave antigo')
        assert 'Crítico' in c['txt'] and 'Já publicado' in c['txt']                       # criticidade intacta, ineditismo visível
        assert 'motivo: fato antigo, já publicado, sem atualização material recente' in texto_prio(pg, 'Acidente grave antigo')
        assert pg.evaluate("filaData[0].prioridade") == 'A'                               # prioridade CRIT histórica preservada
        br.close()

def test_caso1_com_atualizacao_material_nao_perde_urgencia():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Antigo com novidade', status='publicado', score=FINAL(90), comp=dict(criticidade='CRITICO', atualizacao_material=dict(impacto='relevante')), data='2026-02-10')])
        mostrar_todos(pg, True)
        assert pe(pg)['Antigo com novidade'][0] == 'A'
        br.close()

def test_caso2_criticidade_menor_mas_fato_novo_com_impacto_agora_tem_prioridade_alta():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Decisao nova', score=FINAL(50), comp=dict(criticidade='MEDIA', atualizacao_material=dict(impacto='relevante'), ultima_atualizacao_material='2026-10-19T00:00:00Z'), data='2026-10-19'),
                      dict(k=2, titulo='Critico antigo ja publicado', status='publicado', score=FINAL(90), comp=dict(criticidade='CRITICO'), data='2025-12-01')])
        mostrar_todos(pg, True)
        assert pe(pg)['Decisao nova'][0] == 'B' and pe(pg)['Critico antigo ja publicado'][0] == 'D'
        assert titulos(pg) == ['Decisao nova', 'Critico antigo ja publicado']
        assert 'atualização material relevante' in texto_prio(pg, 'Decisao nova')
        br.close()

def test_ineditismo_antigo_mas_nunca_publicado_mantem_prioridade_com_aviso():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Antigo inedito', score=FINAL(90), comp=dict(criticidade='CRITICO'), data='2026-02-10')])
        assert pe(pg)['Antigo inedito'][0] == 'A'
        c = card(pg, 'Antigo inedito')
        assert 'Inédito' in c['txt'] and 'Fato antigo, mas ainda inédito' in c['txt']
        br.close()

def test_ineditismo_desempata_a_ordem_inedito_antes_de_ja_publicado_e_flag_publicado_antes():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=2, titulo='Ja publicado antes (flag)', score=FINAL(70), comp=dict(criticidade='MEDIA', publicado_antes=True, atualizacao_material=dict(impacto='relevante')), data='2026-10-10'),
                      dict(k=1, titulo='Inedito', score=FINAL(70), comp=dict(criticidade='MEDIA', atualizacao_material=dict(impacto='relevante')), data='2026-10-10')])
        assert pe(pg)['Ja publicado antes (flag)'][0] == 'B' and pe(pg)['Inedito'][0] == 'B'
        assert titulos(pg) == ['Inedito', 'Ja publicado antes (flag)']
        assert 'Já publicado' in card(pg, 'Ja publicado antes (flag)')['txt']
        br.close()

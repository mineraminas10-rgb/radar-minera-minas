"""Fila editorial: decisão de score, corte <40, card, ordenação e travas de publicação. Supabase SIMULADO, sem rede."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_operacao_assistida import abrir, EMP

SETUP = """
(n) => {
  const mk = (c) => ({id:'uuid-'+c.k, id_evento:'ev-'+c.k, titulo_fato:c.titulo || ('Evento '+c.k), resumo_factual:'', empresa:'Empresa T', municipio:'Cidade', fonte_id:null,
     status_editorial:c.status||'em_apuracao', revisao_humana:c.revisao||'Pendente', pre_release:c.pre||null, url_oficial:null,
     data_evento:c.data||null, data_publicacao:null, created_at:c.criado||'2026-10-01T10:00:00Z',
     processo:null, tipo_evento:null, decisao:null, situacao_processual:null, proximo_marco:null, palavras_chave:[], justificativa_editorial:null,
     event_scores: c.score ? [Object.assign({vigente:true, score_bruto:null, score_normalizado:null, score_relevancia:null, componentes:c.comp||null, prioridade:c.prio||null,
                   justificativa_score:'just '+c.k, versao_score:'v-teste', estagio:'preliminar'}, c.score)] : [],
     documentos:[], evidencias:c.evid||[], checklist_editorial:[]});
  window.__consultas = []; window.__updates = [];
  const rows = { events: n.casos.map(mk), sources: [], api_execucoes: [] };
  const b = (t) => { const q = { select(){return q}, eq(){return q}, in(){return q}, not(){return q}, order(){return q}, limit(){return q},
     update(v){ window.__updates.push({t, v}); return q; },
     then(res, rej){ window.__consultas.push(t); return Promise.resolve({data: rows[t]||[], error:null}).then(res, rej); } }; return q; };
  sb = { from: b, auth:{getSession:async()=>({data:{session:null}})}, functions:{invoke:async()=>({data:null,error:{message:'x'}})} };
  agoraMs = () => Date.parse('2026-10-20T00:00:00Z');
  window.pode = (a) => n.master || a === 'editorial';
  clienteSelecionado = '@@EMP@@'; clientesCache = [{id:'@@EMP@@', nome:'Empresa T'}];
  document.getElementById('view-fila').classList.add('active');
}
""".replace("@@EMP@@", EMP)


def carregar(pg, casos, master=False):
    pg.evaluate(SETUP, dict(casos=casos, master=master))
    pg.evaluate("carregarFila()")
    pg.wait_for_function("document.getElementById('filaWrap').children.length > 0 && !/Carregando/.test(document.getElementById('filaWrap').textContent)", timeout=5000)


def titulos(pg):
    return pg.evaluate("[...document.querySelectorAll('#filaWrap .titulo')].map(x=>x.textContent)")

def card(pg, titulo):
    return pg.evaluate("""(t) => { const c=[...document.querySelectorAll('#filaWrap .card')].find(x=>x.querySelector('.titulo').textContent===t);
        return c ? {txt:c.innerText, html:c.innerHTML, sit:c.dataset.situacao,
                    pronto: c.querySelector('[data-action=pronto_para_publicar]') && {dis:c.querySelector('[data-action=pronto_para_publicar]').disabled, txt:c.querySelector('[data-action=pronto_para_publicar]').innerText, title:c.querySelector('[data-action=pronto_para_publicar]').title},
                    pub: c.querySelector('[data-action=publicado]') && {dis:c.querySelector('[data-action=publicado]').disabled}} : null; }""", titulo)

def mostrar_todos(pg, v):
    pg.evaluate("(v)=>{document.getElementById('mostrarTodos').checked=v; renderFila();}", v)

FINAL = lambda v: dict(estagio='final', score_normalizado=v)
PRELIM = lambda v: dict(estagio='preliminar', score_normalizado=v)

# ---- 1) final 35 + MEDIA -> fora da seleção, sem apagar nada ------------------------------------------------------
def test_01_final_35_media_sai_da_fila_padrao_e_aparece_em_mostrar_todos():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Baixo', score=FINAL(35), comp=dict(criticidade='MEDIA')),
                      dict(k=2, titulo='Bom', score=FINAL(70), comp=dict(criticidade='MEDIA'))])
        assert titulos(pg) == ['Bom']
        assert 'fora da seleção (score < 40) oculto' in pg.inner_text('#filterSummary')
        mostrar_todos(pg, True)
        assert set(titulos(pg)) == {'Baixo', 'Bom'}
        c = card(pg, 'Baixo')
        assert c['sit'] == 'FORA_DA_SELECAO'
        assert 'DESCARTADO_POR_SCORE' in c['txt'] and 'SCORE_MENOR_40' in c['txt'] and 'versão v-teste' in c['txt'] and 'estágio final' in c['txt']
        # decisão é derivada na leitura: nenhuma escrita
        assert pg.evaluate("window.__updates.length") == 0
        br.close()

# ---- 2) final 35 + ALTA -> permanece com gatilho forte ---------------------------------------------------------------
def test_02_final_35_alta_permanece_com_gatilho_forte():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Alta baixo', score=FINAL(35), comp=dict(criticidade='ALTA')),
                      dict(k=2, titulo='Critico baixo', score=FINAL(10), comp=dict(criticidade='CRITICO'))])
        assert set(titulos(pg)) == {'Alta baixo', 'Critico baixo'}
        assert card(pg, 'Alta baixo')['sit'] == 'SCORE_BAIXO_COM_GATILHO_FORTE'
        assert 'SCORE_BAIXO_COM_GATILHO_FORTE' in card(pg, 'Critico baixo')['txt']
        br.close()

# ---- 3) preliminar 35 -> mostra 35 PROVISÓRIO, nunca descarta ----------------------------------------------------------
def test_03_preliminar_35_mostra_provisorio_e_nao_descarta():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Prelim', score=PRELIM(35), comp=dict(criticidade='MEDIA'))])
        assert titulos(pg) == ['Prelim']
        c = card(pg, 'Prelim')
        assert c['sit'] == 'SCORE_PROVISORIO'
        assert '35 · Provisório' in c['txt'] and 'PROVISÓRIO' in c['txt']
        assert 'FORA DA SELEÇÃO' not in c['txt'].upper().replace('REF.: FORA DA SELEÇÃO', '')
        br.close()

# ---- 4) sem score -> PENDENTE_DE_SCORE ---------------------------------------------------------------------------------
def test_04_sem_score_fica_pendente_de_score_visivel_e_nao_descartado():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Sem score')])
        assert titulos(pg) == ['Sem score']
        c = card(pg, 'Sem score')
        assert c['sit'] == 'PENDENTE_DE_SCORE' and 'PENDENTE_DE_SCORE' in c['txt']
        br.close()

# ---- 5) score 85 -> Muito forte (e as demais faixas) --------------------------------------------------------------------
def test_05_faixas_do_score_decisorio():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='A', score=FINAL(85)), dict(k=2, titulo='B', score=FINAL(60)), dict(k=3, titulo='C', score=FINAL(40)),
                      dict(k=4, titulo='D', score=dict(score_relevancia=79))])
        assert 'Muito forte' in card(pg, 'A')['txt']
        assert 'Forte' in card(pg, 'B')['txt'] and 'Muito forte' not in card(pg, 'B')['txt']
        assert 'Avaliar' in card(pg, 'C')['txt']
        assert 'Forte' in card(pg, 'D')['txt']       # score_relevancia é decisório (regra 1), mesmo em estágio preliminar
        assert pg.evaluate("[decisaoScore({score_relevancia:79, estagio:'preliminar', score_normalizado:10}).score_valor, faixaScore(39.9), faixaScore(80)]") == [79, 'Fora da seleção', 'Muito forte']
        br.close()

# ---- 6) sem pré-release -> botão bloqueado, com motivo ---------------------------------------------------------------
def test_06_sem_pre_release_bloqueia_pronto_e_publicar_com_motivo_no_botao():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Sem pre', score=FINAL(70))])
        c = card(pg, 'Sem pre')
        assert 'Sem pré-release' in c['txt']
        assert c['pronto']['dis'] is True and 'sem pré-release' in c['pronto']['txt'] and 'sem pré-release' in c['pronto']['title']
        assert c['pub']['dis'] is True
        # mesmo forçando o clique, a função recusa e não escreve
        pg.once("dialog", lambda d: d.accept())
        pg.evaluate("atualizarStatus('uuid-1','pronto_para_publicar')")
        assert pg.evaluate("window.__updates.length") == 0
        br.close()

# ---- 7) com pré-release -> NÃO PUBLICADO até ação humana; aprovar != publicar ----------------------------------------------
def test_07_com_pre_release_continua_nao_publicado_e_publicar_exige_aprovacao_antes():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Com pre', score=FINAL(70), pre='Texto do pré-release', revisao='Revisado'),
                      dict(k=2, titulo='Aprovado', score=FINAL(70), pre='Texto', status='pronto_para_publicar', revisao='Revisado')])
        c = card(pg, 'Com pre')
        assert 'PRÉ-RELEASE · NÃO PUBLICADO' in c['txt'] and 'Texto do pré-release' in c['txt']
        assert c['pronto']['dis'] is False
        assert c['pub']['dis'] is True                      # ainda não aprovado: Aprovar e Publicar são separados
        assert card(pg, 'Aprovado')['pub']['dis'] is False
        assert pg.evaluate("window.__updates.length") == 0  # nada muda sozinho
        br.close()

def test_07b_revisao_humana_pendente_bloqueia_publicar():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Rev pendente', score=FINAL(70), pre='Texto', status='pronto_para_publicar', revisao='Pendente')])
        assert card(pg, 'Rev pendente')['pub']['dis'] is True
        br.close()

def test_07c_score_pendente_so_bloqueia_quando_a_regra_editorial_exigir():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Sem score com pre', pre='Texto')])
        assert card(pg, 'Sem score com pre')['pronto']['dis'] is False        # EXIGE_SCORE_PARA_PUBLICAR = false hoje
        pg.evaluate("EXIGE_SCORE_PARA_PUBLICAR = true; renderFila()")
        c = card(pg, 'Sem score com pre')
        assert c['pronto']['dis'] is True and 'PENDENTE_DE_SCORE' in c['pronto']['txt']
        br.close()

# ---- 8) ATUALIZADO primeiro ------------------------------------------------------------------------------------------------
def test_08_atualizado_vem_primeiro_mesmo_com_criticidade_menor():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Critico novo', score=FINAL(90), comp=dict(criticidade='CRITICO'), prio='A'),
                      dict(k=2, titulo='Media atualizada', score=FINAL(50), comp=dict(criticidade='MEDIA', ultima_atualizacao_material='2026-10-12T00:00:00Z'), prio='C')])
        assert titulos(pg) == ['Media atualizada', 'Critico novo']
        assert 'ATUALIZADO' in card(pg, 'Media atualizada')['txt'] and 'ATUALIZADO' not in card(pg, 'Critico novo')['txt']
        br.close()

# ---- 9) criticidade -> prioridade -> atualidade -> score -> evidência -> id ------------------------------------------------
def test_09_ordem_prioridade_editorial_criticidade_atualidade_score_evidencia_id():
    with sync_playwright() as p:
        br, pg = abrir(p)
        casos = [
            dict(k=1, titulo='Media A recente 90', score=FINAL(90), comp=dict(criticidade='MEDIA'), prio='A', data='2026-10-10'),
            dict(k=2, titulo='Alta C', score=FINAL(45), comp=dict(criticidade='ALTA'), prio='C', data='2026-01-01'),
            dict(k=3, titulo='Critico D', score=FINAL(45), comp=dict(criticidade='CRITICO'), prio='D', data='2025-01-01'),
            dict(k=4, titulo='Media A antigo', score=FINAL(99), comp=dict(criticidade='MEDIA'), prio='A', data='2026-05-01'),
            dict(k=5, titulo='Media B', score=FINAL(99), comp=dict(criticidade='MEDIA'), prio='B', data='2026-10-11'),
            dict(k=6, titulo='Media A recente 60', score=FINAL(60), comp=dict(criticidade='MEDIA'), prio='A', data='2026-10-10'),
            dict(k=7, titulo='Media A recente 60 com evid', score=FINAL(60), comp=dict(criticidade='MEDIA'), prio='A', data='2026-10-10', evid=[dict(id='e1', trecho_literal='x', resumo_extraido='y')]),
            dict(k=8, titulo='Sem criticidade', score=FINAL(95), prio='A', data='2026-10-12'),
        ]
        carregar(pg, casos)
        assert titulos(pg) == ['Critico D', 'Alta C', 'Media B', 'Media A recente 90', 'Media A recente 60 com evid', 'Media A recente 60', 'Sem criticidade', 'Media A antigo']
        br.close()

def test_09b_score_provisorio_nao_entra_na_ordem():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Prelim 99', score=PRELIM(99), comp=dict(criticidade='MEDIA'), data='2026-10-10'),
                      dict(k=2, titulo='Final 50', score=FINAL(50), comp=dict(criticidade='MEDIA'), data='2026-10-10')])
        assert titulos(pg) == ['Final 50', 'Prelim 99']
        br.close()

# ---- 10) nenhum dado histórico apagado -----------------------------------------------------------------------------------------
def test_10_nada_e_apagado_nem_alterado_pela_decisao_de_score():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Baixo', score=FINAL(10), comp=dict(criticidade='BAIXA'), pre='Texto antigo', evid=[dict(id='e1', trecho_literal='t', resumo_extraido='r')])])
        antes = pg.evaluate("JSON.stringify(filaData.map(i=>i.event))")
        mostrar_todos(pg, True); mostrar_todos(pg, False); mostrar_todos(pg, True)
        depois = pg.evaluate("JSON.stringify(filaData.map(i=>i.event))")
        assert antes == depois                                          # evento, evidência, score e pré-release intactos
        assert json.loads(depois)[0]['pre_release'] == 'Texto antigo' and len(json.loads(depois)[0]['evidencias']) == 1
        assert pg.evaluate("window.__updates.length") == 0              # nenhuma escrita/remoção
        assert 'Texto antigo' in card(pg, 'Baixo')['txt']
        br.close()

def test_11_trava_editorial_mantem_na_fila_quem_ja_foi_aprovado_por_humano():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Ja aprovado', score=FINAL(20), comp=dict(criticidade='MEDIA'), pre='Texto', status='pronto_para_publicar')])
        assert titulos(pg) == ['Ja aprovado']
        assert card(pg, 'Ja aprovado')['sit'] == 'FORA_DA_SELECAO_MANTIDO_POR_TRAVA'
        br.close()

def test_12_titulo_fato_nao_e_alterado_pelo_card():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Titulo <b>exato</b> do fato', score=FINAL(70))])
        assert titulos(pg) == ['Titulo <b>exato</b> do fato']
        br.close()

def test_13_master_ve_aviso_de_nao_enviar_a_ia_em_fora_da_selecao_e_pendente():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, [dict(k=1, titulo='Baixo', score=FINAL(10), comp=dict(criticidade='BAIXA')), dict(k=2, titulo='Sem score'), dict(k=3, titulo='Bom', score=FINAL(70))], master=True)
        mostrar_todos(pg, True)
        av = pg.evaluate("[...document.querySelectorAll('details.iaEvento')].map(d=>d.closest('.card').querySelector('.titulo').textContent+'|'+d.dataset.avisoIa)")
        assert 'Baixo|Não enviar à IA: FORA_DA_SELECAO (SCORE_MENOR_40)' in av and 'Sem score|Não enviar à IA: PENDENTE_DE_SCORE' in av and 'Bom|' in av
        br.close()

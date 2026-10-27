"""Regras da fila NO BANCO: a interface só exibe o que public.fila_editorial devolve (prioridade, ordem, bloqueios, aviso de IA),
aplica o rascunho da IA só por clique e cai no modo de transição se o banco ainda não tem as regras. Supabase SIMULADO, sem rede."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_operacao_assistida import abrir
from test_fila_editorial import carregar, card, titulos, FINAL, mostrar_todos

def dbitem(k, cod='C', ordem=1, motivo='REGRA_DO_BANCO', texto='regra do banco', bloq_pronto=None, ia=None, crit='MEDIA', score=70):
    return {'event_id': f'uuid-{k}', 'ordem': ordem, 'criticidade': crit,
            'decisao': {'score_valor': score, 'score_decisorio': True, 'score_estagio': 'final', 'score_versao': 'v', 'score_motivo': 'SCORE_FINAL_HOMOLOGADO'},
            'situacao': {'codigo': 'NA_SELECAO', 'foraDaSelecao': False, 'regra': None, 'motivo': None},
            'atual': {'material_ts': 1790000000000, 'material_texto': '2026-10-10', 'atualizado': False}, 'qualidade_evidencia': 2,
            'ineditismo': {'inedito': True, 'texto': 'Inédito'},
            'prioridade_editorial': {'codigo': cod, 'rotulo': {'A': 'IMEDIATA', 'B': 'ALTA', 'C': 'AVALIAR', 'D': 'BAIXA/FORA', 'PENDENTE': 'PENDENTE'}[cod], 'motivo': motivo, 'texto': texto, 'aviso': None},
            'bloqueios': {'pronto_para_publicar': bloq_pronto or [], 'publicado': (bloq_pronto or []) + ['aprove antes (Pronto p/ publicar)']},
            'ia': ia or {'pode': True, 'motivos': []}, 'regras_versao': 'FILA-PARAMS-V1'}

def mock_banco(pg, itens, erro=None):
    pg.evaluate("""([itens, erro]) => { window.__rpcMock = window.__rpcMock || {};
        window.__rpcMock.fila_editorial = async () => erro ? {data:null, error:erro} : {data: itens, error:null}; }""", [itens, erro])

def casos(): return [dict(k=1, titulo='Um', score=FINAL(90), comp=dict(criticidade='CRITICO')), dict(k=2, titulo='Dois', score=FINAL(70), comp=dict(criticidade='MEDIA'))]

def prepara(pg, itens, erro=None, bloquear_legado=True):
    pg.evaluate("window.__rpcMock = {}")
    mock_banco(pg, itens, erro)
    if bloquear_legado:   # se a interface tentar decidir sozinha, o teste quebra
        pg.evaluate("""() => { const nao = () => { throw new Error('regra local usada com o banco respondendo'); };
            window.prioridadeEditorial = nao; window.situacaoFila = nao; window.decisaoScore = nao; window.ineditismoDe = nao; }""")

def test_prioridade_e_texto_vem_do_banco_e_a_regra_local_nao_e_usada():
    with sync_playwright() as p:
        br, pg = abrir(p)
        pg.evaluate("window.__rpcMock = {}")
        # injeta o mock ANTES do carregar (carregar() recria o sb e preserva __rpcMock)
        mock_banco(pg, [dbitem(1, 'D', 1, texto='texto escolhido pelo banco', crit='CRITICO', score=90), dbitem(2, 'B', 2)])
        pg.evaluate("""() => { const nao = () => { throw new Error('regra local usada'); };
            window.prioridadeEditorial = nao; window.situacaoFila = nao; window.decisaoScore = nao; window.ineditismoDe = nao; }""")
        carregar(pg, casos())
        c = card(pg, 'Um')
        assert 'texto escolhido pelo banco' in c['txt'] and 'BAIXA/FORA' in c['txt']          # CRITICO 90 seria A nas regras antigas
        assert pg.evaluate("filaData.every(i=>i.regrasOrigem==='banco')")
        assert 'MODO DE TRANSIÇÃO' not in pg.evaluate("document.getElementById('filterSummary').textContent")
        assert pg.evaluate("window.__rpcs.filter(r=>r.nome==='fila_editorial').length") == 1
        br.close()

def test_ordem_da_fila_e_a_do_banco():
    with sync_playwright() as p:
        br, pg = abrir(p)
        mock_banco(pg, [dbitem(1, 'A', 2, crit='CRITICO', score=90), dbitem(2, 'C', 1)])
        carregar(pg, casos())
        assert titulos(pg) == ['Dois', 'Um']             # o banco manda: ordem 1 = Dois (as regras antigas poriam Um primeiro)
        br.close()

def test_bloqueio_de_avanco_vem_do_banco():
    with sync_playwright() as p:
        br, pg = abrir(p)
        mock_banco(pg, [dbitem(1, 'A', 1, bloq_pronto=['bloqueio decidido no banco']), dbitem(2, 'C', 2)])
        carregar(pg, casos())
        a, b = card(pg, 'Um'), card(pg, 'Dois')
        assert a['pronto']['dis'] is True and 'bloqueio decidido no banco' in a['pronto']['title']
        assert b['pronto']['dis'] is False
        br.close()

def test_aviso_de_ia_vem_do_banco():
    with sync_playwright() as p:
        br, pg = abrir(p)
        mock_banco(pg, [dbitem(1, 'D', 1, ia={'pode': False, 'motivos': ['PRIORIDADE_D']}), dbitem(2, 'C', 2)])
        carregar(pg, casos(), master=True)
        av = pg.evaluate("[...document.querySelectorAll('details.iaEvento')].map(d=>d.dataset.avisoIa)")
        assert av == ['Não enviar à IA: PRIORIDADE_D', '']
        br.close()

def test_banco_sem_as_regras_cai_no_modo_de_transicao_e_avisa():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos())          # rpc ausente (PGRST202)
        assert pg.evaluate("filaData.every(i=>i.regrasOrigem==='transicao')")
        assert 'MODO DE TRANSIÇÃO' in pg.evaluate("document.getElementById('filterSummary').textContent")
        assert titulos(pg) == ['Um', 'Dois']
        br.close()

def test_erro_real_do_banco_nao_vira_regra_local_em_silencio():
    with sync_playwright() as p:
        br, pg = abrir(p)
        mock_banco(pg, None, erro={'code': '42501', 'message': 'permission denied for function fila_editorial'})
        pg.evaluate(__import__('test_fila_editorial').SETUP, dict(casos=casos(), master=False))
        pg.evaluate("carregarFila()"); pg.wait_for_timeout(600)
        assert pg.evaluate("filaData.length") == 0 or pg.evaluate("document.querySelectorAll('#filaWrap .card').length") == 0
        br.close()

def test_entrada_aparece_no_topo_do_card_ao_lado_dos_indicadores():
    with sync_playwright() as p:
        br, pg = abrir(p)
        carregar(pg, casos())
        r = pg.evaluate("""() => { const c = document.querySelector('#filaWrap .card'); const e = c.querySelector('.cardTop .ind-entrada');
            return {topo: !!e, txt: e && e.innerText, fora: !!c.querySelector('.scoreMeta .entradaTopo')}; }""")
        assert r['topo'] and 'Entrada' in r['txt'] and '01/10/2026' in r['txt'] and not r['fora']
        br.close()

# ---- rascunho da IA -> pré-release (só por clique) ----
def rascunho(pg, resposta, pode_editorial=True):
    pg.evaluate("""([r, pe]) => { window.__rpcs = []; window.__aplic = []; window.pode = (a) => pe && a === 'editorial';
        sb = { rpc: async (nome, args) => { window.__rpcs.push({nome, args});
          if (nome === 'fila_rascunho_pre_release') return r;
          if (nome === 'fila_aplicar_rascunho_pre_release') { window.__aplic.push(args); return {data:{ok:true}, error:null}; }
          return {data:null, error:{code:'PGRST202'}}; } };
        window.carregarFila = async () => { window.__recarregou = true; };
        document.body.insertAdjacentHTML('beforeend', '<div id=rp></div>'); }""", [resposta, pode_editorial])
    pg.evaluate("rascunhoPreCarregar(document.getElementById('rp'), 'uuid-9')"); pg.wait_for_timeout(200)

OK_R = {'data': {'execucao_id': 'x1', 'rascunho': 'Rascunho gerado pela IA.', 'ja_tem_pre_release': False, 'pode_aplicar': True, 'bloqueio': None}, 'error': None}

def test_mostrar_rascunho_nao_aplica_nada_sozinho():
    with sync_playwright() as p:
        br, pg = abrir(p)
        rascunho(pg, OK_R)
        assert 'Rascunho gerado pela IA.' in pg.evaluate("document.getElementById('rp').innerText")
        assert pg.evaluate("window.__aplic.length") == 0 and pg.evaluate("window.__rpcs.map(r=>r.nome)") == ['fila_rascunho_pre_release']
        br.close()

def test_clique_aplica_com_a_execucao_vista_e_recarrega_a_fila():
    with sync_playwright() as p:
        br, pg = abrir(p)
        pg.on('dialog', lambda d: d.accept())
        rascunho(pg, OK_R)
        pg.click('#rp .btnAplicarRascunho'); pg.wait_for_timeout(200)
        assert pg.evaluate("window.__aplic") == [{'p_event_id': 'uuid-9', 'p_execucao_id': 'x1', 'p_substituir': False}]
        assert pg.evaluate("window.__recarregou") is True
        br.close()

def test_cancelar_a_confirmacao_nao_aplica():
    with sync_playwright() as p:
        br, pg = abrir(p)
        pg.on('dialog', lambda d: d.dismiss())
        rascunho(pg, OK_R); pg.click('#rp .btnAplicarRascunho'); pg.wait_for_timeout(200)
        assert pg.evaluate("window.__aplic.length") == 0
        br.close()

def test_evento_com_pre_release_exige_substituicao_explicita():
    with sync_playwright() as p:
        br, pg = abrir(p)
        pg.on('dialog', lambda d: d.accept())
        rascunho(pg, {'data': {**OK_R['data'], 'ja_tem_pre_release': True}, 'error': None})
        assert 'Substituir' in pg.evaluate("document.querySelector('#rp .btnAplicarRascunho').innerText")
        pg.click('#rp .btnAplicarRascunho'); pg.wait_for_timeout(200)
        assert pg.evaluate("window.__aplic[0].p_substituir") is True
        br.close()

def test_bloqueio_do_banco_esconde_o_botao_e_explica():
    with sync_playwright() as p:
        br, pg = abrir(p)
        rascunho(pg, {'data': {**OK_R['data'], 'pode_aplicar': False, 'bloqueio': 'FORA_DA_SELECAO'}, 'error': None})
        t = pg.evaluate("document.getElementById('rp').innerText")
        assert pg.evaluate("!!document.querySelector('#rp .btnAplicarRascunho')") is False and 'abaixo do corte' in t
        br.close()

def test_sem_permissao_editorial_nem_consulta():
    with sync_playwright() as p:
        br, pg = abrir(p)
        rascunho(pg, OK_R, pode_editorial=False)
        assert pg.evaluate("window.__rpcs.length") == 0 and pg.evaluate("document.getElementById('rp').innerHTML") == ''
        br.close()

def test_erro_do_banco_ao_aplicar_aparece_e_nao_recarrega():
    with sync_playwright() as p:
        br, pg = abrir(p)
        msgs = []
        pg.on('dialog', lambda d: (msgs.append(d.message), d.accept()))
        rascunho(pg, OK_R)
        pg.evaluate("""() => { const o = sb.rpc; sb.rpc = async (n, a) => n === 'fila_aplicar_rascunho_pre_release' ? {data:null, error:{message:'pre_release_recusado: existe análise mais recente; recarregue'}} : o(n, a); }""")
        pg.click('#rp .btnAplicarRascunho'); pg.wait_for_timeout(200)
        assert any('análise mais recente' in m for m in msgs) and pg.evaluate("window.__recarregou") is None
        br.close()

def test_migracao_ausente_mostra_aviso_em_vez_de_botao():
    with sync_playwright() as p:
        br, pg = abrir(p)
        rascunho(pg, {'data': None, 'error': {'code': 'PGRST202', 'message': 'x'}})
        assert '20261019' in pg.evaluate("document.getElementById('rp').innerText")
        br.close()

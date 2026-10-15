"""Painel ADMIN > Piloto IA (operação assistida): roda o index.html real num Chromium com o Supabase SIMULADO.
Nenhuma rede, nenhuma chamada paga. Confere: só elegíveis selecionáveis, teto de 6, 1 chamada por caso,
nenhum texto/pré-IA vindo do navegador, sem nova tentativa, parada em erro fatal e leitura do resultado."""
import json, pathlib
from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[2]
HTML = (RAIZ / 'index.html').read_text(encoding='utf-8')
STUB = "window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:null}}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}}),signOut:async()=>({})},from(){throw new Error('x')},functions:{invoke:async()=>({data:null,error:{message:'x'}})}})}"
EMP = '11111111-1111-1111-1111-111111111111'; CART = '22222222-2222-2222-2222-222222222222'; EXE = '33333333-3333-3333-3333-333333333333'
LOTE = 'PILOTO_M6_M8_M9A_2026_10_R2'

SETUP = """
(n) => {
  window.__calls = [];
  const mods = ['M8_acidentes_ambientais','M6_outorgas','M9A_anm_movimentacoes'];
  const evs = Array.from({length:n.total}, (_,i)=>({id:'aaaaaaaa-0000-0000-0000-'+String(i).padStart(12,'0'), id_evento:'ev-'+i, modulo:mods[i%3],
     titulo_fato:'Evento '+i, municipio:'Cidade', status_editorial:'em_apuracao', revisao_humana:'Pendente', execucao_criacao_id:'@@EXE@@', carteira_id: n.nocart ? null : '@@CART@@', created_at:'2026-10-0'+(i%9+1)}));
  window.__evs = evs;
  const rows = {
    events: evs,
    api_execucoes: [],
    carteiras: [{id:'@@CART@@', nome:'Mineração', ativa:true}, {id:'44444444-4444-4444-4444-444444444444', nome:'Outra', ativa:true}],
    execucoes: [{id:'@@EXE@@', carteira_id: n.execCart ? '@@CART@@' : null}],
  };
  const b = (tabela) => { const st={t:tabela, ids:null, lim:null}; const q={
    select(){return q}, eq(){return q}, in(c,v){ if(c==='id_evento') st.ids=v; return q}, order(){return q}, limit(k){ st.lim=k; return q}, gte(){return q}, lt(){return q},
    then(res,rej){ let data = rows[tabela]||[]; if(st.ids) data = data.filter(e=>st.ids.includes(e.id_evento)); else if(tabela==='events' && st.lim) data = data.slice(0, st.lim); if(tabela==='api_execucoes' && window.__execRows) data = window.__execRows(); const r={data, error:null, count:data.length}; return Promise.resolve(r).then(res,rej); } }; return q; };
  window.sb = undefined;
  sb = { from: b, functions: { invoke: async (nome, {body}) => {
      window.__calls.push({nome, body});
      if (nome==='admin-api') return {data:{ok:true, config:{ativo:n.ativa, modelo_padrao:'gpt-5.4-mini', usa_credencial_global:true, limite_diario_usd:null, limite_mensal_usd:null}, precos:[{modelo:'gpt-5.4-mini', ativo:true, vigente_desde:'2026-01-01', input_usd_por_milhao:0.75, output_usd_por_milhao:4.5}]}, error:null};
      if (body.acao==='elegibilidade') return {data:{ok:true, lote_id:'@@LOTE@@', limite_max_lote:6, itens: body.event_ids.map((id,i)=>({event_id:id, encontrado:true, elegivel: i<n.eleg, ja_analisado_pela_ia:false, motivos_dispensa: i<n.eleg?[]:['fora_de_escopo'], regra_pre_ia:'REGRA_X', faixa_vinculo:null, score_antes:{estagio:'inicial', score_relevancia:50, prioridade:'B', versao_score:'v1'}}))}, error:null};
      if (nome==='executar-ai') return window.__resp(body);
      return {data:null,error:{message:'inesperado'}};
  }}};
  adminState.empresas=[{id:'@@EMP@@', nome:'Empresa T'}]; adminState.empresaId='@@EMP@@'; adminState.sub='piloto'; adminState.seq=1;
  window.pode = () => true; window.exigirPermissao = () => true;
  document.getElementById('adminBody') || document.body.insertAdjacentHTML('beforeend','<div id="adminBody"></div>');
  for (let el = document.getElementById('adminBody'); el && el !== document.documentElement; el = el.parentElement) { el.hidden = false; el.classList.remove('hidden'); el.style.display = (el.id === 'adminBody' || el.tagName === 'BODY') ? 'block' : 'block'; }
  document.querySelectorAll('#loginBox,#authBox,.authOverlay,#authView').forEach(x => x.style.display = 'none');
}
"""
for _k, _v in dict(EXE=EXE, CART=CART, LOTE=LOTE, EMP=EMP).items():
    SETUP = SETUP.replace("@@" + _k + "@@", _v)

def ok_resp(): return "(b)=>({data:{ok:true, execucao_id:'e-'+b.event_id, chamou_provider:true, modelo:'gpt-5.4-mini', uso:{input_tokens:100,output_tokens:50,total_tokens:150}, custo_estimado_usd:0.001, latencia_ms:900, revisao_humana:'Pendente'}, error:null})"

def abrir(p):
    br = p.chromium.launch(); pg = br.new_page()
    pg.route('**/*supabase*.js*', lambda r: r.fulfill(status=200, content_type='application/javascript', body=STUB))
    pg.route('**/*', lambda r: r.continue_() if r.request.url.startswith('data:') or 'supabase' in r.request.url else r.fulfill(status=200, body='') if r.request.url.startswith('http') else r.continue_())
    pg.set_content(HTML, wait_until='domcontentloaded'); pg.wait_for_timeout(500)
    return br, pg

def preparar(pg, total=6, eleg=4, ativa=True, resp=None, nocart=False, execcart=False, marcar=True):
    pg.evaluate(f"(()=>{{window.__resp = {resp or ok_resp()}; return 0}})()")
    pg.evaluate(SETUP, dict(total=total, eleg=eleg, ativa=ativa, nocart=nocart, execCart=execcart))
    pg.evaluate("adminPiloto()"); pg.wait_for_selector('#pilRodar', timeout=5000)
    if marcar:   # a tela não pré-marca nada: os testes marcam à mão (até 6), como a pessoa faria
        pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>!i.disabled).slice(0,6).forEach(i=>i.click())")

def confirmar(pg):
    pg.check('#pilOk'); pg.fill('#pilDigite', 'CONFIRMO')

def execs(pg): return pg.evaluate("window.__calls.filter(c=>c.nome==='executar-ai' && !c.body.acao)")

def test_so_elegiveis_selecionaveis_e_default():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=6, eleg=4, marcar=False)
        habil = pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>!i.disabled).length")
        marc = pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length")
        assert habil == 4 and marc == 0   # nada vem pré-marcado
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is True   # exige CONFIRMO
        confirmar(pg); pg.wait_for_timeout(50)
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is True   # confirmado, mas nenhum evento marcado
        pg.evaluate("[...document.querySelectorAll('input[data-pil]')].find(i=>!i.disabled).click()"); pg.wait_for_timeout(50)
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is False
        br.close()

def test_teto_de_seis_e_um_por_caso_sem_texto_do_navegador():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=9, eleg=9)
        marc = pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length")
        assert marc == 6
        # tentar marcar um 7º: o painel recusa
        pg.evaluate("(()=>{const i=[...document.querySelectorAll('input[data-pil]')].find(x=>!x.checked&&!x.disabled); i.click();})()")
        assert pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length") == 6
        confirmar(pg); pg.click('#pilRodar'); pg.wait_for_selector('#pilConferencia', timeout=5000); pg.wait_for_timeout(400)
        cs = execs(pg)
        assert len(cs) == 6 and len({c['body']['event_id'] for c in cs}) == 6
        for c in cs:
            b = c['body']
            assert b['operacao'] == 'analise_editorial' and b['usar_api_real'] is True and b['limite_ia'] == 6 and b['reasoning_effort'] == 'none'
            assert 'payload' not in b and 'pre_ia' not in b and b['prompt'].endswith('_ANALISE_EDITORIAL_V2')
        br.close()

def test_usar_api_real_desmarcado_zero_pagas():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4)
        pg.uncheck('#pilReal'); confirmar(pg)
        assert 'Atenção' not in pg.inner_text('#pilPlano') and '0 chamada(s) paga(s)' in pg.inner_text('#pilPlano')
        pg.click('#pilRodar'); pg.wait_for_timeout(600)
        assert all(c['body']['usar_api_real'] is False for c in execs(pg))
        br.close()

def test_limite_ia_respeitado_no_cliente_tambem():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4)
        pg.fill('#pilLimite', '2'); confirmar(pg); pg.click('#pilRodar'); pg.wait_for_timeout(700)
        assert len(execs(pg)) == 2 and all(c['body']['limite_ia'] == 2 for c in execs(pg))
        br.close()

def test_erro_fatal_interrompe_sem_nova_tentativa():
    resp = "(b)=>({data:null,error:{message:'x',context:{json:async()=>({ok:false,code:'api_pausada',message:'A API está pausada.'})}}})"
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4, resp=resp)
        confirmar(pg); pg.click('#pilRodar'); pg.wait_for_timeout(700)
        assert len(execs(pg)) == 1                       # parou na primeira e não repetiu
        assert 'interrompida' in pg.inner_text('#pilResultado')
        br.close()

def test_resposta_invalida_conta_como_chamada_e_nao_repete():
    resp = "(b)=>({data:null,error:{message:'x',context:{json:async()=>({ok:false,code:'resposta_invalida',message:'inválida',erros:['fato_confirmado_sem_citacao'],execucao_id:'e-'+b.event_id,chamou_provider:true,uso:{total_tokens:10},custo_estimado_usd:0.001})}}})"
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4, resp=resp)
        confirmar(pg); pg.click('#pilRodar'); pg.wait_for_timeout(900)
        assert len(execs(pg)) == 4                       # um por caso, nenhum retry, não é erro fatal
        assert 'Chamadas reais: <b>4</b>' in pg.evaluate("document.getElementById('pilResultado').innerHTML")
        br.close()

def test_api_pausada_bloqueia_execucao():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4, ativa=False)
        confirmar(pg); pg.wait_for_timeout(50)
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is True
        br.close()

def test_resposta_estruturada_7_secoes_e_bloco_do_evento():
    j = {"fato_confirmado": {"texto": "Fato X", "citacoes": [1]}, "contexto_documental": {"texto": "Ctx", "citacoes": []}, "avaliacao_editorial": {"texto": "Aval"},
         "hipotese_apuracao": {"texto": "Hip"}, "lacunas": ["L1"], "perguntas_redacao": ["P1"], "proposta_abordagem": {"texto": "Prop", "rascunho_pre_release": None}}
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=1)
        html = pg.evaluate("(t)=>iaRespostaHTML(t)", json.dumps(j))
        for rot in ['Fato confirmado', 'Contexto documental', 'Avaliação editorial', 'Hipótese de apuração', 'Lacunas', 'Perguntas para a redação', 'Proposta de abordagem']:
            assert rot in html
        pg.evaluate("(()=>{window.__execRows = () => [{id:'x',status:'sucesso',modelo:'gpt-5.4-mini',custo_estimado_usd:0.002,versao_prompt:'M8_ANALISE_EDITORIAL_V2',resposta_texto:%s,metadata:{}}]; return 0})()" % json.dumps(json.dumps(j)))
        pg.evaluate("document.body.insertAdjacentHTML('beforeend','<details id=dd class=iaEvento data-ia-event=ev1 data-revisao=Pendente><div class=iaBody></div></details>')")
        pg.evaluate("iaEventoCarregar(document.getElementById('dd'))"); pg.wait_for_timeout(200)
        t = pg.evaluate("document.getElementById('dd').textContent")
        assert 'Passou no pré-IA' in t and 'Concluída' in t and 'Pendente' in t and 'Fato X' in t
        br.close()


def test_evento_sem_carteira_usa_a_da_execucao():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=4, nocart=True, execcart=True)
        assert pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>!i.disabled).length") == 4
        assert pg.input_value('#pilCarteira') == CART             # carteira da execução vira o padrão
        confirmar(pg); pg.click('#pilRodar'); pg.wait_for_timeout(700)
        assert all(c['body']['carteira_id'] == CART for c in execs(pg)) and len(execs(pg)) == 4
        br.close()

def test_evento_e_execucao_sem_carteira_exige_escolha():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, eleg=2, nocart=True, execcart=False)
        confirmar(pg); pg.wait_for_timeout(50)
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is True
        assert 'Selecione a carteira' in pg.inner_text('#pilPlano')
        pg.select_option('#pilCarteira', CART); pg.wait_for_timeout(50)
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is False
        br.close()


def contar(pg, js): return pg.evaluate(js)

def test_nada_vem_pre_marcado_mesmo_com_muitos_elegiveis():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=9, eleg=9, marcar=False)
        assert contar(pg, "[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length") == 0
        assert pg.evaluate("document.getElementById('pilRodar').disabled") is True
        br.close()

def test_incluir_evento_pelo_codigo_fora_dos_recentes():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=60, eleg=1, marcar=False)
        # a lista traz só os 40 mais recentes; ev-55 não aparece
        assert contar(pg, "[...document.querySelectorAll('input[data-pil]')].length") == 40
        assert 'ev-55' not in pg.inner_text('#adminBody')
        pg.fill('#pilCodigo', 'ev-55'); pg.click('#pilIncluir'); pg.wait_for_timeout(600)
        assert 'incluído pelo código' in pg.inner_text('#adminBody')
        assert contar(pg, "[...document.querySelectorAll('input[data-pil]')].length") == 41
        marcados = pg.evaluate("[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).map(i=>i.dataset.pil)")
        assert marcados == [pg.evaluate("window.__evs[55].id")]
        # a consulta de elegibilidade nunca passa de 50 ids
        eleg = pg.evaluate("window.__calls.filter(c=>c.body && c.body.acao==='elegibilidade').map(c=>c.body.event_ids.length)")
        assert eleg and max(eleg) <= 50
        confirmar(pg); pg.click('#pilRodar'); pg.wait_for_selector('#pilConferencia', timeout=5000); pg.wait_for_timeout(300)
        cs = execs(pg)
        assert len(cs) == 1 and cs[0]['body']['event_id'] == pg.evaluate("window.__evs[55].id") and cs[0]['body']['referencia_evento'] == 'ev-55'
        br.close()

def test_codigo_invalido_ou_inexistente_nao_inclui_nada():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=6, eleg=0, marcar=False)
        pg.fill('#pilCodigo', "x'; drop table events"); pg.click('#pilIncluir'); pg.wait_for_timeout(200)
        assert 'inválido' in pg.inner_text('#pilCodigoMsg')
        pg.fill('#pilCodigo', 'nao-existe-123'); pg.click('#pilIncluir'); pg.wait_for_timeout(600)
        assert 'Não encontrado' in pg.inner_text('#pilCodigoMsg')
        assert contar(pg, "[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length") == 0
        br.close()

def test_codigo_incluido_nao_elegivel_fica_desabilitado():
    with sync_playwright() as p:
        br, pg = abrir(p); preparar(pg, total=60, eleg=0, marcar=False)
        pg.fill('#pilCodigo', 'ev-55'); pg.click('#pilIncluir'); pg.wait_for_timeout(600)
        assert 'não elegível' in pg.inner_text('#pilCodigoMsg')
        assert contar(pg, "[...document.querySelectorAll('input[data-pil]')].filter(i=>i.checked).length") == 0
        br.close()

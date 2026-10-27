"""Fila do editor: selo "IA analisada" e opção "analisados pela IA primeiro" (só master). Supabase SIMULADO, sem rede."""
import pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_operacao_assistida import abrir, EMP

SETUP = """
(n) => {
  const mk = (i, criado) => ({id:'ev-uuid-'+i, id_evento:'ev-'+i, titulo_fato:'Evento '+i, resumo_factual:'', empresa:'Empresa T', municipio:'Cidade', fonte_id:null,
     status_editorial:'em_apuracao', revisao_humana:'Pendente', pre_release:null, url_oficial:null, data_evento:null, data_publicacao:null, created_at:criado,
     processo:null, tipo_evento:null, decisao:null, situacao_processual:null, proximo_marco:null, palavras_chave:[], justificativa_editorial:null,
     event_scores:[], documentos:[], evidencias:[], checklist_editorial:[]});
  // ev-0 é o mais novo; ev-1 e ev-2 são antigos e foram analisados pela IA (ev-2 mais recentemente)
  const eventos = [mk(0,'2026-10-10T10:00:00Z'), mk(1,'2026-08-06T10:00:00Z'), mk(2,'2026-08-29T10:00:00Z'), mk(3,'2026-09-01T10:00:00Z')];
  window.__consultas = [];
  const rows = { events: eventos, sources: [], api_execucoes: n.erroIa ? null : [
     {event_id:'ev-uuid-1', data_inicio:'2026-10-15T20:00:00Z'}, {event_id:'ev-uuid-2', data_inicio:'2026-10-15T20:05:00Z'}] };
  const b = (t) => { const q = { select(){return q}, eq(){return q}, in(){return q}, not(){return q}, order(){return q}, limit(){return q},
     then(res, rej){ window.__consultas.push(t); const d = rows[t]; const r = d === null ? {data:null, error:{message:'sem permissão'}} : {data:d||[], error:null}; return Promise.resolve(r).then(res, rej); } }; return q; };
  sb = { from: b, rpc: async (nome) => ({data:null, error:{code:'PGRST202', message:'Could not find the function public.'+nome}}), auth:{getSession:async()=>({data:{session:null}})}, functions:{invoke:async()=>({data:null,error:{message:'x'}})} };
  window.pode = (a) => n.master || a === 'editorial';
  clienteSelecionado = '@@EMP@@'; clientesCache = [{id:'@@EMP@@', nome:'Empresa T'}];
  document.getElementById('view-fila').classList.add('active');
}
""".replace("@@EMP@@", EMP)

def test_a_caixa_esta_ligada_ao_redesenho_da_fila():
    # o boot completo não roda neste ambiente simulado; confere que o ouvinte existe no código real
    assert "getElementById('iaPrimeiro').addEventListener('change', renderFila)" in (pathlib.Path(__file__).resolve().parents[2] / 'index.html').read_text(encoding='utf-8')

def carregar(pg, master=True, erro_ia=False):
    pg.evaluate(SETUP, dict(master=master, erroIa=erro_ia))
    pg.evaluate("carregarFila()"); pg.wait_for_function("document.querySelectorAll('#filaWrap .card').length >= 4", timeout=5000)

def ordem(pg): return pg.evaluate("[...document.querySelectorAll('#filaWrap .titulo')].map(x=>x.textContent)")

def test_selo_e_opcao_aparecem_so_para_master_e_ordem_padrao_nao_muda():
    with sync_playwright() as p:
        br, pg = abrir(p); carregar(pg, master=True)
        assert ordem(pg) == ['Evento 0', 'Evento 3', 'Evento 2', 'Evento 1']        # data de entrada, como sempre
        assert pg.evaluate("document.querySelectorAll('.seloIa').length") == 2
        assert pg.evaluate("document.getElementById('iaPrimeiroLabel').hidden") is False
        br.close()

def test_analisados_primeiro_com_a_analise_mais_recente_no_topo():
    with sync_playwright() as p:
        br, pg = abrir(p); carregar(pg, master=True)
        pg.evaluate("document.getElementById('iaPrimeiro').checked = true; renderFila()")
        assert ordem(pg) == ['Evento 2', 'Evento 1', 'Evento 0', 'Evento 3']
        pg.evaluate("document.getElementById('iaPrimeiro').checked = false; renderFila()")
        assert ordem(pg) == ['Evento 0', 'Evento 3', 'Evento 2', 'Evento 1']
        br.close()

def test_editor_comum_nao_ve_selo_nem_opcao_e_nao_consulta_registros_da_ia():
    with sync_playwright() as p:
        br, pg = abrir(p); carregar(pg, master=False)
        assert pg.evaluate("document.querySelectorAll('.seloIa').length") == 0
        assert pg.evaluate("document.getElementById('iaPrimeiroLabel').hidden") is True
        assert 'api_execucoes' not in pg.evaluate("window.__consultas")
        assert ordem(pg) == ['Evento 0', 'Evento 3', 'Evento 2', 'Evento 1']
        br.close()

def test_falha_ao_ler_registros_da_ia_nao_derruba_a_fila():
    with sync_playwright() as p:
        br, pg = abrir(p); carregar(pg, master=True, erro_ia=True)
        assert len(ordem(pg)) == 4 and pg.evaluate("document.querySelectorAll('.seloIa').length") == 0
        br.close()

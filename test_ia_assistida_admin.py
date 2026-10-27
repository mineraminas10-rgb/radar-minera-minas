"""IA assistida no detalhe do evento: master vê tudo; ADMIN vê só status + análise (sem modelo/custo/prompt) via função do servidor.
Usa o pode()/carregarPermissoes() REAIS do index.html: as permissões vêm do banco (rpc minhas_permissoes, simulada). Sem rede."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_operacao_assistida import abrir

RESP = json.dumps({"fato_confirmado": {"texto": "Fato do parecer", "citacoes": []}, "avaliacao_editorial": {"texto": "Avaliação X"}, "lacunas": [], "perguntas_redacao": []})

SETUP = """
(n) => {
  window.__consultas = []; window.__rpcs = [];
  authState.perfil = { role: n.role }; authState.permissoes = n.perm;
  const linhasMaster = [{id:'x', status:'sucesso', modelo:'MODELO-SECRETO', custo_estimado_usd:0.0042, versao_prompt:'PROMPT-V9', data_inicio:'2026-10-20T10:00:00Z', erro:null, motivo_bloqueio:null, resposta_texto:n.resposta, metadata:{}}];
  const q = (t) => { const o = { select(){return o}, eq(){return o}, order(){return o}, limit(){return o},
     then(res, rej){ window.__consultas.push(t); return Promise.resolve({data: n.master_nega ? null : linhasMaster, error: n.master_nega ? {message:'sem permissão'} : null}).then(res, rej); } }; return o; };
  sb = { from: q, rpc: async (nome, args) => { window.__rpcs.push({nome, args});
      if (nome === 'fila_rascunho_pre_release') return {data:null, error:{code:'PGRST202', message:'sem a migração 20261019'}};   // fora do escopo destes testes
      if (n.rpc_erro) return {data:null, error:{message:'permission denied for function'}};
      return {data: n.rpc_linhas === undefined ? [{status:'sucesso', data_inicio:'2026-10-20T10:00:00Z', motivo_bloqueio:null, flags:{}, resposta_texto:n.resposta, tem_erro:false}] : n.rpc_linhas, error:null}; } };
  document.body.insertAdjacentHTML('beforeend','<details id=dd class=iaEvento data-ia-event="ev-1" data-revisao="Pendente"><summary>IA</summary><div class=iaBody></div></details>');
}
"""

MATRIZ = {
  'master':  {'editorial': True, 'admin_painel': True, 'ia_assistida': True, 'ia_assistida_custo': True, 'todas_empresas': True, 'cliente_criar': True},
  'admin':   {'editorial': True, 'admin_painel': False, 'ia_assistida': True, 'ia_assistida_custo': False, 'todas_empresas': False, 'cliente_criar': False},
  'cliente': {},
}

def rodar(role, **kw):
    with sync_playwright() as p:
        br, pg = abrir(p)
        pg.evaluate(SETUP, dict(role=role, resposta=RESP, perm=MATRIZ[role], **kw))
        pg.evaluate("iaEventoCarregar(document.getElementById('dd'))"); pg.wait_for_timeout(250)
        out = dict(texto=pg.evaluate("document.getElementById('dd').textContent"), consultas=pg.evaluate("window.__consultas"), rpcs=pg.evaluate("window.__rpcs"))
        br.close()
    return out

def perm_do_banco(retorno):
    """Roda carregarPermissoes() real com sb.rpc simulado; retorna o resultado e as chamadas."""
    with sync_playwright() as p:
        br, pg = abrir(p)
        r = pg.evaluate("""async (ret) => { window.__r = []; sb = { rpc: async (n) => { window.__r.push(n); return ret; } };
            const x = await carregarPermissoes('admin'); return { x, chamadas: window.__r }; }""", retorno)
        br.close()
    return r

def test_permissoes_vem_do_banco_pela_funcao_minhas_permissoes():
    r = perm_do_banco({'data': {'editorial': True, 'ia_assistida': True, 'admin_painel': False}, 'error': None})
    assert r['chamadas'] == ['minhas_permissoes'] and r['x']['origem'] == 'banco' and r['x']['permissoes'] == {'editorial': True, 'ia_assistida': True, 'admin_painel': False}

def test_pode_obedece_so_ao_que_o_banco_devolveu_e_o_papel_nao_importa():
    with sync_playwright() as p:
        br, pg = abrir(p)
        r = pg.evaluate("""() => { const f = (role, perm) => { authState.perfil = {role}; authState.permissoes = perm; return ['ia_assistida','ia_assistida_custo','admin_painel','todas_empresas'].map(a => pode(a)); };
            return { master_sem_nada: f('master', {}), master_nulo: f('master', null), admin_com_tudo: f('admin', {ia_assistida:true, ia_assistida_custo:true, admin_painel:true, todas_empresas:true}),
                     so_true_vale: f('admin', {ia_assistida:'sim', admin_painel:1}) } }""")
        br.close()
    assert r['master_sem_nada'] == [False] * 4 and r['master_nulo'] == [False] * 4          # sem permissão no banco, nem o master pode
    assert r['admin_com_tudo'] == [True] * 4                                                 # o que manda é a linha do banco, não o papel
    assert r['so_true_vale'] == [False] * 4

def test_sem_a_funcao_no_banco_usa_a_copia_de_transicao_sem_liberar_ia_assistida_ao_admin():
    for erro in [{'code': 'PGRST202', 'message': 'Could not find the function public.minhas_permissoes'}, {'code': '42883', 'message': 'function minhas_permissoes() does not exist'}]:
        adm = perm_do_banco({'data': None, 'error': erro})
        assert adm['x']['origem'] == 'transicao' and adm['x']['permissoes']['editorial'] is True and adm['x']['permissoes']['ia_assistida'] is False and adm['x']['permissoes']['admin_painel'] is False

def test_outro_erro_ao_ler_permissoes_bloqueia_em_vez_de_liberar():
    r = perm_do_banco({'data': None, 'error': {'code': '42501', 'message': 'permission denied'}})
    assert 'erro' in r['x'] and 'permissoes' not in r['x']

def test_entrada_do_app_carrega_as_permissoes_antes_de_abrir():
    src = (pathlib.Path(__file__).resolve().parents[2] / 'index.html').read_text(encoding='utf-8')
    assert "const perm = await carregarPermissoes(perfil.role);" in src and "permissoes: perm.permissoes" in src
    assert "Não foi possível verificar suas permissões" in src

def test_admin_ve_status_e_analise_sem_modelo_custo_prompt():
    o = rodar('admin')
    t = o['texto']
    assert 'Concluída' in t and 'Fato do parecer' in t and 'Avaliação X' in t and 'Revisão humana' in t and 'Passou no pré-IA' in t
    for proibido in ['Modelo', 'Custo', 'Prompt', 'MODELO-SECRETO', 'PROMPT-V9', '0.0042', 'US$']:
        assert proibido not in t, proibido

def test_admin_usa_a_funcao_do_servidor_e_nunca_consulta_api_execucoes_direto():
    o = rodar('admin')
    assert [r for r in o['rpcs'] if r['nome'] != 'fila_rascunho_pre_release'] == [{'nome': 'ia_assistida_evento', 'args': {'p_event_id': 'ev-1'}}]
    assert o['consultas'] == []

def test_master_continua_com_a_visao_completa_e_sem_rpc():
    o = rodar('master')
    t = o['texto']
    assert 'Modelo: MODELO-SECRETO' in t and 'Prompt: PROMPT-V9' in t and 'Custo' in t and 'Fato do parecer' in t
    assert o['consultas'] == ['api_execucoes'] and [r for r in o['rpcs'] if r['nome'] != 'fila_rascunho_pre_release'] == []

def test_perfil_sem_permissao_nao_consulta_nada():
    o = rodar('cliente')
    assert o['texto'].strip().endswith('Sem permissão.') and o['consultas'] == [] and o['rpcs'] == []

def test_admin_sem_registros_ve_nunca_enviado_sem_dica_de_painel_admin():
    o = rodar('admin', rpc_linhas=[])
    assert 'Nunca enviado à IA.' in o['texto'] and 'Piloto IA' not in o['texto']

def test_admin_chamada_com_erro_mostra_aviso_generico_sem_texto_do_erro():
    o = rodar('admin', rpc_linhas=[{'status': 'erro', 'data_inicio': '2026-10-20T10:00:00Z', 'motivo_bloqueio': None, 'flags': {}, 'resposta_texto': None, 'tem_erro': True}])
    assert 'Com erro' in o['texto'] and 'A chamada terminou com erro.' in o['texto']

def test_admin_dispensado_pre_ia_mostra_o_motivo_pelas_flags():
    o = rodar('admin', rpc_linhas=[{'status': 'bloqueado_pre_ia', 'data_inicio': '2026-10-20T10:00:00Z', 'motivo_bloqueio': 'fora_de_escopo', 'flags': {'fora_de_escopo': True}, 'resposta_texto': None, 'tem_erro': False}])
    assert 'Passou no pré-IA: não' in o['texto'] and 'Dispensada (pré-IA)' in o['texto']

def test_admin_sem_a_migration_aplicada_ve_mensagem_clara_e_nada_quebra():
    o = rodar('admin', rpc_erro=True)
    assert 'Não foi possível carregar' in o['texto'] and 'MODELO' not in o['texto']

def test_cartao_so_oferece_o_bloco_a_quem_tem_permissao():
    src = (pathlib.Path(__file__).resolve().parents[2] / 'index.html').read_text(encoding='utf-8')
    assert "pode('ia_assistida') ?" in src and "IA assistida${pode('ia_assistida_custo') ? '' : ' — leitura'}" in src

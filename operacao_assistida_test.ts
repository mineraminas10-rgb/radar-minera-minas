// Testes da operação assistida (analise_editorial): sem rede, sem banco, sem chave real.
// Rodar: deno test --no-lock supabase/functions/tests/operacao_assistida_test.ts
// (sem dependência de rede: asserções mínimas locais, no mesmo formato do @std/assert)
function assert(c: unknown, msg = 'asserção falhou'): asserts c { if (!c) throw new Error(msg); }
function assertEquals(a: unknown, b: unknown, msg = ''): void {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg} esperado ${JSON.stringify(b)} mas veio ${JSON.stringify(a)}`);
}
function assertStringIncludes(s: string, sub: string): void { if (!s.includes(sub)) throw new Error(`"${s.slice(0, 200)}" não contém "${sub}"`); }
async function assertRejects(fn: () => Promise<unknown>, _t?: unknown, trecho?: string): Promise<void> {
  try { await fn(); } catch (e) {
    const m = e instanceof Error ? e.message : String(e);
    if (trecho && !m.toLowerCase().includes(trecho.toLowerCase())) throw new Error(`erro "${m}" não contém "${trecho}"`);
    return;
  }
  throw new Error('deveria ter lançado erro');
}
import { executarIA } from '../_shared/executar.ts';
import type { ExecDeps, ExecInput } from '../_shared/executar.ts';
import { LIMITE_MAX_LOTE, LOTE_PILOTO_ID, consultarElegibilidade, montarEntrada, moduloCurto, validarAnalise } from '../_shared/analise.ts';
import { OPERACOES } from '../_shared/operacoes.ts';
import { PROMPTS, buscarPrompt } from '../_shared/prompts.ts';
import { sha256Hex } from '../_shared/gate.ts';
import type { Chamador } from '../_shared/autorizacao.ts';
import type { Dossie, Elegibilidade, ExecucaoNova, ExecucaoPatch, Repo } from '../_shared/types.ts';

const EMP = '4a8f5089-7662-4b38-a07b-907b76428a88';
const OUTRA = '5e7eecd3-b1d7-49b4-8466-78454a083f61';
const CART = '2190672f-6cdb-4053-b7b7-ee779164caae';
const EXEC = '11111111-1111-4111-8111-111111111111';
const CHAVE = 'sk-TESTE-NAO-VAZAR-1234567890abcdef';
const uid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

type Linha = Omit<ExecucaoNova, "modelo" | "status" | "metadata" | "erro" | "motivo_bloqueio"> & Omit<ExecucaoPatch, "metadata"> & { id: string; modelo: string | null; status: string; metadata?: Record<string, unknown>; erro?: string | null };
class Mem implements Repo {
  linhas: Linha[] = [];
  totaisChamados: string[] = [];
  eventos = new Map<string, { elig: Elegibilidade; dos: Dossie }>();
  falhaInsertPendente: string | null = null;
  eventoEmpresa = new Map<string, string>();
  getPerfil() { return Promise.resolve(null); }
  getEmpresasDoUsuario() { return Promise.resolve([]); }
  getEmpresa(id: string) { return Promise.resolve({ id, nome: 'x', ativa: true }); }
  getCarteira(id: string) { return Promise.resolve({ id, empresa_id: EMP, ativa: true }); }
  getEvento(id: string) { return Promise.resolve(this.eventos.has(id) ? { id, empresa_id: this.eventoEmpresa.get(id) ?? EMP, carteira_id: null } : null); }
  getConsulta(id: string) { return Promise.resolve({ id, empresa_id: EMP, carteira_id: null }); }
  getConfig() {
    return Promise.resolve({ id: 'c', empresa_id: EMP, provider: 'openai', ativo: true, usa_credencial_global: true, secret_ref: null, modelo_padrao: 'gpt-6-luna',
      limite_mensal_usd: 20, limite_mensal_tokens: null, limite_diario_usd: 2 });
  }
  getPreco() { return Promise.resolve({ id: 'p', provider: 'openai', modelo: 'gpt-6-luna', vigente_desde: '2026-01-01', input_usd_por_milhao: 0.1, cached_input_usd_por_milhao: null, output_usd_por_milhao: 0.5 }); }
  getConsumoLimites() { return Promise.resolve({ dia_usd: 0, mes_usd: 0, mes_tokens: 0 }); }
  insertExecucao(row: ExecucaoNova) {
    if (this.falhaInsertPendente && row.status === 'pendente') return Promise.reject(new Error(`execucao: ${this.falhaInsertPendente}`));
    const l = { ...row, id: `ex-${this.linhas.length + 1}` } as Linha; this.linhas.push(l); return Promise.resolve({ id: l.id });
  }
  updateExecucao(id: string, patch: ExecucaoPatch) { Object.assign(this.linhas.find((l) => l.id === id)!, patch); return Promise.resolve(); }
  insertAuditoria() { return Promise.resolve(); }
  lerChave() { return Promise.resolve(CHAVE); }
  buscarSucessoPorHash(_e: string, h: string) {
    const l = this.linhas.find((x) => x.hash_chamada === h && x.status === 'sucesso');
    return Promise.resolve(l ? { id: l.id, modelo: l.modelo ?? null, resposta_texto: l.resposta_texto ?? null, input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0, custo_estimado_usd: l.custo_estimado_usd ?? null } : null);
  }
  getElegibilidade(id: string) { return Promise.resolve(this.eventos.get(id)?.elig ?? { encontrado: false, elegivel: false, flags: {} }); }
  getDossie(id: string) { return Promise.resolve(this.eventos.get(id)?.dos ?? null); }
  estadoLote(_e: string, lote: string, ev: string | null) {
    const reais = this.linhas.filter((l) => l.metadata?.lote_id === lote && ['pendente', 'sucesso', 'erro'].includes(l.status));
    return Promise.resolve({ total: reais.length, evento_ja_chamado: reais.some((l) => l.event_id === ev) });
  }
  atualizarTotais(id: string) { this.totaisChamados.push(id); return Promise.resolve(); }
  reais() { return this.linhas.filter((l) => ['pendente', 'sucesso', 'erro'].includes(l.status)); }
}

function novoEvento(m: Mem, n: number, mod: 'M6_outorgas' | 'M8_acidentes_ambientais' | 'M9A_anm_movimentacoes', over: Partial<Elegibilidade> = {}) {
  const id = uid(n);
  const elig: Elegibilidade = {
    encontrado: true, event_id: id, empresa_id: EMP, modulo: mod, id_evento: `ev-${n}`, execucao_criacao_id: EXEC, status_editorial: 'em_apuracao',
    revisao_humana: 'Pendente', evidencias: 2, flags: {}, elegivel: true, regra_pre_ia: 'PRE_IA_TESTE_V1', ia_sucesso_previo: false,
    score_antes: { estagio: 'preliminar', score_relevancia: 27, prioridade: 'C', versao_score: 'SCORE-TESTE-V1' }, ...over,
  };
  const dos: Dossie = {
    event_id: id, empresa_id: EMP, carteira_id: null, execucao_criacao_id: EXEC, modulo: mod, id_evento: `ev-${n}`,
    evento: { titulo_fato: 'GSM Mineração Ltda — anulacao', empresa: 'GSM Mineração Ltda', processo: 'portaria-15.01.0050552.2026', data_evento: '2026-10-07' },
    evidencias: [
      { n: 1, campo: 'verbo_decisorio_literal', tipo: 'fato', trecho: 'Fica anulado o ato publicado dia 29/06/2026 da Portaria nº 15.01.0050552.2026 - Usuário: GSM Mineração Ltda. Motivo: Autotutela.', pagina_secao: null },
      { n: 2, campo: 'empresa', tipo: 'fato', trecho: 'GSM Mineração Ltda', pagina_secao: null },
    ],
  };
  m.eventos.set(id, { elig, dos });
  return id;
}

const RESP_OK = {
  fato_confirmado: { texto: 'O IGAM anulou o ato publicado em 29/06/2026 da Portaria 15.01.0050552.2026 em nome da GSM Mineração Ltda, por autotutela.', citacoes: [1] },
  contexto_documental: { texto: 'O texto identifica o usuário como GSM Mineração Ltda.', citacoes: [2] },
  avaliacao_editorial: { texto: 'Pode interessar por tratar de anulação de ato de outorga de uma mineradora.' },
  hipotese_apuracao: { texto: 'Verificar se a anulação decorre de erro formal ou de questão ambiental.' },
  lacunas: ['Finalidade do uso da água', 'Vazão outorgada'],
  perguntas_redacao: ['Qual foi o vício que motivou a autotutela?'],
  proposta_abordagem: { texto: 'Nota curta sobre a anulação, ouvindo o IGAM e a empresa.', rascunho_pre_release: null },
};
const respostaProvedor = (obj: unknown, extra: Record<string, unknown> = {}) => ({
  model: 'gpt-6-luna', status: 'completed',
  output: [{ type: 'message', content: [{ type: 'output_text', text: typeof obj === 'string' ? obj : JSON.stringify(obj) }] }],
  usage: { input_tokens: 900, output_tokens: 400, total_tokens: 1300, input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 0 } },
  ...extra,
});

function ambiente(m: Mem, fabrica: () => Response | Promise<Response> = () => new Response(JSON.stringify(respostaProvedor(RESP_OK)), { status: 200, headers: { 'x-request-id': 'req_abc' } })) {
  const chamadas: Array<{ url: string; auth: string; corpo: Record<string, unknown> }> = [];
  const deps: ExecDeps = {
    repo: m, getEnv: () => undefined, now: () => new Date('2026-10-13T20:00:00Z'),
    fetchFn: ((url: string, init: RequestInit) => {
      chamadas.push({ url, auth: String((init.headers as Record<string, string>).Authorization), corpo: JSON.parse(String(init.body)) });
      return Promise.resolve(fabrica());
    }) as unknown as typeof fetch,
  };
  return { deps, chamadas };
}
const master: Chamador = { userId: 'u-master', email: 'm@x', perfil: { id: 'u-master', role: 'master', nome: 'M', ativo: true }, deveTrocarSenha: false, empresas: [] };
const admin: Chamador = { userId: 'u-admin', email: 'a@x', perfil: { id: 'u-admin', role: 'admin', nome: 'A', ativo: true }, deveTrocarSenha: false, empresas: [EMP] };

const pedido = (eventId: string, over: Record<string, unknown> = {}): ExecInput => ({
  empresa_id: EMP, carteira_id: CART, event_id: eventId, execucao_id: EXEC, operacao: 'analise_editorial', modulo: 'm6',
  prompt: 'M6_ANALISE_EDITORIAL_V3', reasoning_effort: 'none', motivo_chamada: 'piloto_operacao_assistida', usar_api_real: true, limite_ia: 6, ...over,
});

// ------------------------------------------------------------------ catálogo e prompts
Deno.test('catálogo: analise_editorial é só master, esforço none, teto próprio e entrada pelo servidor', () => {
  const op = OPERACOES.analise_editorial;
  assertEquals(op.so_master, true);
  assertEquals(op.esforco_padrao, 'none');
  assertEquals(op.dossie_servidor, true);
  assert(op.max_output_tokens >= 1000 && op.max_output_tokens <= 2000);
  assertEquals(LIMITE_MAX_LOTE, 6);
});

Deno.test('prompts de analise_editorial: um por módulo, todos com as 7 seções e regras anti-invenção', () => {
  for (const nome of ['M6_ANALISE_EDITORIAL_V3', 'M8_ANALISE_EDITORIAL_V3', 'M9A_ANALISE_EDITORIAL_V3']) {
    const p = buscarPrompt(nome)!;
    assert(p, nome);
    assertEquals(p.operacao, 'analise_editorial');
    assertStringIncludes(p.instructions, 'Nunca invente');
    assertStringIncludes(p.instructions, 'Não atribua score');
    const props = (p.schema as { properties: Record<string, unknown> }).properties;
    assertEquals(Object.keys(props), ['fato_confirmado', 'contexto_documental', 'avaliacao_editorial', 'hipotese_apuracao', 'lacunas', 'perguntas_redacao', 'proposta_abordagem']);
  }
});

Deno.test('prompts congelados: o texto de uma versão publicada não muda (mudar = criar V2)', async () => {
  const esperados: Record<string, string> = JSON.parse(await Deno.readTextFile(new URL('./prompts_congelados.json', import.meta.url)));
  for (const p of PROMPTS) {
    const h = await sha256Hex(p.instructions + JSON.stringify(p.schema));
    assertEquals(esperados[`${p.nome}_${p.versao}`], h, `${p.nome}_${p.versao} mudou de texto`);
  }
});

// ------------------------------------------------------------------ fluxo feliz
Deno.test('caso elegível: 1 chamada real, entrada montada no servidor, resposta validada e rastreada', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id, { payload: { input: 'TEXTO DO NAVEGADOR DEVE SER IGNORADO' } }));
  assertEquals(r.status, 200);
  assertEquals(r.body.ok, true);
  assertEquals(chamadas.length, 1);
  const c = chamadas[0];
  assertStringIncludes(c.corpo.input as string, 'DOSSIÊ DO EVENTO');
  assert(!(c.corpo.input as string).includes('NAVEGADOR'));
  assert(!(c.corpo.input as string).toLowerCase().includes('score'));       // a IA não vê score/prioridade
  assertEquals(c.corpo.store, false);
  assertEquals((c.corpo.reasoning as { effort: string }).effort, 'none');
  assertEquals(((c.corpo.text as { format: { strict: boolean } }).format).strict, true);
  const l = m.linhas.find((x) => x.status === 'sucesso')!;
  for (const campo of ['empresa_id', 'carteira_id', 'modulo', 'event_id', 'execucao_id', 'provider', 'modelo', 'versao_prompt', 'versao_regra', 'reasoning_effort', 'hash_entrada', 'hash_chamada', 'request_id_provider', 'latencia_ms', 'input_tokens', 'output_tokens', 'total_tokens', 'custo_estimado_usd', 'resposta_texto', 'data_fim']) {
    assert((l as unknown as Record<string, unknown>)[campo] !== undefined && (l as unknown as Record<string, unknown>)[campo] !== null, `faltou ${campo}`);
  }
  assertEquals(l.modulo, 'm6');
  assertEquals(l.versao_prompt, 'M6_ANALISE_EDITORIAL_V3');
  assertEquals(l.versao_regra, 'PRE_IA_TESTE_V1:SCORE-TESTE-V1');
  assertEquals(l.metadata?.lote_id, LOTE_PILOTO_ID);
  assertEquals((l.metadata?.validacao as { ok: boolean }).ok, true);
  assertEquals(l.metadata?.revisao_humana, 'Pendente');
  assertEquals(r.body.revisao_humana, 'Pendente');
  assertEquals((r.body.resposta as { fato_confirmado: { citacoes: number[] } }).fato_confirmado.citacoes, [1]);
  assertEquals(m.totaisChamados, [EXEC]);
});

Deno.test('a chave nunca aparece em resposta, linha gravada ou log', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(chamadas[0].auth, `Bearer ${CHAVE}`);                       // só vai no cabeçalho ao provedor
  assert(!JSON.stringify(r).includes(CHAVE));
  assert(!JSON.stringify(m.linhas).includes(CHAVE));
});

// ------------------------------------------------------------------ parâmetros e travas
Deno.test('usar_api_real=false: zero chamadas pagas, bloqueio registrado', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id, { usar_api_real: false }));
  assertEquals(chamadas.length, 0);
  assertEquals(r.body.chamou_provider, false);
  assertEquals(r.body.code, 'usar_api_real_desligado');
  assertEquals(m.linhas[0].status, 'bloqueado_config');
  assertEquals(m.reais().length, 0);
});

Deno.test('usar_api_real e limite_ia são obrigatórios e limite_ia ≤ 6', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  await assertRejects(() => executarIA(deps, master, pedido(id, { usar_api_real: undefined })), Error, 'usar_api_real');
  await assertRejects(() => executarIA(deps, master, pedido(id, { usar_api_real: 'true' })), Error, 'usar_api_real');
  await assertRejects(() => executarIA(deps, master, pedido(id, { limite_ia: undefined })), Error, 'limite_ia');
  await assertRejects(() => executarIA(deps, master, pedido(id, { limite_ia: 7 })), Error, 'máximo');
  await assertRejects(() => executarIA(deps, master, pedido(id, { limite_ia: -1 })), Error, 'limite_ia');
  assertEquals(chamadas.length, 0);
});

Deno.test('limite_ia=0 não chama', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id, { limite_ia: 0 }));
  assertEquals(chamadas.length, 0); assertEquals(r.body.code, 'limite_ia_zero');
});

Deno.test('teto: nunca mais de 6 chamadas reais no lote (7º evento bloqueado sem tocar o provedor)', async () => {
  const m = new Mem(); const { deps, chamadas } = ambiente(m);
  const ids = Array.from({ length: 8 }, (_, i) => novoEvento(m, i + 1, 'M6_outorgas', { id_evento: `ev-${i + 1}` }));
  // dossiês distintos para não cair em idempotência
  ids.forEach((id, i) => { m.eventos.get(id)!.dos.evento.titulo_fato = `Caso ${i} distinto`; });
  const saidas = [];
  for (const id of ids) saidas.push(await executarIA(deps, master, pedido(id)));
  assertEquals(chamadas.length, 6);
  assertEquals(m.reais().length, 6);
  assertEquals(saidas[6].body.code, 'limite_ia_do_lote');
  assertEquals(saidas[7].body.code, 'limite_ia_do_lote');
  assertEquals(saidas[6].body.chamou_provider, false);
});

Deno.test('limite_ia=2 do pedido é respeitado', async () => {
  const m = new Mem(); const { deps, chamadas } = ambiente(m);
  const ids = [1, 2, 3].map((n) => novoEvento(m, n, 'M6_outorgas'));
  ids.forEach((id, i) => { m.eventos.get(id)!.dos.evento.titulo_fato = `Caso ${i}`; });
  for (const id of ids) await executarIA(deps, master, pedido(id, { limite_ia: 2 }));
  assertEquals(chamadas.length, 2);
});

Deno.test('trava do banco (trigger) recusando = bloqueio, sem chamada e sem custo', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  m.falhaInsertPendente = 'limite_ia_do_lote_atingido';
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(chamadas.length, 0);
  assertEquals(r.body.code, 'limite_ia_do_lote_atingido');
  assertEquals(m.reais().length, 0);
});

Deno.test('sem retry: evento que deu ERRO não é chamado de novo no lote', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const { deps, chamadas } = ambiente(m, () => new Response(JSON.stringify({ error: { message: 'boom' } }), { status: 500 }));
  const r1 = await executarIA(deps, master, pedido(id));
  assertEquals(r1.status, 502);
  assertEquals(m.reais()[0].status, 'erro');
  const r2 = await executarIA(deps, master, pedido(id));
  assertEquals(r2.body.code, 'evento_ja_chamado_no_lote');
  assertEquals(chamadas.length, 1);
});

Deno.test('idempotência: mesma entrada+regra+prompt+modelo já concluída = reutilizado, custo zero, sem chamada', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  await executarIA(deps, master, pedido(id));
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(chamadas.length, 1);
  assertEquals(r.body.origem, 'cache_interno');
  assertEquals(m.linhas.at(-1)!.status, 'reutilizado');
  assertEquals(m.reais().length, 1);
});

// ------------------------------------------------------------------ elegibilidade
Deno.test('evento NÃO elegível (regra determinística) = bloqueado_pre_ia, zero chamada; o navegador não consegue liberar', async () => {
  const m = new Mem();
  const id = novoEvento(m, 1, 'M8_acidentes_ambientais', { elegivel: false, flags: { descartado_por_regra_deterministica: true } });
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id, { modulo: 'm8', prompt: 'M8_ANALISE_EDITORIAL_V3', pre_ia: { descartado_por_regra_deterministica: false } }));
  assertEquals(chamadas.length, 0);
  assertEquals(m.linhas[0].status, 'bloqueado_pre_ia');
  assertEquals(r.body.code, 'pre_ia_descartado_por_regra_deterministica');
});

Deno.test('sem evidência = bloqueado_por_falta_de_documento', async () => {
  const m = new Mem();
  const id = novoEvento(m, 1, 'M9A_anm_movimentacoes', { evidencias: 0, elegivel: false, flags: { bloqueado_por_falta_de_documento: true } });
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id, { modulo: 'm9a', prompt: 'M9A_ANALISE_EDITORIAL_V3' }));
  assertEquals(chamadas.length, 0); assertEquals(r.body.code, 'pre_ia_bloqueado_por_falta_de_documento');
});

Deno.test('revisão humana já feita = fora de escopo (a IA só atua antes da revisão)', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas', { revisao_humana: 'Aprovada' });
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(chamadas.length, 0); assertEquals(r.body.code, 'pre_ia_fora_de_escopo');
});

Deno.test('escopo: módulo, prompt, execução e empresa precisam bater', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  await assertRejects(() => executarIA(deps, master, pedido(id, { modulo: 'm8', prompt: 'M8_ANALISE_EDITORIAL_V3' })), Error, 'módulo');
  await assertRejects(() => executarIA(deps, master, pedido(id, { prompt: 'M8_ANALISE_EDITORIAL_V3' })), Error, 'prompt');
  await assertRejects(() => executarIA(deps, master, pedido(id, { execucao_id: '22222222-2222-4222-8222-222222222222' })), Error, 'execucao_id');
  m.eventoEmpresa.set(id, OUTRA);
  await assertRejects(() => executarIA(deps, master, pedido(id)), Error, 'Escopo');
  assertEquals(chamadas.length, 0);
});

Deno.test('admin (não master) não executa analise_editorial', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const { deps, chamadas } = ambiente(m);
  await assertRejects(() => executarIA(deps, admin, pedido(id)), Error, 'permissão');
  assertEquals(chamadas.length, 0);
});

// ------------------------------------------------------------------ validação da resposta
Deno.test('resposta com número inventado = erro (paga, contada, bruta preservada, sem sucesso)', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const inventada = { ...RESP_OK, fato_confirmado: { texto: 'O IGAM anulou a outorga de 1.500 m³/h concedida em 12/03/2024.', citacoes: [1] } };
  const { deps, chamadas } = ambiente(m, () => new Response(JSON.stringify(respostaProvedor(inventada)), { status: 200 }));
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(chamadas.length, 1);
  assertEquals(r.body.ok, false); assertEquals(r.body.code, 'resposta_invalida');
  const l = m.reais()[0];
  assertEquals(l.status, 'erro');
  assertStringIncludes(l.erro ?? '', 'resposta_invalida');
  assert((l.resposta_texto ?? '').includes('1.500'));                    // bruta preservada
  assert((l.total_tokens ?? 0) > 0 && (l.custo_estimado_usd ?? 0) > 0);  // custo da chamada fica registrado
  assertEquals(m.linhas.filter((x) => x.status === 'sucesso').length, 0);
  assertEquals(m.totaisChamados.length, 1);
});

Deno.test('resposta que não é JSON / incompleta = erro, sem promoção', async () => {
  for (const corpo of [respostaProvedor('isto não é json'), respostaProvedor(RESP_OK, { status: 'incomplete' })]) {
    const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
    const { deps } = ambiente(m, () => new Response(JSON.stringify(corpo), { status: 200 }));
    const r = await executarIA(deps, master, pedido(id));
    assertEquals(r.body.code, 'resposta_invalida');
    assertEquals(m.reais()[0].status, 'erro');
  }
});

Deno.test('o fluxo nunca altera o evento: o repositório sequer tem operação de escrita em events/scores', () => {
  const metodos = Object.getOwnPropertyNames(Mem.prototype);
  for (const m of metodos) assert(!/(update|set|upsert).*(evento|event|score|status)/i.test(m), m);
});

Deno.test('validarAnalise: caso válido, seções ausentes, citação inexistente, score e publicação', () => {
  const entrada = 'Portaria 15.01.0050552.2026 publicada em 29/06/2026 GSM Mineração';
  assertEquals(validarAnalise(JSON.stringify(RESP_OK), entrada, 2).ok, true);
  const sem = { ...RESP_OK } as Record<string, unknown>; delete sem.lacunas;
  assertEquals(validarAnalise(JSON.stringify(sem), entrada, 2).ok, false);
  const cit = { ...RESP_OK, fato_confirmado: { ...RESP_OK.fato_confirmado, citacoes: [9] } };
  assertStringIncludes(validarAnalise(JSON.stringify(cit), entrada, 2).erros.join(), 'citacao_inexistente');
  const semCit = { ...RESP_OK, fato_confirmado: { ...RESP_OK.fato_confirmado, citacoes: [] } };
  assertStringIncludes(validarAnalise(JSON.stringify(semCit), entrada, 2).erros.join(), 'sem_citacao');
  const score = { ...RESP_OK, avaliacao_editorial: { texto: 'Dou score: 88 e prioridade A para este caso.' } };
  assertStringIncludes(validarAnalise(JSON.stringify(score), entrada, 2).erros.join(), 'score_ou_prioridade');
  const pub = { ...RESP_OK, proposta_abordagem: { texto: 'O caso está liberado para publicação imediata.', rascunho_pre_release: null } };
  assertStringIncludes(validarAnalise(JSON.stringify(pub), entrada, 2).erros.join(), 'libera_publicacao');
  const extra = { ...RESP_OK, campo_novo: 'x' };
  assertEquals(validarAnalise(JSON.stringify(extra), entrada, 2).ok, false);
  const ok2 = { ...RESP_OK, fato_confirmado: { texto: 'A portaria foi publicada em 29/06/2026 (processo 15.01.0050552.2026).', citacoes: [1, 1, 2] } };
  assertEquals(validarAnalise(JSON.stringify(ok2), entrada, 2).analise!.fato_confirmado.citacoes, [1, 2]);
});

Deno.test('montarEntrada: só dossiê (campos e evidências numeradas), sem score', () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const t = montarEntrada(m.eventos.get(id)!.dos);
  assertStringIncludes(t, '[1] (verbo_decisorio_literal | fato)');
  assertStringIncludes(t, 'Empresa/titular: GSM Mineração Ltda');
  assert(!/score|prioridade/i.test(t));
  assertEquals(moduloCurto('M9A_anm_movimentacoes'), 'm9a');
  assertEquals(moduloCurto('M8_acidentes_ambientais'), 'm8');
  assertEquals(moduloCurto('M6_outorgas'), 'm6');
  assertEquals(moduloCurto('M1_licenciamento'), 'm1');
});

Deno.test('consultarElegibilidade: master, sem custo; outro admin recusado; evento de outra empresa não vaza', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas'); const id2 = novoEvento(m, 2, 'M6_outorgas'); m.eventoEmpresa.set(id2, OUTRA);
  const r = await consultarElegibilidade(m, master, { empresa_id: EMP, event_ids: [id, id2] });
  assertEquals(r.itens[0].elegivel, true);
  assertEquals(r.itens[1].elegivel, false);
  await assertRejects(() => consultarElegibilidade(m, admin, { empresa_id: EMP, event_ids: [id] }), Error, 'permissão');
  await assertRejects(() => consultarElegibilidade(m, master, { empresa_id: EMP, event_ids: [] }), Error);
});

Deno.test('validarAnalise: data ISO do dossiê aceita em dd/mm/aaaa; data diferente continua barrada', () => {
  const entrada = 'Portaria 15.01.0050552.2026 publicada em 29/06/2026 GSM Mineração\nData do evento: 2026-07-22\n[8] (data_evento | fato) 2026-07-22 e 14/02/2023';
  const com = (t: string) => ({ ...RESP_OK, contexto_documental: { texto: t, citacoes: [1] } });
  assertEquals(validarAnalise(JSON.stringify(com('O evento ocorreu em 22/07/2026.')), entrada, 8).ok, true);
  assertEquals(validarAnalise(JSON.stringify(com('A guia foi emitida em 2023-02-14.')), entrada, 8).ok, true);
  const errada = validarAnalise(JSON.stringify(com('O evento ocorreu em 23/07/2026.')), entrada, 8);
  assertEquals(errada.ok, false);
  assertStringIncludes(errada.erros.join(), 'numero_nao_encontrado_no_dossie');
  const deduzida = validarAnalise(JSON.stringify(com('A guia vence em 22/07/2029.')), entrada, 8);
  assertEquals(deduzida.ok, false);
});

Deno.test('validarAnalise: mais de 6 perguntas continua sendo recusado (o prompt V2 agora pede no máximo 6)', () => {
  const entrada = 'Portaria 15.01.0050552.2026 publicada em 29/06/2026 GSM Mineração';
  const sete = { ...RESP_OK, perguntas_redacao: Array.from({ length: 7 }, (_, i) => `Pergunta ${i + 1}?`) };
  assertStringIncludes(validarAnalise(JSON.stringify(sete), entrada, 2).erros.join(), 'perguntas_redacao_itens_demais');
});

Deno.test('prompts V2/V3: V1 e V2 congeladas e desativadas; V3 ativa, com o pré-release completo e o resto idêntico à V2', () => {
  for (const mod of ['M6', 'M8', 'M9A']) {
    const v1 = buscarPrompt(`${mod}_ANALISE_EDITORIAL_V1`)!; const v2 = buscarPrompt(`${mod}_ANALISE_EDITORIAL_V2`)!; const v3 = buscarPrompt(`${mod}_ANALISE_EDITORIAL_V3`)!;
    assertEquals(v1.ativo, false); assertEquals(v2.ativo, false); assertEquals(v3.ativo, true);
    for (const v of [v2, v3]) {
      assertStringIncludes(v.instructions, 'no máximo 6 itens');
      assertStringIncludes(v.instructions, 'no máximo 8 itens');
      assertStringIncludes(v.instructions, 'nunca calcule nem deduza datas');
      assertStringIncludes(v.instructions, 'Nunca invente');
      assertEquals(JSON.stringify(v.schema), JSON.stringify(v1.schema));
    }
    // V3: pré-release completo (90-120 palavras; o quê/onde/quando, fonte, providências, o que NÃO consta); sem "se couber"
    assertStringIncludes(v3.instructions, '90 a 120 palavras');
    assertStringIncludes(v3.instructions, 'o que aconteceu, onde');
    assertStringIncludes(v3.instructions, 'tipo e número do documento');
    assertStringIncludes(v3.instructions, 'providências adotadas');
    assertStringIncludes(v3.instructions, 'o documento NÃO informa');
    assertStringIncludes(v3.instructions, 'Copie números, datas e horários exatamente');
    assert(!v3.instructions.includes('se couber'));
    assertStringIncludes(v3.instructions, 'Não atribua score');                 // continua sem score/prioridade/liberar publicação
    // só o item (7) mudou: tirando-o, V2 e V3 são o mesmo texto
    const sem7 = (t: string) => t.replace(/\(7\) proposta_abordagem:.*?(?=Não atribua score)/s, '');
    assertEquals(sem7(v3.instructions), sem7(v2.instructions));
  }
});

Deno.test('validarAnalise: rascunho curto (<60 palavras) gera AVISO, não erro; rascunho completo não avisa', () => {
  const entrada = 'Comunicado de Acidente Ambiental nº 205/2026 da Semad, registrado em 06/10/2026 às 11h30 no km 452 da BR-259, em Gouveia';
  const curto = { ...RESP_OK, proposta_abordagem: { texto: 'Nota curta sobre a ocorrência, ouvindo a empresa.', rascunho_pre_release: 'Comunicado nº 205/2026 da Semad registra a ocorrência no km 452 da BR-259, em Gouveia.' } };
  const rc = validarAnalise(JSON.stringify(curto), entrada, 2);
  assert(rc.avisos.some((a) => a.startsWith('rascunho_pre_release_curto')), rc.avisos.join());
  assert(!rc.erros.some((e) => e.includes('rascunho')), rc.erros.join());
  const longo = 'Comunicado de Acidente Ambiental nº 205/2026 da Semad registra a ocorrência de 06/10/2026, às 11h30, no km 452 da BR-259, em Gouveia, onde parte da carga caiu na pista e no pátio de um posto. ' +
    'O aviso foi feito ao Núcleo de Emergência Ambiental no mesmo dia, e a área foi isolada. O transportador acionou empresa de pronto atendimento para o transbordo e a limpeza do local. ' +
    'O comunicado não identifica o produto transportado, a empresa responsável pelo transporte nem a extensão do material derramado, informações necessárias para verificar eventual relação com atividade minerária.';
  const ok = { ...RESP_OK, proposta_abordagem: { texto: 'Nota curta sobre a ocorrência, ouvindo a empresa.', rascunho_pre_release: longo } };
  const ro = validarAnalise(JSON.stringify(ok), entrada, 2);
  assert(!ro.avisos.some((a) => a.startsWith('rascunho_pre_release_curto')), ro.avisos.join());
});

Deno.test('prompt V1 desativado: pedir a V1 é recusado antes de qualquer custo', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas');
  const { deps, chamadas } = ambiente(m);
  await assertRejects(() => executarIA(deps, master, pedido(id, { prompt: 'M6_ANALISE_EDITORIAL_V1' })), Error, 'desativada');
  assertEquals(chamadas.length, 0);
});

Deno.test('evento com análise de IA já concluída não é cobrado de novo, mesmo em lote novo', async () => {
  const m = new Mem(); const id = novoEvento(m, 1, 'M6_outorgas', { ia_sucesso_previo: true });
  const { deps, chamadas } = ambiente(m);
  const r = await executarIA(deps, master, pedido(id));
  assertEquals(r.body.code, 'evento_ja_analisado');
  assertEquals(r.status, 409);
  assertEquals(chamadas.length, 0);
  assertEquals(m.reais().length, 0);
});

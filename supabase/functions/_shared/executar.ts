import { HttpError, isUuid, sanitizarErro } from './errors.ts';
import { exigirRole, resolverEmpresa } from './autorizacao.ts';
import type { Chamador } from './autorizacao.ts';
import { calcularCusto, estimarMaximo, verificarLimites } from './custo.ts';
import { decidirChamadaIA, hashChamada, hashEntrada, CAMPOS_PRE_IA } from './gate.ts';
import type { PreIa } from './gate.ts';
import { operacaoDe } from './operacoes.ts';
import type { Esforco } from './operacoes.ts';
import { buscarPrompt, idPrompt } from './prompts.ts';
import { sha256Hex } from './gate.ts';
import { obterSegredo } from './segredo.ts';
import type { Elegibilidade, Repo } from './types.ts';
import { LIMITE_MAX_LOTE, LOTE_PILOTO_ID, moduloCurto, montarEntrada, validarAnalise } from './analise.ts';

export interface ExecDeps {
  repo: Repo;
  getEnv: (n: string) => string | undefined;
  fetchFn: typeof fetch;
  now: () => Date;
  openaiUrl?: string;
  timeoutMs?: number;
}

export interface ExecInput {
  empresa_id?: unknown;
  carteira_id?: unknown;             // escopo obrigatório nas operações de módulo
  event_id?: unknown;                // UUID do evento (obrigatório nas operações de módulo)
  execucao_id?: unknown;             // UUID da execução/consulta do coletor (obrigatório nas operações de módulo)
  operacao?: unknown;
  modulo?: unknown;
  referencia_evento?: unknown;
  modelo?: unknown;
  payload?: unknown;
  // --- travas pré-IA ---
  prompt?: unknown;                  // nome versionado do prompt (ex.: M8_CLASSIFICACAO_V1)
  versao_regra?: unknown;            // versão da regra/score que gerou a entrada
  motivo_chamada?: unknown;
  status_evento?: unknown;
  hash_entrada?: unknown;            // hash calculado pelo coletor (informativo; o servidor recalcula o seu)
  reasoning_effort?: unknown;
  autorizacao_explicita?: unknown;   // exigida por operações de raciocínio médio
  pre_ia?: unknown;                  // resultado das etapas determinísticas (ver gate.ts)
  // --- operação assistida (analise_editorial) ---
  usar_api_real?: unknown;           // boolean OBRIGATÓRIO: false => nenhuma chamada paga (registra bloqueio)
  limite_ia?: unknown;               // inteiro 0..6 OBRIGATÓRIO: teto de chamadas reais do lote
}

export interface ExecOpts {
  somenteMaster?: boolean;   // chamadas vindas do painel Admin (teste de conexão / execução manual)
}

export interface ExecResultado { status: number; body: Record<string, unknown> }

const PROVIDER = 'openai';
const OPENAI_URL = 'https://api.openai.com/v1/responses';
const MODELO_RE = /^[A-Za-z0-9][A-Za-z0-9._:\-]{0,79}$/;
const TEXTO_RE = /^[\p{L}\p{N} _.:\-\/]{1,80}$/u;
const MAX_CHARS_PAYLOAD = 100_000;

interface MensagemIn { role: string; content: string }
interface PayloadOk { input: string | MensagemIn[]; instructions?: string; maxOutput: number; maxPedido: number | null; limitado: boolean; chars: number }

// Só repassamos ao provedor campos que conhecemos (lista branca). Isso impede que um
// usuário inclua "tools" pagas, outro modelo, "store", etc. dentro do payload.
export function validarPayload(p: unknown, tetoOperacao: number, aceitaInstructions: boolean): PayloadOk {
  if (!p || typeof p !== 'object' || Array.isArray(p)) {
    throw new HttpError(400, 'dados_invalidos', 'payload deve ser um objeto.');
  }
  const o = p as Record<string, unknown>;
  let chars = 0;
  let input: string | MensagemIn[];
  if (typeof o.input === 'string') {
    if (!o.input.trim()) throw new HttpError(400, 'dados_invalidos', 'payload.input vazio.');
    input = o.input; chars += o.input.length;
  } else if (Array.isArray(o.input) && o.input.length > 0 && o.input.length <= 50) {
    input = o.input.map((m) => {
      const mm = m as Record<string, unknown>;
      if (!mm || typeof mm.content !== 'string' || !['user', 'assistant', 'system', 'developer'].includes(String(mm.role))) {
        throw new HttpError(400, 'dados_invalidos', 'payload.input com mensagem inválida.');
      }
      chars += mm.content.length;
      return { role: String(mm.role), content: mm.content };
    });
  } else {
    throw new HttpError(400, 'dados_invalidos', 'payload.input é obrigatório (texto ou lista de mensagens).');
  }
  let instructions: string | undefined;
  if (o.instructions !== undefined && o.instructions !== null) {
    if (!aceitaInstructions) throw new HttpError(400, 'prompt_solto', 'Esta operação usa prompt versionado; não envie payload.instructions.');
    if (typeof o.instructions !== 'string') throw new HttpError(400, 'dados_invalidos', 'payload.instructions inválido.');
    instructions = o.instructions; chars += instructions.length;
  }
  // teto POR OPERAÇÃO: pedir mais que o teto = limitar ao teto (e registrar os dois valores)
  let maxOutput = tetoOperacao;
  let maxPedido: number | null = null;
  let limitado = false;
  if (o.max_output_tokens !== undefined && o.max_output_tokens !== null) {
    const n = Number(o.max_output_tokens);
    if (!Number.isInteger(n) || n < 1) throw new HttpError(400, 'dados_invalidos', 'max_output_tokens inválido.');
    maxPedido = n;
    if (n > tetoOperacao) limitado = true;
    maxOutput = Math.min(n, tetoOperacao);
  }
  if (chars > MAX_CHARS_PAYLOAD) throw new HttpError(413, 'payload_grande', 'Conteúdo grande demais.');
  return { input, instructions, maxOutput, maxPedido, limitado, chars };
}

function extrairTexto(j: Record<string, unknown>): string {
  const partes: string[] = [];
  const out = Array.isArray(j.output) ? j.output : [];
  for (const item of out as Array<Record<string, unknown>>) {
    if (item?.type === 'message' && Array.isArray(item.content)) {
      for (const c of item.content as Array<Record<string, unknown>>) {
        if (c?.type === 'output_text' && typeof c.text === 'string') partes.push(c.text);
      }
    }
  }
  return partes.join('');
}

const num = (v: unknown) => (typeof v === 'number' && isFinite(v) && v >= 0 ? Math.floor(v) : 0);

// Núcleo: valida -> autoriza -> GATE pré-IA -> configuração -> preço -> idempotência -> segredo ->
// limite -> chama a API -> registra. Sempre devolve {status, body}; nunca devolve a chave.
// Exceções de HttpError antes de existir contexto de empresa (400/403) não geram linha em api_execucoes.
const MOTIVO_RE = /^[\p{L}\p{N} _.:,;\-\/()]{1,200}$/u;
const VERSAO_RE = /^[A-Za-z0-9][A-Za-z0-9._\-:]{0,59}$/;
const STATUS_EVENTO_RE = /^[a-z0-9_]{1,40}$/;

function lerPreIa(v: unknown): PreIa {
  if (v === undefined || v === null) return {};
  if (typeof v !== 'object' || Array.isArray(v)) throw new HttpError(400, 'dados_invalidos', 'pre_ia inválido.');
  const o = v as Record<string, unknown>;
  const r: Record<string, boolean> = {};
  for (const k of Object.keys(o)) {
    if (!CAMPOS_PRE_IA.includes(k)) throw new HttpError(400, 'dados_invalidos', `pre_ia: campo desconhecido (${k.slice(0, 40)}).`);
    if (typeof o[k] !== 'boolean') throw new HttpError(400, 'dados_invalidos', `pre_ia.${k} deve ser verdadeiro/falso.`);
    r[k] = o[k] as boolean;
  }
  return r as PreIa;
}

async function executarIAInterno(
  deps: ExecDeps,
  ch: Chamador,
  input: ExecInput,
  opts: ExecOpts = {},
): Promise<ExecResultado> {
  // --- validação de entrada ---
  const operacao = typeof input.operacao === 'string' ? input.operacao.trim() : '';
  if (!TEXTO_RE.test(operacao)) throw new HttpError(400, 'dados_invalidos', 'operacao inválida.');
  const opCfg = operacaoDe(operacao);
  if (!opCfg) throw new HttpError(400, 'operacao_desconhecida', 'Operação não cadastrada em operacoes.ts (cada operação tem teto de tokens e esforço próprios).');
  let modulo: string | null = null;
  if (input.modulo !== undefined && input.modulo !== null && input.modulo !== '') {
    if (typeof input.modulo !== 'string' || !TEXTO_RE.test(input.modulo)) throw new HttpError(400, 'dados_invalidos', 'modulo inválido.');
    modulo = input.modulo;
  }
  let modeloPedido: string | null = null;
  if (input.modelo !== undefined && input.modelo !== null && input.modelo !== '') {
    if (typeof input.modelo !== 'string' || !MODELO_RE.test(input.modelo)) throw new HttpError(400, 'dados_invalidos', 'modelo inválido.');
    modeloPedido = input.modelo;
  }
  const porDossie = opCfg.dossie_servidor === true;
  // operações de módulo da operação assistida: a entrada é montada NO SERVIDOR (o payload do navegador é ignorado)
  let payload: PayloadOk = porDossie
    ? { input: '', maxOutput: opCfg.max_output_tokens, maxPedido: null, limitado: false, chars: 0 }
    : validarPayload(input.payload, opCfg.max_output_tokens, opCfg.texto_livre);
  let usarApiReal = true;
  let limiteIa = 0;
  if (porDossie) {
    if (typeof input.usar_api_real !== 'boolean') throw new HttpError(400, 'usar_api_real_obrigatorio', 'Informe usar_api_real (verdadeiro/falso).');
    usarApiReal = input.usar_api_real;
    if (!Number.isInteger(input.limite_ia) || (input.limite_ia as number) < 0) throw new HttpError(400, 'limite_ia_obrigatorio', 'Informe limite_ia (inteiro de 0 a 6).');
    if ((input.limite_ia as number) > LIMITE_MAX_LOTE) throw new HttpError(400, 'limite_ia_maximo', `limite_ia máximo é ${LIMITE_MAX_LOTE}.`);
    limiteIa = input.limite_ia as number;
  }

  // prompt versionado (operações de módulo) — nunca texto solto
  let promptReg = null as ReturnType<typeof buscarPrompt>;
  let versaoPrompt: string;
  if (opCfg.texto_livre) {
    versaoPrompt = `TESTE_${opCfg.nome.toUpperCase()}_V1`;
  } else {
    if (typeof input.prompt !== 'string') throw new HttpError(400, 'prompt_obrigatorio', 'Informe o prompt versionado (ex.: M8_CLASSIFICACAO_V1).');
    promptReg = buscarPrompt(input.prompt);
    if (!promptReg) throw new HttpError(400, 'prompt_desconhecido', 'Prompt não encontrado no registro versionado.');
    if (!promptReg.ativo) throw new HttpError(400, 'prompt_inativo', 'Esta versão de prompt está desativada.');
    if (promptReg.operacao !== operacao) throw new HttpError(400, 'prompt_incompativel', 'O prompt não pertence a esta operação.');
    if (modulo && promptReg.modulo !== modulo) throw new HttpError(400, 'prompt_incompativel', 'O prompt não pertence a este módulo.');
    versaoPrompt = idPrompt(promptReg);
  }

  // esforço de raciocínio explícito (nunca o default silêncioso do modelo)
  let esforco: Esforco = opCfg.esforco_padrao;
  if (input.reasoning_effort !== undefined && input.reasoning_effort !== null && input.reasoning_effort !== '') {
    if (!opCfg.esforcos_permitidos.includes(input.reasoning_effort as Esforco)) {
      throw new HttpError(400, 'esforco_nao_permitido', `Esforço de raciocínio não permitido para ${opCfg.nome}.`);
    }
    esforco = input.reasoning_effort as Esforco;
  }

  let versaoRegra: string | null = null;
  if (!porDossie && input.versao_regra !== undefined && input.versao_regra !== null && input.versao_regra !== '') {
    if (typeof input.versao_regra !== 'string' || !VERSAO_RE.test(input.versao_regra)) throw new HttpError(400, 'dados_invalidos', 'versao_regra inválida.');
    versaoRegra = input.versao_regra;
  }
  let motivoChamada: string | null = null;
  if (input.motivo_chamada !== undefined && input.motivo_chamada !== null && input.motivo_chamada !== '') {
    if (typeof input.motivo_chamada !== 'string' || !MOTIVO_RE.test(input.motivo_chamada)) throw new HttpError(400, 'dados_invalidos', 'motivo_chamada inválido.');
    motivoChamada = input.motivo_chamada;
  }
  let statusEvento: string | null = null;
  if (input.status_evento !== undefined && input.status_evento !== null && input.status_evento !== '') {
    if (typeof input.status_evento !== 'string' || !STATUS_EVENTO_RE.test(input.status_evento)) throw new HttpError(400, 'dados_invalidos', 'status_evento inválido.');
    statusEvento = input.status_evento;
  }
  let preIa = lerPreIa(input.pre_ia);

  // --- autorização ---
  if (opts.somenteMaster || opCfg.so_master) exigirRole(ch, ['master']);
  else exigirRole(ch, ['master', 'admin']);
  if (opCfg.exige_autorizacao_explicita && input.autorizacao_explicita !== true) {
    throw new HttpError(403, 'autorizacao_explicita_necessaria', 'Esta operação exige autorizacao_explicita=true.');
  }
  const empresaId = resolverEmpresa(ch, input.empresa_id);
  const empresa = await deps.repo.getEmpresa(empresaId);
  if (!empresa || empresa.ativa === false) {
    // para não-master o id já é o próprio; para master é um UUID inexistente/inativo
    throw new HttpError(ch.perfil.role === 'master' ? 404 : 403, ch.perfil.role === 'master' ? 'empresa_nao_encontrada' : 'sem_permissao',
      ch.perfil.role === 'master' ? 'Empresa não encontrada ou inativa.' : 'Sem acesso à empresa.');
  }

  // --- ESCOPO DA CONSULTA: empresa + carteira + evento + execução têm que ser da MESMA empresa ---
  // (o banco repete esta regra com FK composta/trigger/RLS; aqui ela barra ANTES de qualquer custo)
  const negarEscopo = async (code: string, entidade: string, entidadeId: string | null): Promise<never> => {
    try {
      await deps.repo.insertAuditoria({ usuario_id: ch.userId, empresa_id: empresaId, acao: 'consulta_bloqueada_escopo', entidade, entidade_id: entidadeId, valor_novo: { code, operacao } });
    } catch { /* a recusa não depende da auditoria */ }
    throw new HttpError(403, code, 'Escopo da consulta inválido para esta empresa.');
  };
  let carteiraId: string | null = null;
  let eventId: string | null = null;
  let consultaId: string | null = null;
  let eventoRef: string | null = null;
  const exigeEscopo = !opCfg.texto_livre;
  for (const [campo, valor] of [['carteira_id', input.carteira_id], ['event_id', input.event_id], ['execucao_id', input.execucao_id]] as const) {
    const informado = valor !== undefined && valor !== null && valor !== '';
    if (!informado && exigeEscopo) throw new HttpError(400, `${campo}_obrigatorio`, `Informe ${campo}: toda chamada de IA carrega empresa_id, carteira_id, event_id e execucao_id.`);
    if (informado && !isUuid(valor)) throw new HttpError(400, 'dados_invalidos', `${campo} inválido.`);
  }
  if (input.carteira_id) {
    carteiraId = String(input.carteira_id).toLowerCase();
    const c = await deps.repo.getCarteira(carteiraId);
    if (!c || c.empresa_id !== empresaId) await negarEscopo('carteira_nao_pertence_a_empresa', 'carteira', carteiraId);
    if (c && c.ativa === false) throw new HttpError(409, 'carteira_inativa', 'A carteira está inativa.');
  }
  if (input.event_id) {
    eventId = String(input.event_id).toLowerCase();
    const ev = await deps.repo.getEvento(eventId);
    if (!ev || ev.empresa_id !== empresaId) await negarEscopo('evento_de_outra_empresa', 'evento', eventId);
    if (ev && ev.carteira_id && carteiraId && ev.carteira_id !== carteiraId) await negarEscopo('evento_de_outra_carteira', 'evento', eventId);
  }
  if (input.execucao_id) {
    consultaId = String(input.execucao_id).toLowerCase();
    const ex = await deps.repo.getConsulta(consultaId);
    if (!ex || ex.empresa_id !== empresaId) await negarEscopo('execucao_de_outra_empresa', 'execucao', consultaId);
    if (ex && ex.carteira_id && carteiraId && ex.carteira_id !== carteiraId) await negarEscopo('execucao_de_outra_carteira', 'execucao', consultaId);
  }
  // --- OPERAÇÃO ASSISTIDA: elegibilidade pré-IA e dossiê vêm do BANCO (nunca do navegador) ---
  let elegibilidade: Elegibilidade | null = null;
  let nEvidencias = 0;
  if (porDossie) {
    const [elig, dos] = [await deps.repo.getElegibilidade(eventId as string), await deps.repo.getDossie(eventId as string)];
    if (!elig.encontrado || !dos) throw new HttpError(404, 'evento_nao_encontrado', 'Evento não encontrado.');
    elegibilidade = elig;
    const modEv = moduloCurto(elig.modulo);
    if (!modEv) throw new HttpError(400, 'modulo_nao_suportado', 'Este módulo não participa da operação assistida.');
    if (modulo && modulo !== modEv) throw new HttpError(400, 'modulo_incompativel_com_evento', 'O módulo informado não é o do evento.');
    modulo = modEv;
    if (promptReg && promptReg.modulo !== modEv) throw new HttpError(400, 'prompt_incompativel', 'O prompt não pertence ao módulo do evento.');
    if (elig.execucao_criacao_id && consultaId !== elig.execucao_criacao_id) {
      throw new HttpError(400, 'execucao_nao_e_a_do_evento', 'execucao_id deve ser a execução que criou o evento.');
    }
    const entrada = montarEntrada(dos);
    nEvidencias = dos.evidencias.length;
    payload = { input: entrada, maxOutput: opCfg.max_output_tokens, maxPedido: null, limitado: false, chars: entrada.length };
    versaoRegra = `${elig.regra_pre_ia ?? 'PRE_IA'}:${elig.score_antes?.versao_score ?? 'SEM_SCORE'}`.slice(0, 59);
    // o servidor decide a elegibilidade; o navegador só pode ADICIONAR motivos de dispensa, nunca remover
    const srv: Record<string, boolean> = { ...(elig.flags ?? {}) };
    if (elig.revisao_humana !== 'Pendente') srv.fora_de_escopo = true;   // a IA só atua antes da revisão humana
    preIa = { ...preIa, ...srv } as PreIa;
  }
  const hashIn = await hashEntrada(payload.input);
  const meta: Record<string, unknown> = {
    payload_chars: payload.chars, max_output_tokens: payload.maxOutput, max_output_tokens_pedido: payload.maxPedido,
    max_output_tokens_limitado: payload.limitado, reasoning_effort: esforco,
  };
  if (promptReg) { meta.prompt = versaoPrompt; meta.prompt_sha256 = await sha256Hex(promptReg.instructions + JSON.stringify(promptReg.schema)); }
  if (statusEvento) meta.status_evento = statusEvento;
  if (typeof input.hash_entrada === 'string' && /^[a-f0-9]{16,128}$/i.test(input.hash_entrada)) meta.hash_entrada_origem = input.hash_entrada.toLowerCase();
  if (Object.keys(preIa).length) meta.pre_ia = preIa;
  if (porDossie && elegibilidade) {
    meta.lote_id = LOTE_PILOTO_ID;
    meta.limite_ia = limiteIa;
    meta.usar_api_real = usarApiReal;
    meta.evidencias_enviadas = nEvidencias;
    meta.elegibilidade = {
      regra_pre_ia: elegibilidade.regra_pre_ia ?? null, elegivel: elegibilidade.elegivel, flags: elegibilidade.flags, evidencias: elegibilidade.evidencias ?? 0,
      faixa_vinculo: elegibilidade.faixa_vinculo ?? null, score_antes: elegibilidade.score_antes ?? null, status_evento: elegibilidade.status_editorial ?? null,
    };
  }
  if (input.referencia_evento !== undefined && input.referencia_evento !== null && input.referencia_evento !== '') {
    meta.referencia_evento = String(input.referencia_evento).slice(0, 120);   // texto de apoio; a identidade é event_id
  }
  eventoRef = eventId;
  if (opts.somenteMaster) meta.origem = 'painel_admin';

  const base = {
    empresa_id: empresaId, usuario_id: ch.userId, provider: PROVIDER, operacao, modulo, event_id: eventId, carteira_id: carteiraId, execucao_id: consultaId,
    hash_entrada: hashIn, versao_prompt: versaoPrompt, versao_regra: versaoRegra, reasoning_effort: esforco,
    motivo_chamada: motivoChamada ?? `${modulo ?? 'sem_modulo'}:${operacao}`,
  };

  // Registra um bloqueio (sem chamar o provedor) mantendo SEMPRE o empresa_id.
  const bloquear = async (status: 'bloqueado_config' | 'bloqueado_limite' | 'bloqueado_pre_ia', http: number, code: string, msg: string, modelo: string | null, detalhe?: Record<string, unknown>): Promise<ExecResultado> => {
    const { id } = await deps.repo.insertExecucao({ ...base, modelo, status, erro: msg, motivo_bloqueio: code, metadata: { ...meta, ...(detalhe || {}) } });
    return { status: http, body: { ok: false, code, message: msg, execucao_id: id, chamou_provider: false } };
  };

  // --- GATE PRÉ-IA (1ª passada: só as etapas determinísticas que o chamador já executou) ---
  const gateEntrada = {
    empresa_id: empresaId, modulo, event_id: eventoRef, operacao, hash_entrada: hashIn,
    versao_regra: versaoRegra, versao_prompt: versaoPrompt, status_evento: statusEvento, pre_ia: preIa,
  };
  const d1 = decidirChamadaIA(gateEntrada);
  if (d1.acao === 'bloquear') {
    return bloquear('bloqueado_pre_ia', 200, `pre_ia_${d1.motivo}`, 'Chamada de IA dispensada: nenhum token foi gasto.', null, { gate: d1.motivo });
  }

  // --- operação assistida: sem usar_api_real=true NENHUMA chamada paga (registra e conta como evitada) ---
  if (porDossie && !usarApiReal) {
    return bloquear('bloqueado_config', 409, 'usar_api_real_desligado', 'usar_api_real=false: nenhuma chamada paga foi feita.', null);
  }
  if (porDossie && limiteIa === 0) {
    return bloquear('bloqueado_limite', 409, 'limite_ia_zero', 'limite_ia=0: nenhuma chamada paga foi feita.', null);
  }

  // --- configuração da empresa ---
  const cfg = await deps.repo.getConfig(empresaId, PROVIDER);
  if (!cfg) return bloquear('bloqueado_config', 409, 'api_nao_configurada', 'A API não está configurada para esta empresa.', modeloPedido);
  if (!cfg.ativo) return bloquear('bloqueado_config', 409, 'api_pausada', 'A API está pausada para esta empresa.', modeloPedido);

  const modelo = modeloPedido || cfg.modelo_padrao;
  if (!modelo) return bloquear('bloqueado_config', 409, 'modelo_nao_definido', 'Nenhum modelo definido para esta empresa.', null);

  const agora = deps.now();
  const preco = await deps.repo.getPreco(PROVIDER, modelo, agora);
  if (!preco) return bloquear('bloqueado_config', 409, 'modelo_sem_preco', 'Este modelo não tem preço cadastrado; cadastre antes de usar.', modelo);

  // --- idempotência do Radar (2ª passada do gate): mesma entrada+regra+prompt+modelo+esforço ---
  const hashCh = await hashChamada({
    empresa_id: empresaId, carteira_id: carteiraId, evento: eventoRef, operacao, hash_entrada: hashIn, versao_regra: versaoRegra,
    versao_prompt: versaoPrompt, modelo, reasoning_effort: esforco,
  });
  const anterior = await deps.repo.buscarSucessoPorHash(empresaId, hashCh);
  const d2 = decidirChamadaIA(gateEntrada, anterior ? { id: anterior.id } : null);
  if (d2.acao === 'reutilizar' && anterior) {
    const { id: reusoId } = await deps.repo.insertExecucao({
      ...base, modelo: anterior.modelo ?? modelo, status: 'reutilizado', hash_chamada: hashCh,
      reutilizado_de_execucao_id: anterior.id, custo_estimado_usd: 0, data_fim: deps.now().toISOString(),
      input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0,
      metadata: { ...meta, origem_resultado: 'cache_interno' },
    });
    return {
      status: 200,
      body: {
        ok: true, execucao_id: reusoId, reutilizado_de_execucao_id: anterior.id, origem: 'cache_interno', chamou_provider: false,
        empresa_id: empresaId, provider: PROVIDER, modelo: anterior.modelo ?? modelo, texto: anterior.resposta_texto ?? '',
        uso: { input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0 },
        custo_estimado_usd: 0, latencia_ms: 0, request_id_provider: null,
      },
    };
  }

  // --- teto do lote: no máximo `limite_ia` (≤ 6) chamadas reais, 1 por evento, sem repetição de erro ---
  if (porDossie) {
    const lote = await deps.repo.estadoLote(empresaId, LOTE_PILOTO_ID, eventId);
    if (lote.evento_ja_chamado) {
      return bloquear('bloqueado_limite', 409, 'evento_ja_chamado_no_lote', 'Este evento já teve a sua chamada neste lote (sem nova tentativa automática).', modelo, { lote });
    }
    if (lote.total >= Math.min(limiteIa, LIMITE_MAX_LOTE)) {
      return bloquear('bloqueado_limite', 429, 'limite_ia_do_lote', `Limite de ${Math.min(limiteIa, LIMITE_MAX_LOTE)} chamadas reais do lote atingido.`, modelo, { lote });
    }
  }

  const segredo = await obterSegredo(cfg, deps.getEnv, (n) => deps.repo.lerChave(n));
  if (!segredo.valor) {
    return bloquear('bloqueado_config', 409, 'credencial_ausente', 'Chave da API não cadastrada (ADMIN > API).', modelo, { segredo_nome: segredo.nome });
  }

  // --- limites (consumo atual + estimativa pessimista desta chamada) ---
  const consumo = await deps.repo.getConsumoLimites(empresaId);
  const est = estimarMaximo(payload.chars + (promptReg ? promptReg.instructions.length : 0), payload.maxOutput, preco);
  const violacoes = verificarLimites(cfg, consumo, est);
  if (violacoes.length) {
    return bloquear('bloqueado_limite', 429, 'limite_atingido', 'Limite de consumo da empresa atingido.', modelo,
      { violacoes, consumo, estimativa: est });
  }

  // --- execução ---
  let execId: string;
  try {
    execId = (await deps.repo.insertExecucao({ ...base, modelo, status: 'pendente', hash_chamada: hashCh, metadata: meta })).id;
  } catch (e) {
    // a trava do BANCO (trigger) é a última defesa do teto: se ela recusar, nada foi cobrado
    const m = e instanceof Error ? e.message : '';
    const g = /(limite_ia_do_lote_atingido|evento_ja_chamado_no_lote|analise_editorial_exige_lote)/.exec(m);
    if (porDossie && g) return bloquear('bloqueado_limite', 429, g[1], 'A trava de segurança do banco recusou a chamada: nenhum token foi gasto.', modelo, { origem_bloqueio: 'trigger_banco' });
    throw e;
  }
  const t0 = Date.now();
  const corpo: Record<string, unknown> = { model: modelo, input: payload.input, max_output_tokens: payload.maxOutput, store: false, reasoning: { effort: esforco } };
  const instrucoes = promptReg ? promptReg.instructions : payload.instructions;
  if (instrucoes) corpo.instructions = instrucoes;
  if (promptReg) corpo.text = { format: { type: 'json_schema', name: promptReg.nome.toLowerCase(), schema: promptReg.schema, strict: true } };

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), deps.timeoutMs ?? 60_000);
  try {
    let resp: Response;
    try {
      resp = await deps.fetchFn(deps.openaiUrl || OPENAI_URL, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${segredo.valor}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(corpo),
        signal: ctrl.signal,
      });
    } catch (e) {
      const lat = Date.now() - t0;
      const msg = sanitizarErro(ctrl.signal.aborted ? 'Tempo excedido ao chamar o provedor.' : (e instanceof Error ? e.message : 'falha de rede'), [segredo.valor]);
      await deps.repo.updateExecucao(execId, { status: 'erro', data_fim: deps.now().toISOString(), latencia_ms: lat, erro: msg });
      return { status: 502, body: { ok: false, code: 'erro_provider', message: 'Falha ao chamar o provedor de IA.', execucao_id: execId, chamou_provider: true } };
    }

    const lat = Date.now() - t0;
    const requestId = resp.headers.get('x-request-id');
    let j: Record<string, unknown> = {};
    try { j = await resp.json(); } catch { /* corpo não-JSON */ }

    if (!resp.ok) {
      const e = (j.error ?? {}) as Record<string, unknown>;
      const msg = sanitizarErro(`HTTP ${resp.status}: ${typeof e.message === 'string' ? e.message : 'erro do provedor'}`, [segredo.valor]);
      await deps.repo.updateExecucao(execId, {
        status: 'erro', data_fim: deps.now().toISOString(), latencia_ms: lat, erro: msg, request_id_provider: requestId,
      });
      // não repassa a mensagem crua do provedor ao navegador
      const http = resp.status === 429 ? 429 : 502;
      return { status: http, body: { ok: false, code: 'erro_provider', message: `O provedor de IA recusou a chamada (HTTP ${resp.status}).`, execucao_id: execId, request_id_provider: requestId, chamou_provider: true } };
    }

    const u = (j.usage ?? {}) as Record<string, unknown>;
    const det = (u.input_tokens_details ?? {}) as Record<string, unknown>;
    const detSaida = (u.output_tokens_details ?? {}) as Record<string, unknown>;
    const uso = {
      input_tokens: num(u.input_tokens),
      cached_input_tokens: num(det.cached_tokens),
      output_tokens: num(u.output_tokens),
      reasoning_tokens: num(detSaida.reasoning_tokens),
      total_tokens: 0,
    };
    uso.total_tokens = num(u.total_tokens) || uso.input_tokens + uso.output_tokens;
    const custo = calcularCusto(uso, preco);
    const texto = extrairTexto(j);
    const modeloEfetivo = typeof j.model === 'string' ? j.model : modelo;

    // Operação assistida: a resposta só vale se passar na validação. Inválida => 'erro' (a chamada foi paga e
    // fica contada), resposta bruta preservada para auditoria, nenhuma promoção de status.
    if (porDossie) {
      const incompleta = j.status === 'incomplete';
      const v = incompleta ? { ok: false, erros: ['resposta_incompleta'], avisos: [] as string[], analise: undefined } : validarAnalise(texto, typeof payload.input === 'string' ? payload.input : '', nEvidencias);
      if (!v.ok) {
        const resumoErro = `resposta_invalida: ${v.erros.slice(0, 6).join('; ')}`.slice(0, 480);
        await deps.repo.updateExecucao(execId, {
          status: 'erro', data_fim: deps.now().toISOString(), latencia_ms: lat, modelo: modeloEfetivo,
          request_id_provider: requestId, pricing_id: preco.id, ...uso, custo_estimado_usd: custo, resposta_texto: texto, erro: resumoErro,
          metadata: { ...meta, resposta_chars: texto.length, validacao: { ok: false, erros: v.erros, avisos: v.avisos } },
        });
        return {
          status: 200,
          body: {
            ok: false, code: 'resposta_invalida', message: 'A IA respondeu, mas a resposta não passou na validação; nada foi promovido.',
            erros: v.erros, execucao_id: execId, chamou_provider: true, modelo: modeloEfetivo, uso, custo_estimado_usd: custo, latencia_ms: lat, request_id_provider: requestId,
          },
        };
      }
      await deps.repo.updateExecucao(execId, {
        status: 'sucesso', data_fim: deps.now().toISOString(), latencia_ms: lat, modelo: modeloEfetivo,
        request_id_provider: requestId, pricing_id: preco.id, ...uso, custo_estimado_usd: custo, resposta_texto: texto,
        metadata: { ...meta, resposta_chars: texto.length, validacao: { ok: true, erros: [], avisos: v.avisos }, revisao_humana: 'Pendente' },
      });
      return {
        status: 200,
        body: {
          ok: true, execucao_id: execId, empresa_id: empresaId, provider: PROVIDER, modelo: modeloEfetivo, origem: 'provider', chamou_provider: true,
          resposta: v.analise, validacao: { ok: true, avisos: v.avisos }, revisao_humana: 'Pendente',
          uso, custo_estimado_usd: custo, latencia_ms: lat, request_id_provider: requestId,
        },
      };
    }

    await deps.repo.updateExecucao(execId, {
      status: 'sucesso', data_fim: deps.now().toISOString(), latencia_ms: lat, modelo: modeloEfetivo,
      request_id_provider: requestId, pricing_id: preco.id, ...uso, custo_estimado_usd: custo, resposta_texto: texto,
      metadata: { ...meta, resposta_chars: texto.length },
    });
    return {
      status: 200,
      body: {
        ok: true, execucao_id: execId, empresa_id: empresaId, provider: PROVIDER, modelo, origem: 'provider', chamou_provider: true,
        texto, uso, custo_estimado_usd: custo, latencia_ms: lat, request_id_provider: requestId,
      },
    };
  } catch (e) {
    // qualquer falha inesperada depois de criar a linha: não deixar "pendente"
    try {
      await deps.repo.updateExecucao(execId, { status: 'erro', data_fim: deps.now().toISOString(), latencia_ms: Date.now() - t0, erro: sanitizarErro(e instanceof Error ? e.message : 'erro', [segredo.valor]) });
    } catch { /* melhor esforço */ }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}


// Envolve o núcleo: nas operações assistidas, TODO desfecho (sucesso, erro, bloqueio) recalcula execucoes.totais.
export async function executarIA(deps: ExecDeps, ch: Chamador, input: ExecInput, opts: ExecOpts = {}): Promise<ExecResultado> {
  const op = typeof input.operacao === 'string' ? operacaoDe(input.operacao.trim()) : null;
  const atualizar = async (execucaoId: unknown) => {
    if (!op?.dossie_servidor || !isUuid(execucaoId)) return;
    try { await deps.repo.atualizarTotais(String(execucaoId).toLowerCase()); } catch { /* totais são melhor-esforço: nunca derrubam a resposta */ }
  };
  let r: ExecResultado;
  try {
    r = await executarIAInterno(deps, ch, input, opts);
  } catch (e) {
    if (e instanceof HttpError && e.status < 500) throw e;   // recusas antes de existir linha em api_execucoes
    await atualizar(input.execucao_id);
    throw e;
  }
  if (r.body.execucao_id) await atualizar(input.execucao_id);
  return r;
}

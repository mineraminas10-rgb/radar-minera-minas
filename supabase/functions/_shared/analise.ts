// Operação assistida (analise_editorial): entrada montada no servidor + validação da resposta.
// Tudo aqui é puro (sem rede/banco) para ser testado por inteiro.
import { exigirMaster } from './autorizacao.ts';
import type { Chamador } from './autorizacao.ts';
import { HttpError, isUuid } from './errors.ts';
import type { Dossie, Elegibilidade, Repo } from './types.ts';

// Lote fixo do piloto: o navegador NÃO escolhe (um lote novo por requisição burlaria o teto).
// Para um novo lote de testes, troque este valor num deploy — nunca por parâmetro.
export const LOTE_PILOTO_ID = 'PILOTO_M6_M8_M9A_2026_10_R2';
export const LIMITE_MAX_LOTE = 6;

// 'M8_acidentes_ambientais' -> 'm8'; 'M9A_anm_movimentacoes' -> 'm9a'; 'M6_outorgas' -> 'm6'
export function moduloCurto(moduloEnum: string | undefined | null): string | null {
  const m = /^(M\d+[A-Z]?)_/.exec(String(moduloEnum ?? ''));
  return m ? m[1].toLowerCase() : null;
}

const ROTULOS: Array<[string, string]> = [
  ['tipo_evento', 'Tipo do evento'], ['titulo_fato', 'Título do fato'], ['resumo_factual', 'Resumo factual'], ['empresa', 'Empresa/titular'],
  ['cnpj', 'CNPJ'], ['municipio', 'Município'], ['atividade', 'Atividade'], ['decisao', 'Decisão'], ['processo', 'Processo/portaria'],
  ['data_evento', 'Data do evento'], ['data_publicacao', 'Data de publicação'], ['estrutura', 'Estrutura'], ['instrumento', 'Instrumento'],
  ['empreendimento', 'Empreendimento'], ['url_oficial', 'URL oficial'],
];

// Texto enviado ao provedor. Não inclui score/prioridade (a IA não os vê nem os altera).
export function montarEntrada(d: Dossie): string {
  const linhas: string[] = ['DOSSIÊ DO EVENTO (única fonte permitida)', `Evento: ${d.id_evento}`, `Módulo: ${d.modulo}`, '', 'CAMPOS DO EVENTO'];
  for (const [k, rot] of ROTULOS) {
    const v = d.evento?.[k];
    if (v !== null && v !== undefined && String(v).trim() !== '') linhas.push(`- ${rot}: ${String(v).trim()}`);
  }
  linhas.push('', 'EVIDÊNCIAS NUMERADAS');
  for (const e of d.evidencias) {
    const meta = [e.campo, e.tipo, e.pagina_secao].filter((x) => x).join(' | ');
    linhas.push(`[${e.n}] (${meta}) ${String(e.trecho).replace(/\s+/g, ' ').trim()}`);
  }
  return linhas.join('\n');
}

// ---------------------------------------------------------------------------------------------
// Validação da resposta. Inválida => a chamada vira 'erro' (resposta bruta preservada), nada é promovido.
// ---------------------------------------------------------------------------------------------
export interface Analise {
  fato_confirmado: { texto: string; citacoes: number[] };
  contexto_documental: { texto: string; citacoes: number[] };
  avaliacao_editorial: { texto: string };
  hipotese_apuracao: { texto: string };
  lacunas: string[];
  perguntas_redacao: string[];
  proposta_abordagem: { texto: string; rascunho_pre_release: string | null };
}
export interface Validacao { ok: boolean; erros: string[]; avisos: string[]; analise?: Analise }

const MAX_TEXTO = 1500;
const MAX_ITEM = 300;
const MAX_RASCUNHO = 1200;
const CHAVES_RAIZ = ['fato_confirmado', 'contexto_documental', 'avaliacao_editorial', 'hipotese_apuracao', 'lacunas', 'perguntas_redacao', 'proposta_abordagem'];

const ehObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const mesmasChaves = (o: Record<string, unknown>, esperadas: string[]) =>
  Object.keys(o).length === esperadas.length && esperadas.every((k) => Object.prototype.hasOwnProperty.call(o, k));

// números "relevantes": com 3+ dígitos, ou com separador (datas, processos, valores)
const NUM_RE = /\d[\d.,/-]*\d|\d{3,}/g;
const soDigitos = (t: string) => t.replace(/\D/g, '');

export function validarAnalise(textoBruto: string, entradaTexto: string, nEvidencias: number): Validacao {
  const erros: string[] = [];
  const avisos: string[] = [];
  let j: unknown;
  try { j = JSON.parse(textoBruto); } catch { return { ok: false, erros: ['json_invalido'], avisos }; }
  if (!ehObj(j)) return { ok: false, erros: ['json_nao_e_objeto'], avisos };
  if (!mesmasChaves(j, CHAVES_RAIZ)) {
    const faltam = CHAVES_RAIZ.filter((k) => !(k in j));
    const sobram = Object.keys(j).filter((k) => !CHAVES_RAIZ.includes(k));
    return { ok: false, erros: [`secoes_diferentes_do_schema(faltam:${faltam.join(',') || '-'};sobram:${sobram.join(',') || '-'})`], avisos };
  }

  const texto = (v: unknown, nome: string, min: number, max = MAX_TEXTO): string => {
    if (typeof v !== 'string') { erros.push(`${nome}_nao_e_texto`); return ''; }
    const t = v.trim();
    if (t.length < min) erros.push(`${nome}_vazio`);
    if (t.length > max) erros.push(`${nome}_longo_demais`);
    return t;
  };
  const lista = (v: unknown, nome: string, min: number, max: number): string[] => {
    if (!Array.isArray(v)) { erros.push(`${nome}_nao_e_lista`); return []; }
    if (v.length < min) erros.push(`${nome}_sem_itens`);
    if (v.length > max) erros.push(`${nome}_itens_demais`);
    return v.map((x, i) => {
      if (typeof x !== 'string' || !x.trim()) { erros.push(`${nome}[${i}]_invalido`); return ''; }
      if (x.length > MAX_ITEM) erros.push(`${nome}[${i}]_longo_demais`);
      return x.trim();
    });
  };
  const cit = (v: unknown, nome: string, obrigatoria: boolean): number[] => {
    if (!Array.isArray(v)) { erros.push(`${nome}_citacoes_nao_e_lista`); return []; }
    const out: number[] = [];
    for (const n of v) {
      if (!Number.isInteger(n) || (n as number) < 1 || (n as number) > nEvidencias) { erros.push(`${nome}_citacao_inexistente(${String(n).slice(0, 12)})`); continue; }
      if (!out.includes(n as number)) out.push(n as number);
    }
    if (obrigatoria && out.length === 0) erros.push(`${nome}_sem_citacao`);
    return out;
  };

  const sec = (k: string, esperadas: string[]): Record<string, unknown> => {
    const o = j[k];
    if (!ehObj(o) || !mesmasChaves(o, esperadas)) { erros.push(`${k}_estrutura_invalida`); return {}; }
    return o;
  };
  const fc = sec('fato_confirmado', ['texto', 'citacoes']);
  const cd = sec('contexto_documental', ['texto', 'citacoes']);
  const ae = sec('avaliacao_editorial', ['texto']);
  const ha = sec('hipotese_apuracao', ['texto']);
  const pa = sec('proposta_abordagem', ['texto', 'rascunho_pre_release']);

  const analise: Analise = {
    fato_confirmado: { texto: texto(fc.texto, 'fato_confirmado', 20), citacoes: cit(fc.citacoes, 'fato_confirmado', true) },
    contexto_documental: { texto: texto(cd.texto, 'contexto_documental', 1), citacoes: cit(cd.citacoes, 'contexto_documental', false) },
    avaliacao_editorial: { texto: texto(ae.texto, 'avaliacao_editorial', 10) },
    hipotese_apuracao: { texto: texto(ha.texto, 'hipotese_apuracao', 10) },
    lacunas: lista(j.lacunas, 'lacunas', 1, 8),
    perguntas_redacao: lista(j.perguntas_redacao, 'perguntas_redacao', 1, 6),
    proposta_abordagem: { texto: texto(pa.texto, 'proposta_abordagem', 10), rascunho_pre_release: null },
  };
  if (pa.rascunho_pre_release === null || pa.rascunho_pre_release === undefined) {
    analise.proposta_abordagem.rascunho_pre_release = null;
  } else {
    analise.proposta_abordagem.rascunho_pre_release = texto(pa.rascunho_pre_release, 'rascunho_pre_release', 1, MAX_RASCUNHO);
  }
  if (analise.contexto_documental.texto && analise.contexto_documental.citacoes.length === 0) avisos.push('contexto_documental_sem_citacao');

  // Anti-invenção: todo número/data das seções FACTUAIS (e do rascunho) precisa existir no dossiê enviado.
  const numerosDoDossie: string[] = (entradaTexto.match(NUM_RE) ?? []).map(soDigitos).filter((d) => d.length > 0);
  // Uma data do dossiê vale nos dois formatos: aaaa-mm-dd (ISO) e dd/mm/aaaa. Só o formato muda; dia, mês e ano têm que ser os mesmos.
  for (const m of entradaTexto.matchAll(/(\d{4})-(\d{2})-(\d{2})/g)) numerosDoDossie.push(`${m[3]}${m[2]}${m[1]}`);
  for (const m of entradaTexto.matchAll(/(\d{2})\/(\d{2})\/(\d{4})/g)) numerosDoDossie.push(`${m[3]}${m[2]}${m[1]}`);
  const existe = (dig: string) => numerosDoDossie.some((n) => n.includes(dig));
  for (const [nome, t] of [
    ['fato_confirmado', analise.fato_confirmado.texto],
    ['contexto_documental', analise.contexto_documental.texto],
    ['rascunho_pre_release', analise.proposta_abordagem.rascunho_pre_release ?? ''],
  ] as const) {
    for (const tok of t.match(NUM_RE) ?? []) {
      const dig = soDigitos(tok);
      if (dig && !existe(dig)) erros.push(`numero_nao_encontrado_no_dossie(${nome}:${tok.slice(0, 24)})`);
    }
  }
  // Nas demais seções, número fora do dossiê é só aviso (opinião/pergunta pode citar um prazo genérico).
  for (const [nome, t] of [
    ['avaliacao_editorial', analise.avaliacao_editorial.texto],
    ['hipotese_apuracao', analise.hipotese_apuracao.texto],
    ['proposta_abordagem', analise.proposta_abordagem.texto],
  ] as const) {
    for (const tok of t.match(NUM_RE) ?? []) {
      const dig = soDigitos(tok);
      if (dig && !existe(dig)) avisos.push(`numero_fora_do_dossie(${nome}:${tok.slice(0, 24)})`);
    }
  }

  // A IA não atribui score/prioridade nem libera publicação.
  const tudo = JSON.stringify(analise);
  if (/\b(score|pontua[cç][aã]o|nota)\s*(final|de relev[aâ]ncia)?\s*[:=]?\s*\d/i.test(tudo) || /\bprioridade\s*[:=]?\s*"?[ABCD]\b/.test(tudo)) {
    erros.push('atribui_score_ou_prioridade');
  }
  if (/(pronto|liberad[oa])\s+para\s+(a\s+)?publica[cç][aã]o|publicar\s+imediatamente|pode\s+ser\s+publicad/i.test(tudo)) {
    erros.push('libera_publicacao');
  }
  return erros.length ? { ok: false, erros, avisos } : { ok: true, erros, avisos, analise };
}

// ---------------------------------------------------------------------------------------------
// Consulta de elegibilidade para o painel (sem custo, sem chamada ao provedor).
// ---------------------------------------------------------------------------------------------
export function resumoElegibilidade(e: Elegibilidade) {
  const motivos = Object.entries(e.flags ?? {}).filter(([, v]) => v === true).map(([k]) => k);
  return {
    event_id: e.event_id ?? null, encontrado: e.encontrado, elegivel: e.elegivel === true,
    ja_analisado_pela_ia: e.ia_sucesso_previo === true, motivos_dispensa: motivos, evidencias: e.evidencias ?? 0,
    modulo: e.modulo ?? null, id_evento: e.id_evento ?? null, status_editorial: e.status_editorial ?? null, revisao_humana: e.revisao_humana ?? null,
    regra_pre_ia: e.regra_pre_ia ?? null, faixa_vinculo: e.faixa_vinculo ?? null, score_antes: e.score_antes ?? null,
    execucao_criacao_id: e.execucao_criacao_id ?? null,
  };
}


// POST {acao:'elegibilidade', empresa_id, event_ids:[...]}  — master, sem custo e sem chamar o provedor.
export async function consultarElegibilidade(repo: Repo, ch: Chamador, body: Record<string, unknown>) {
  exigirMaster(ch);
  if (!isUuid(body.empresa_id)) throw new HttpError(400, 'dados_invalidos', 'empresa_id inválido.');
  const empresaId = body.empresa_id.toLowerCase();
  const ids = body.event_ids;
  if (!Array.isArray(ids) || ids.length === 0 || ids.length > 50 || !ids.every(isUuid)) {
    throw new HttpError(400, 'dados_invalidos', 'event_ids deve ter de 1 a 50 UUIDs.');
  }
  const itens = [];
  for (const id of ids as string[]) {
    const ev = await repo.getEvento(id.toLowerCase());
    if (!ev || ev.empresa_id !== empresaId) { itens.push({ event_id: id, encontrado: false, elegivel: false, motivos_dispensa: ['evento_de_outra_empresa_ou_inexistente'] }); continue; }
    itens.push(resumoElegibilidade(await repo.getElegibilidade(id.toLowerCase())));
  }
  return { ok: true, lote_id: LOTE_PILOTO_ID, limite_max_lote: LIMITE_MAX_LOTE, itens };
}

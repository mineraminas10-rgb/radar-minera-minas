// GATE PRÉ-IA — decisão ÚNICA sobre chamar (ou não) o provedor de IA.
// Regra de ouro: a IA só roda depois de captura -> normalização -> hash -> comparação ->
// deduplicação -> escopo -> regras determinísticas -> travas. Esta função é a última trava.
// Ela é pura (sem rede, sem banco), e o resultado é gravado em api_execucoes.

export type MotivoBloqueio =
  | 'registro_identico'
  | 'hash_igual_ultimo_sucesso'
  | 'republicacao_literal'
  | 'fora_de_escopo'
  | 'descartado_por_regra_deterministica'
  | 'continuidade_sem_mudanca_material'
  | 'enriquecimento_ja_concluido'
  | 'bloqueado_por_falta_de_documento'
  | 'tarefa_sem_linguagem_natural';

// Resultado das etapas determinísticas que já rodaram ANTES (feitas pelo coletor/módulo).
export interface PreIa {
  registro_identico?: boolean;                    // 1  idêntico ao já processado
  hash_igual_ultimo_sucesso?: boolean;            // 2  hash de entrada igual ao do último sucesso
  republicacao_literal?: boolean;                 // 3  republicação sem delta
  fora_de_escopo?: boolean;                       // 4  filtro de escopo
  descartado_por_regra_deterministica?: boolean;  // 5
  continuidade_sem_mudanca_material?: boolean;    // 6
  enriquecimento_ja_concluido?: boolean;          // 7  mesmo estado já enriquecido
  bloqueado_por_falta_de_documento?: boolean;     // 9  a IA não pode suprir documento ausente
  tarefa_sem_linguagem_natural?: boolean;         // 10 não exige interpretação de linguagem natural
}

// Ordem de verificação = ordem da lista do pedido (itens 1-7, 9, 10).
const ORDEM: Array<[keyof PreIa, MotivoBloqueio]> = [
  ['registro_identico', 'registro_identico'],
  ['hash_igual_ultimo_sucesso', 'hash_igual_ultimo_sucesso'],
  ['republicacao_literal', 'republicacao_literal'],
  ['fora_de_escopo', 'fora_de_escopo'],
  ['descartado_por_regra_deterministica', 'descartado_por_regra_deterministica'],
  ['continuidade_sem_mudanca_material', 'continuidade_sem_mudanca_material'],
  ['enriquecimento_ja_concluido', 'enriquecimento_ja_concluido'],
  ['bloqueado_por_falta_de_documento', 'bloqueado_por_falta_de_documento'],
  ['tarefa_sem_linguagem_natural', 'tarefa_sem_linguagem_natural'],
];

export interface GateEntrada {
  empresa_id: string;
  modulo: string | null;
  event_id: string | null;
  operacao: string;
  hash_entrada: string;
  versao_regra: string | null;
  versao_prompt: string;
  status_evento?: string | null;       // informativo (gravado), não decide sozinho
  pre_ia?: PreIa;
}

export interface SucessoAnterior { id: string }

export type Decisao =
  | { acao: 'chamar' }
  | { acao: 'bloquear'; motivo: MotivoBloqueio }
  // item 8: mesma entrada + regra + prompt + modelo (+ esforço) já têm execução de SUCESSO
  | { acao: 'reutilizar'; execucao_anterior_id: string };

export function decidirChamadaIA(e: GateEntrada, sucessoAnterior?: SucessoAnterior | null): Decisao {
  const f = e.pre_ia ?? {};
  for (const [campo, motivo] of ORDEM) {
    if (f[campo] === true) return { acao: 'bloquear', motivo };
  }
  if (sucessoAnterior) return { acao: 'reutilizar', execucao_anterior_id: sucessoAnterior.id };
  return { acao: 'chamar' };
}

export const MOTIVOS_VALIDOS: string[] = ORDEM.map(([, m]) => m);
export const CAMPOS_PRE_IA: string[] = ORDEM.map(([c]) => c as string);

// ---- hashes (SHA-256 hex, Web Crypto: igual em Deno e nos testes) ----
async function sha256(txt: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(txt));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

// Normalização mínima e estável: fim de linha único e espaços das pontas.
export function normalizarEntrada(texto: string): string {
  return texto.replace(/\r\n?/g, '\n').trim();
}

export async function hashEntrada(input: string | Array<{ role: string; content: string }>): Promise<string> {
  const txt = typeof input === 'string' ? normalizarEntrada(input) : JSON.stringify(input.map((m) => [m.role, normalizarEntrada(m.content)]));
  return sha256(txt);
}

// Chave lógica de idempotência (cache do PRÓPRIO Radar — não é o cached_input_tokens da OpenAI).
export async function hashChamada(p: {
  empresa_id: string; carteira_id?: string | null; evento: string | null; operacao: string; hash_entrada: string;
  versao_regra: string | null; versao_prompt: string; modelo: string; reasoning_effort: string;
}): Promise<string> {
  // empresa + carteira + evento + operação + entrada + regra + prompt + modelo + esforço
  return sha256([p.empresa_id, p.carteira_id ?? '', p.evento ?? '', p.operacao, p.hash_entrada, p.versao_regra ?? '', p.versao_prompt, p.modelo, p.reasoning_effort].join('|'));
}

export const sha256Hex = sha256;

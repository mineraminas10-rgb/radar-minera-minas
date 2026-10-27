// Tipos compartilhados das Edge Functions do Radar.
// Nada aqui depende de Deno ou do supabase-js: o núcleo (executar.ts, autorizacao.ts, ...)
// recebe dependências por injeção, o que permite testar toda a regra de negócio sem rede.

// Dois perfis: master (um só, acesso global) e admin (só as empresas vinculadas em usuario_empresas).
export type Role = 'master' | 'admin';
export const ROLES: Role[] = ['master', 'admin'];

export interface Perfil {
  id: string;
  role: string;
  nome: string | null;
  ativo: boolean;
}

export interface Empresa { id: string; nome: string; slug?: string; ativa: boolean }

export interface ApiConfig {
  id: string;
  empresa_id: string;
  provider: string;
  ativo: boolean;
  usa_credencial_global: boolean;
  secret_ref: string | null;        // NOME do secret, nunca o valor
  modelo_padrao: string | null;
  limite_mensal_usd: number | null;
  limite_mensal_tokens: number | null;
  limite_diario_usd: number | null;
  updated_at?: string;
  updated_by?: string | null;
}

export interface Preco {
  id: string;
  provider: string;
  modelo: string;
  vigente_desde: string;
  input_usd_por_milhao: number;
  cached_input_usd_por_milhao: number | null;
  output_usd_por_milhao: number;
}

export interface ConsumoLimites { dia_usd: number; mes_usd: number; mes_tokens: number }

export type StatusExecucao = 'pendente' | 'sucesso' | 'erro' | 'bloqueado_limite' | 'bloqueado_config' | 'bloqueado_pre_ia' | 'reutilizado';

export interface ExecucaoNova {
  empresa_id: string;
  usuario_id: string | null;
  provider: string;
  modelo: string | null;
  operacao: string;
  modulo: string | null;
  event_id: string | null;
  carteira_id?: string | null;   // escopo da consulta (obrigatório nas operações de módulo)
  execucao_id?: string | null;   // execução (consulta) do coletor que originou a chamada
  status: StatusExecucao;
  erro?: string | null;
  metadata?: Record<string, unknown>;
  // auditoria das travas pré-IA
  hash_entrada?: string | null;
  hash_chamada?: string | null;
  versao_prompt?: string | null;
  versao_regra?: string | null;
  reasoning_effort?: string | null;
  motivo_chamada?: string | null;
  motivo_bloqueio?: string | null;
  reutilizado_de_execucao_id?: string | null;
  // só em linhas 'reutilizado': custo zero, nenhum token novo
  input_tokens?: number; cached_input_tokens?: number; output_tokens?: number; reasoning_tokens?: number; total_tokens?: number;
  custo_estimado_usd?: number | null;
  data_fim?: string;
}

export interface ExecucaoPatch {
  status?: StatusExecucao;
  modelo?: string | null;
  request_id_provider?: string | null;
  pricing_id?: string | null;
  data_fim?: string;
  latencia_ms?: number;
  input_tokens?: number;
  cached_input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
  custo_estimado_usd?: number | null;
  erro?: string | null;
  motivo_bloqueio?: string | null;
  resposta_texto?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SucessoPrevio {
  id: string; modelo: string | null; resposta_texto: string | null;
  input_tokens: number; cached_input_tokens: number; output_tokens: number; reasoning_tokens: number; total_tokens: number;
  custo_estimado_usd: number | null;
}

// Escopo de uma consulta: tudo precisa pertencer à MESMA empresa (validado no backend e de novo no banco).
export interface CarteiraEscopo { id: string; empresa_id: string; ativa: boolean }
export interface EventoEscopo { id: string; empresa_id: string; carteira_id: string | null }
export interface ConsultaEscopo { id: string; empresa_id: string; carteira_id: string | null }

export interface AuditoriaNova {
  usuario_id: string | null;
  empresa_id?: string | null;
  acao: string;
  entidade: string;
  entidade_id?: string | null;
  valor_anterior?: unknown;
  valor_novo?: unknown;
  ip?: string | null;
}

// Elegibilidade pré-IA de um evento: calculada no BANCO (ia_elegibilidade_evento) a partir do que os coletores já
// persistiram (faixa do M8, status do M6, família do ato no M9A, evidências). O navegador não participa.
export interface Elegibilidade {
  encontrado: boolean;
  event_id?: string;
  empresa_id?: string;
  carteira_id?: string | null;
  execucao_criacao_id?: string | null;
  modulo?: string;
  id_evento?: string;
  status_editorial?: string;
  revisao_humana?: string | null;
  evidencias?: number;
  flags: Record<string, boolean>;
  elegivel: boolean;
  regra_pre_ia?: string;
  faixa_vinculo?: string | null;
  ia_sucesso_previo?: boolean;
  fila?: { pode: boolean; motivos: string[] };   // decisão do BANCO (fila_pode_gerar_pre_release): corte de score, prioridade D, sem score
  score_antes?: { estagio: string; score_relevancia: number | null; prioridade: string | null; versao_score: string | null } | null;
}

export interface DossieEvidencia { n: number; campo: string | null; tipo: string | null; trecho: string; pagina_secao: string | null }
export interface Dossie {
  event_id: string; empresa_id: string; carteira_id: string | null; execucao_criacao_id: string | null;
  modulo: string; id_evento: string;
  evento: Record<string, unknown>;
  evidencias: DossieEvidencia[];
}

export interface EstadoLote { total: number; evento_ja_chamado: boolean }

// Acesso a dados. Em produção: service_role (ver prod.ts). Nos testes: memória.
export interface Repo {
  getPerfil(userId: string): Promise<Perfil | null>;
  // empresas com vínculo ATIVO em usuario_empresas (a autorização de um admin vem só daqui)
  getEmpresasDoUsuario(userId: string): Promise<string[]>;
  getEmpresa(empresaId: string): Promise<Empresa | null>;
  getCarteira(carteiraId: string): Promise<CarteiraEscopo | null>;
  getEvento(eventId: string): Promise<EventoEscopo | null>;
  getConsulta(execucaoId: string): Promise<ConsultaEscopo | null>;
  getConfig(empresaId: string, provider: string): Promise<ApiConfig | null>;
  getPreco(provider: string, modelo: string, em: Date): Promise<Preco | null>;
  getConsumoLimites(empresaId: string): Promise<ConsumoLimites>;
  insertExecucao(row: ExecucaoNova): Promise<{ id: string }>;
  updateExecucao(id: string, patch: ExecucaoPatch): Promise<void>;
  insertAuditoria(row: AuditoriaNova): Promise<void>;
  // Cofre (Vault): valor da chave pelo NOME; só o backend lê. null = não existe.
  lerChave(nome: string): Promise<string | null>;
  // Idempotência: última execução de SUCESSO real (não 'reutilizado') com esta chave lógica.
  buscarSucessoPorHash(empresaId: string, hashChamada: string): Promise<SucessoPrevio | null>;
  // --- operação assistida (analise_editorial) ---
  getElegibilidade(eventId: string): Promise<Elegibilidade>;
  getDossie(eventId: string): Promise<Dossie | null>;
  // chamadas REAIS (pendente/sucesso/erro) já feitas no lote, e se este evento já teve uma
  estadoLote(empresaId: string, loteId: string, eventId: string | null): Promise<EstadoLote>;
  // recalcula execucoes.totais da execução (idempotente) a partir de api_execucoes
  atualizarTotais(execucaoId: string): Promise<void>;
}

// deve_trocar_senha: vem de auth.users.app_metadata (só o backend escreve; o usuário não consegue alterar)
export interface UsuarioAuth { id: string; email: string | null; deve_trocar_senha?: boolean }
export type GetUser = (jwt: string) => Promise<UsuarioAuth | null>;

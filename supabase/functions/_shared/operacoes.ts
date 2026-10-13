// Catálogo de operações de IA. Cada operação tem SEU teto de tokens de saída e SEU esforço de
// raciocínio (reasoning_effort): nada cai silenciosamente no default do modelo nem em um
// limite genérico de 1024 tokens.
export type Esforco = 'none' | 'low' | 'medium';

export interface OperacaoCfg {
  nome: string;
  max_output_tokens: number;          // teto da operação (pedido maior é LIMITADO a este valor e registrado)
  esforco_padrao: Esforco;
  esforcos_permitidos: Esforco[];
  texto_livre: boolean;               // true: operações de teste/painel, sem prompt registrado
  so_master?: boolean;
  exige_autorizacao_explicita?: boolean; // o chamador precisa mandar autorizacao_explicita=true
  // Operação de módulo da operação assistida: o SERVIDOR monta a entrada (dossiê do evento no banco), confere a
  // elegibilidade pré-IA, exige lote/limite/usar_api_real e valida a resposta antes de aceitá-la.
  dossie_servidor?: boolean;
}

export const OPERACOES: Record<string, OperacaoCfg> = {
  classificacao:           { nome: 'classificacao',           max_output_tokens: 150,  esforco_padrao: 'none',   esforcos_permitidos: ['none'],         texto_livre: false },
  deduplicacao_semantica:  { nome: 'deduplicacao_semantica',  max_output_tokens: 150,  esforco_padrao: 'none',   esforcos_permitidos: ['none'],         texto_livre: false },
  extracao_estruturada:    { nome: 'extracao_estruturada',    max_output_tokens: 350,  esforco_padrao: 'none',   esforcos_permitidos: ['none', 'low'],  texto_livre: false },
  avaliacao_editorial:     { nome: 'avaliacao_editorial',     max_output_tokens: 400,  esforco_padrao: 'low',    esforcos_permitidos: ['none', 'low'],  texto_livre: false },
  resumo:                  { nome: 'resumo',                  max_output_tokens: 500,  esforco_padrao: 'low',    esforcos_permitidos: ['none', 'low'],  texto_livre: false },
  pre_release:             { nome: 'pre_release',             max_output_tokens: 800,  esforco_padrao: 'low',    esforcos_permitidos: ['none', 'low'],  texto_livre: false },
  // operação assistida (piloto): 7 seções separadas, saída estruturada validada no servidor
  analise_editorial:       { nome: 'analise_editorial',       max_output_tokens: 1600, esforco_padrao: 'none',   esforcos_permitidos: ['none', 'low'],  texto_livre: false, so_master: true, dossie_servidor: true },
  // raciocínio médio só por operação explicitamente autorizada (master + autorizacao_explicita)
  raciocinio_complexo:     { nome: 'raciocinio_complexo',     max_output_tokens: 1500, esforco_padrao: 'medium', esforcos_permitidos: ['medium'],       texto_livre: false, so_master: true, exige_autorizacao_explicita: true },
  // painel ADMIN
  teste_conexao:           { nome: 'teste_conexao',           max_output_tokens: 16,   esforco_padrao: 'none',   esforcos_permitidos: ['none'],         texto_livre: true,  so_master: true },
  execucao_teste:          { nome: 'execucao_teste',          max_output_tokens: 512,  esforco_padrao: 'none',   esforcos_permitidos: ['none'],         texto_livre: true,  so_master: true },
};

export function operacaoDe(nome: string): OperacaoCfg | null {
  return Object.prototype.hasOwnProperty.call(OPERACOES, nome) ? OPERACOES[nome] : null;
}

import type { ApiConfig, ConsumoLimites, Preco } from './types.ts';

export interface Uso { input_tokens: number; cached_input_tokens: number; output_tokens: number; total_tokens: number }

const arred = (n: number) => Math.round(n * 1e6) / 1e6;

// Custo = (entrada não-cacheada × preço entrada + entrada cacheada × preço cache + saída × preço saída) / 1e6.
// Usa SEMPRE a versão de preço vigente na hora da chamada (api_model_pricing).
export function calcularCusto(uso: Uso, preco: Preco): number {
  const cached = Math.min(uso.cached_input_tokens, uso.input_tokens);
  const normal = uso.input_tokens - cached;
  const precoCache = preco.cached_input_usd_por_milhao ?? preco.input_usd_por_milhao;
  return arred(
    (normal * preco.input_usd_por_milhao + cached * precoCache + uso.output_tokens * preco.output_usd_por_milhao) / 1e6,
  );
}

// Estimativa PESSIMISTA feita antes de chamar a API (sem desconto de cache):
// entrada ≈ caracteres/3 e saída = teto pedido.
export function estimarMaximo(chars: number, maxOutput: number, preco: Preco): { usd: number; tokens: number } {
  const inTok = Math.ceil(chars / 3);
  const usd = arred((inTok * preco.input_usd_por_milhao + maxOutput * preco.output_usd_por_milhao) / 1e6);
  return { usd, tokens: inTok + maxOutput };
}

export type Violacao = 'diario_usd' | 'mensal_usd' | 'mensal_tokens';

// null = sem limite. 0 = bloqueado. Bloqueia se consumo atual + estimativa ultrapassa o limite.
export function verificarLimites(
  cfg: Pick<ApiConfig, 'limite_diario_usd' | 'limite_mensal_usd' | 'limite_mensal_tokens'>,
  consumo: ConsumoLimites,
  est: { usd: number; tokens: number },
): Violacao[] {
  const v: Violacao[] = [];
  if (cfg.limite_diario_usd != null && consumo.dia_usd + est.usd > Number(cfg.limite_diario_usd)) v.push('diario_usd');
  if (cfg.limite_mensal_usd != null && consumo.mes_usd + est.usd > Number(cfg.limite_mensal_usd)) v.push('mensal_usd');
  if (cfg.limite_mensal_tokens != null && consumo.mes_tokens + est.tokens > Number(cfg.limite_mensal_tokens)) v.push('mensal_tokens');
  return v;
}

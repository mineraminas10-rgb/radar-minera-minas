// Resolve ONDE está a chave da API, sem nunca devolvê-la a ninguém além do chamador interno.
// A chave fica no COFRE do Supabase (Vault), cadastrada pelo master em ADMIN > API:
//   - credencial global (compartilhada):  nome OPENAI_API_KEY_GLOBAL
//   - chave específica de uma empresa:    nome OPENAI_API_KEY_EMP_<id da empresa sem hífens, maiúsculo>
// Compatibilidade: se o cofre não tiver o nome, vale o secret de Edge Function de mesmo nome (modelo anterior).
// O padrão do nome impede apontar para segredos do Supabase (ex.: SUPABASE_SERVICE_ROLE_KEY).
export const SEGREDO_GLOBAL = 'OPENAI_API_KEY_GLOBAL';
export const SECRET_REF_RE = /^OPENAI_API_KEY_[A-Z0-9_]{1,60}$/;
// formato de uma chave da OpenAI (sk-..., sk-proj-...). Barra colar texto errado e quebras de linha.
export const CHAVE_OPENAI_RE = /^sk-[A-Za-z0-9_\-]{20,255}$/;

export const nomeChaveEmpresa = (empresaId: string): string =>
  `OPENAI_API_KEY_EMP_${empresaId.replace(/-/g, '').toUpperCase()}`;

export function nomeDoSegredo(cfg: { empresa_id?: string; usa_credencial_global: boolean; secret_ref: string | null }): string | null {
  if (cfg.usa_credencial_global) return SEGREDO_GLOBAL;
  if (cfg.secret_ref && SECRET_REF_RE.test(cfg.secret_ref)) return cfg.secret_ref;
  return null;
}

// Cofre primeiro; depois o secret de função (legado). Devolve só para uso interno do servidor.
export async function obterSegredo(
  cfg: { usa_credencial_global: boolean; secret_ref: string | null },
  getEnv: (n: string) => string | undefined,
  lerChave: (nome: string) => Promise<string | null>,
): Promise<{ nome: string | null; valor: string | null }> {
  const nome = nomeDoSegredo(cfg);
  if (!nome) return { nome: null, valor: null };
  const limpa = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
  const doCofre = limpa(await lerChave(nome));
  return { nome, valor: doCofre ?? limpa(getEnv(nome)) };
}

export async function statusSegredo(
  nome: string | null,
  getEnv: (n: string) => string | undefined,
  statusChave: (nome: string) => Promise<{ presente: boolean; ultimos4: string | null }>,
): Promise<{ nome: string | null; presente: boolean; ultimos4: string | null; origem: 'cofre' | 'secret_funcao' | null }> {
  if (!nome) return { nome: null, presente: false, ultimos4: null, origem: null };
  const s = await statusChave(nome);
  if (s.presente) return { nome, presente: true, ultimos4: s.ultimos4, origem: 'cofre' };
  if ((getEnv(nome) || '').trim()) return { nome, presente: true, ultimos4: null, origem: 'secret_funcao' };
  return { nome, presente: false, ultimos4: null, origem: null };
}

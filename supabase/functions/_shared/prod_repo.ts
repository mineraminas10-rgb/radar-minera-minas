// Ligação do executar-ai com o mundo real (Deno + Supabase): repositório, usuário e dependências.
// SUPABASE_URL, SUPABASE_ANON_KEY e SUPABASE_SERVICE_ROLE_KEY são injetadas automaticamente
// pelo Supabase nas Edge Functions — a service role NUNCA sai do servidor.
import { createClient } from 'npm:@supabase/supabase-js@2';
import type { ExecDeps } from './executar.ts';
import type {
  ApiConfig, AuditoriaNova, ConsumoLimites, Dossie, Elegibilidade, Empresa, ExecucaoNova, ExecucaoPatch, GetUser, Perfil, Preco, Repo,
} from './types.ts';

export const getEnv = (n: string) => Deno.env.get(n);

export function admin() {
  const url = getEnv('SUPABASE_URL');
  const key = getEnv('SUPABASE_SERVICE_ROLE_KEY');
  if (!url || !key) throw new Error('Ambiente do Supabase incompleto.');
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}

export const falha = (ctx: string, e: { message?: string } | null) => { if (e) throw new Error(`${ctx}: ${e.message}`); };
export const n = (v: unknown) => (v === null || v === undefined ? null : Number(v));

export function criarRepo(db = admin()): Repo {
  return {
    async getPerfil(userId) {
      const { data, error } = await db.from('usuarios_perfil').select('id, role, nome, ativo').eq('id', userId).maybeSingle();
      falha('perfil', error); return (data as Perfil | null) ?? null;
    },
    async getEmpresasDoUsuario(userId) {
      const { data, error } = await db.from('usuario_empresas').select('empresa_id').eq('usuario_id', userId).eq('ativo', true);
      falha('vinculos', error); return (data ?? []).map((r) => String(r.empresa_id).toLowerCase());
    },
    async getEmpresa(id) {
      const { data, error } = await db.from('empresas').select('id, nome, slug, ativa').eq('id', id).maybeSingle();
      falha('empresa', error); return (data as Empresa | null) ?? null;
    },
    async getCarteira(id) {
      const { data, error } = await db.from('carteiras').select('id, empresa_id, ativa').eq('id', id).maybeSingle();
      falha('carteira', error);
      return data ? { id: String(data.id), empresa_id: String(data.empresa_id), ativa: data.ativa !== false } : null;
    },
    async getEvento(id) {
      const { data, error } = await db.from('events').select('id, empresa_id, carteira_id').eq('id', id).maybeSingle();
      falha('evento', error);
      return data ? { id: String(data.id), empresa_id: String(data.empresa_id), carteira_id: data.carteira_id ? String(data.carteira_id) : null } : null;
    },
    async getConsulta(id) {
      const { data, error } = await db.from('execucoes').select('id, empresa_id, carteira_id').eq('id', id).maybeSingle();
      falha('execucao', error);
      return data ? { id: String(data.id), empresa_id: String(data.empresa_id), carteira_id: data.carteira_id ? String(data.carteira_id) : null } : null;
    },
    async getConfig(empresaId, provider) {
      const { data, error } = await db.from('empresa_api_config').select('*').eq('empresa_id', empresaId).eq('provider', provider).maybeSingle();
      falha('config', error);
      if (!data) return null;
      return { ...data, limite_mensal_usd: n(data.limite_mensal_usd), limite_mensal_tokens: n(data.limite_mensal_tokens), limite_diario_usd: n(data.limite_diario_usd) } as ApiConfig;
    },
    async getPreco(provider, modelo, em) {
      const { data, error } = await db.from('api_model_pricing').select('*').eq('provider', provider).eq('modelo', modelo).eq('ativo', true)
        .lte('vigente_desde', em.toISOString()).order('vigente_desde', { ascending: false }).limit(1);
      falha('preco', error);
      const p = data?.[0];
      return p ? ({ ...p, input_usd_por_milhao: Number(p.input_usd_por_milhao), output_usd_por_milhao: Number(p.output_usd_por_milhao), cached_input_usd_por_milhao: n(p.cached_input_usd_por_milhao) } as Preco) : null;
    },
    async getConsumoLimites(empresaId): Promise<ConsumoLimites> {
      const { data, error } = await db.rpc('consumo_limites_empresa', { p_empresa_id: empresaId });
      falha('consumo', error);
      const r = Array.isArray(data) ? data[0] : data;
      return { dia_usd: Number(r?.dia_usd ?? 0), mes_usd: Number(r?.mes_usd ?? 0), mes_tokens: Number(r?.mes_tokens ?? 0) };
    },
    async insertExecucao(row: ExecucaoNova) {
      const { data, error } = await db.from('api_execucoes').insert(row).select('id').single();
      falha('execucao', error); return { id: data!.id as string };
    },
    async updateExecucao(id: string, patch: ExecucaoPatch) {
      const { error } = await db.from('api_execucoes').update(patch).eq('id', id);
      falha('execucao', error);
    },
    async buscarSucessoPorHash(empresaId: string, hashChamada: string) {
      const { data, error } = await db.from('api_execucoes')
        .select('id, modelo, resposta_texto, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, total_tokens, custo_estimado_usd')
        .eq('empresa_id', empresaId).eq('hash_chamada', hashChamada).eq('status', 'sucesso')
        .order('created_at', { ascending: false }).limit(1);
      falha('execucao', error);
      const r = (data ?? [])[0];
      if (!r) return null;
      return {
        id: r.id as string, modelo: (r.modelo as string) ?? null, resposta_texto: (r.resposta_texto as string) ?? null,
        input_tokens: Number(r.input_tokens), cached_input_tokens: Number(r.cached_input_tokens), output_tokens: Number(r.output_tokens),
        reasoning_tokens: Number(r.reasoning_tokens), total_tokens: Number(r.total_tokens),
        custo_estimado_usd: r.custo_estimado_usd == null ? null : Number(r.custo_estimado_usd),
      };
    },
    async getElegibilidade(eventId) {
      const { data, error } = await db.rpc('ia_elegibilidade_evento', { p_event_id: eventId });
      falha('elegibilidade', error);
      const r = (data ?? {}) as Record<string, unknown>;
      return { ...r, encontrado: r.encontrado === true, elegivel: r.elegivel === true, flags: (r.flags ?? {}) as Record<string, boolean> } as Elegibilidade;
    },
    async getDossie(eventId) {
      const { data, error } = await db.rpc('ia_dossie_evento', { p_event_id: eventId, p_max_evidencias: 12 });
      falha('dossie', error);
      return (data as Dossie | null) ?? null;
    },
    async estadoLote(empresaId, loteId, eventId) {
      const base = () => db.from('api_execucoes').select('id', { count: 'exact', head: true })
        .eq('empresa_id', empresaId).eq('metadata->>lote_id', loteId).in('status', ['pendente', 'sucesso', 'erro']);
      const t = await base(); falha('lote', t.error);
      let jaChamado = false;
      if (eventId) { const e = await base().eq('event_id', eventId); falha('lote', e.error); jaChamado = (e.count ?? 0) > 0; }
      return { total: t.count ?? 0, evento_ja_chamado: jaChamado };
    },
    async atualizarTotais(execucaoId) {
      const { error } = await db.rpc('ia_totais_atualizar', { p_execucao_id: execucaoId });
      falha('totais', error);
    },
    async lerChave(nome) {
      const { data, error } = await db.rpc('api_chave_ler', { p_nome: nome });
      falha('cofre', error); return typeof data === 'string' && data ? data : null;
    },
    async insertAuditoria(row: AuditoriaNova) {
      const { error } = await db.from('admin_auditoria').insert(row);
      falha('auditoria', error);
    },
  };
}

export function criarGetUser(db = admin()): GetUser {
  return async (jwt) => {
    const { data, error } = await db.auth.getUser(jwt);
    if (error || !data?.user) return null;
    const am = (data.user.app_metadata ?? {}) as Record<string, unknown>;
    return { id: data.user.id, email: data.user.email ?? null, deve_trocar_senha: am.must_change_password === true };
  };
}

export function depsProducao(repo: Repo = criarRepo()): ExecDeps {
  return { repo, getEnv, fetchFn: fetch, now: () => new Date() };
}

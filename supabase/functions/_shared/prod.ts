// Ligação das funções ADMINISTRATIVAS com o mundo real (Deno + Supabase).
// O repositório do executar-ai (que toca a chave da API) fica em prod_repo.ts, com o mínimo de código.
import { createClient } from 'npm:@supabase/supabase-js@2';
import type { AdminAuth, AdminRepo, UsuarioAuthInfo } from './handlers.ts';
import type { Perfil, Preco, Empresa, ApiConfig } from './types.ts';
import { admin, falha, getEnv, n } from './prod_repo.ts';

export { criarRepo, criarGetUser, depsProducao } from './prod_repo.ts';

export function criarAdminRepo(db = admin()): AdminRepo {
  return {
    async listarPerfis() {
      const { data, error } = await db.from('usuarios_perfil').select('id, role, nome, ativo').order('created_at');
      falha('perfis', error); return (data ?? []) as Perfil[];
    },
    async upsertPerfil(p) {
      const { error } = await db.from('usuarios_perfil').upsert(p, { onConflict: 'id' });
      falha('perfil', error);
    },
    async updatePerfil(id, patch) {
      const { error } = await db.from('usuarios_perfil').update(patch).eq('id', id);
      falha('perfil', error);
    },
    async listarVinculos() {
      const { data, error } = await db.from('usuario_empresas').select('usuario_id, empresa_id, ativo');
      falha('vinculos', error);
      return (data ?? []).map((v) => ({ usuario_id: v.usuario_id as string, empresa_id: String(v.empresa_id).toLowerCase(), ativo: v.ativo === true }));
    },
    async definirVinculos(usuarioId, empresaIds, criadoPor) {
      const { data, error } = await db.from('usuario_empresas').select('empresa_id, ativo').eq('usuario_id', usuarioId);
      falha('vinculos', error);
      const atuais = (data ?? []).map((v) => ({ empresa_id: String(v.empresa_id).toLowerCase(), ativo: v.ativo === true }));
      const antes = atuais.filter((v) => v.ativo).map((v) => v.empresa_id).sort();
      const existentes = new Set(atuais.map((v) => v.empresa_id));
      const alvo = Array.from(new Set(empresaIds.map((e) => e.toLowerCase()))).sort();
      // primeiro cria/reativa, por último desativa: uma falha no meio nunca derruba um acesso que devia ficar
      const novas = alvo.filter((e) => !existentes.has(e)).map((e) => ({ usuario_id: usuarioId, empresa_id: e, ativo: true, created_by: criadoPor }));
      if (novas.length) { const r = await db.from('usuario_empresas').insert(novas); falha('vinculos', r.error); }
      const reativar = alvo.filter((e) => existentes.has(e) && !antes.includes(e));
      if (reativar.length) { const r = await db.from('usuario_empresas').update({ ativo: true }).eq('usuario_id', usuarioId).in('empresa_id', reativar); falha('vinculos', r.error); }
      const desativar = antes.filter((e) => !alvo.includes(e));
      if (desativar.length) { const r = await db.from('usuario_empresas').update({ ativo: false }).eq('usuario_id', usuarioId).in('empresa_id', desativar); falha('vinculos', r.error); }
      return { antes, depois: alvo };
    },
    async contarMastersAtivos(excetoId) {
      let q = db.from('usuarios_perfil').select('id', { count: 'exact', head: true }).eq('role', 'master').eq('ativo', true);
      if (excetoId) q = q.neq('id', excetoId);
      const { count, error } = await q; falha('masters', error); return count ?? 0;
    },
    async listarEmpresas() {
      const { data, error } = await db.from('empresas').select('id, nome, slug, ativa').order('nome');
      falha('empresas', error); return (data ?? []) as Empresa[];
    },
    async upsertConfig(c) {
      const { data, error } = await db.from('empresa_api_config').upsert(c, { onConflict: 'empresa_id,provider' }).select('*').single();
      falha('config', error);
      return { ...data, limite_mensal_usd: n(data!.limite_mensal_usd), limite_mensal_tokens: n(data!.limite_mensal_tokens), limite_diario_usd: n(data!.limite_diario_usd) } as ApiConfig;
    },
    async listarPrecos() {
      const { data, error } = await db.from('api_model_pricing').select('*').order('modelo').order('vigente_desde', { ascending: false });
      falha('precos', error);
      return (data ?? []).map((p) => ({ ...p, input_usd_por_milhao: Number(p.input_usd_por_milhao), output_usd_por_milhao: Number(p.output_usd_por_milhao), cached_input_usd_por_milhao: n(p.cached_input_usd_por_milhao) })) as Preco[];
    },
    async definirChave(nome, valor) {
      const { error } = await db.rpc('api_chave_definir', { p_nome: nome, p_valor: valor });
      falha('cofre', error);
    },
    async statusChave(nome) {
      const { data, error } = await db.rpc('api_chave_status', { p_nome: nome });
      falha('cofre', error);
      return { presente: data?.presente === true, ultimos4: typeof data?.ultimos4 === 'string' ? data.ultimos4 : null };
    },
    async inserirPreco(p) {
      const { data, error } = await db.from('api_model_pricing').insert(p).select('*').single();
      falha('preco', error);
      return { ...data, input_usd_por_milhao: Number(data!.input_usd_por_milhao), output_usd_por_milhao: Number(data!.output_usd_por_milhao), cached_input_usd_por_milhao: n(data!.cached_input_usd_por_milhao) } as Preco;
    },
  };
}

export function criarAdminAuth(db = admin()): AdminAuth {
  const info = (u: { id: string; email?: string | null; last_sign_in_at?: string | null; created_at?: string | null }): UsuarioAuthInfo =>
    ({ id: u.id, email: u.email ?? null, last_sign_in_at: u.last_sign_in_at ?? null, created_at: u.created_at ?? null });
  return {
    async listarUsuarios() {
      const out: UsuarioAuthInfo[] = [];
      for (let page = 1; page <= 50; page++) {
        const { data, error } = await db.auth.admin.listUsers({ page, perPage: 1000 });
        falha('listUsers', error);
        out.push(...data.users.map(info));
        if (data.users.length < 1000) break;
      }
      return out;
    },
    async getUsuario(id) {
      const { data, error } = await db.auth.admin.getUserById(id);
      if (error || !data?.user) return null; return info(data.user);
    },
    async convidar(email, nome, redirectTo) {
      const { data, error } = await db.auth.admin.inviteUserByEmail(email, { data: { name: nome }, redirectTo });
      falha('convite', error); if (!data?.user) throw new Error('convite: usuário não retornado'); return { id: data.user.id };
    },
    async criarComSenha(email, nome, senha) {
      const { data, error } = await db.auth.admin.createUser({
        email, password: senha, email_confirm: true, user_metadata: { name: nome }, app_metadata: { must_change_password: true },
      });
      falha('criarUsuario', error); if (!data?.user) throw new Error('criarUsuario: usuário não retornado'); return { id: data.user.id };
    },
    async definirSenhaTemporaria(id, senha) {
      const { error } = await db.auth.admin.updateUserById(id, { password: senha, app_metadata: { must_change_password: true } });
      falha('senhaTemporaria', error);
    },
    async definirSenhaDefinitiva(id, senha) {
      const { error } = await db.auth.admin.updateUserById(id, { password: senha, app_metadata: { must_change_password: false } });
      falha('senhaDefinitiva', error);
    },
    async senhaConfere(email, senha) {
      const url = getEnv('SUPABASE_URL')!; const anon = getEnv('SUPABASE_ANON_KEY')!;
      const c = createClient(url, anon, { auth: { persistSession: false, autoRefreshToken: false } });
      const { data, error } = await c.auth.signInWithPassword({ email, password: senha });
      if (!error && data?.session) { try { await c.auth.signOut({ scope: 'local' }); } catch { /* ignora */ } return true; }
      return false;
    },
    async criarSemEmail(email, nome) {
      const { data, error } = await db.auth.admin.createUser({ email, email_confirm: true, user_metadata: { name: nome } });
      falha('criarUsuario', error); if (!data?.user) throw new Error('criarUsuario: usuário não retornado'); return { id: data.user.id };
    },
    async gerarLinkRecuperacao(email, redirectTo) {
      const { data, error } = await db.auth.admin.generateLink({ type: 'recovery', email, options: { redirectTo } });
      falha('link', error); if (!data?.properties?.action_link) throw new Error('link: não gerado'); return data.properties.action_link;
    },
    async enviarRecuperacao(email, redirectTo) {
      const url = getEnv('SUPABASE_URL')!; const anon = getEnv('SUPABASE_ANON_KEY')!;
      const c = createClient(url, anon, { auth: { persistSession: false, autoRefreshToken: false } });
      const { error } = await c.auth.resetPasswordForEmail(email, { redirectTo });
      falha('recuperacao', error);
    },
    async banir(id, banir) {
      const { error } = await db.auth.admin.updateUserById(id, { ban_duration: banir ? '876000h' : 'none' });
      falha('ban', error);
    },
  };
}


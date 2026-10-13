import { HttpError, isUuid } from './errors.ts';
import type { GetUser, Perfil, Repo } from './types.ts';

// empresas: vínculos ATIVOS (usuario_empresas) — só relevante para admin; master tem acesso global.
export interface Chamador { userId: string; email: string | null; perfil: Perfil; deveTrocarSenha: boolean; empresas: string[] }

export interface OpcoesAutenticar {
  // só a função trocar-senha aceita quem ainda está com a senha temporária
  permitirSenhaProvisoria?: boolean;
}

// 1) JWT válido  2) perfil existe em usuarios_perfil  3) ativo = true.
// O papel e a empresa vêm SEMPRE do banco (usuarios_perfil) — nunca do token
// nem de user_metadata, nem do corpo da requisição.
export async function autenticar(repo: Repo, getUser: GetUser, req: Request, opts: OpcoesAutenticar = {}): Promise<Chamador> {
  const auth = req.headers.get('authorization') || '';
  const m = /^Bearer\s+(.+)$/i.exec(auth);
  if (!m) throw new HttpError(401, 'nao_autenticado', 'Faça login para continuar.');
  const user = await getUser(m[1].trim());
  if (!user) throw new HttpError(401, 'nao_autenticado', 'Sessão inválida ou expirada.');
  const perfil = await repo.getPerfil(user.id);
  if (!perfil) throw new HttpError(403, 'sem_permissao', 'Cadastro não autorizado.');
  if (perfil.ativo !== true) throw new HttpError(403, 'sem_permissao', 'Usuário inativo.');
  const deveTrocarSenha = user.deve_trocar_senha === true;
  if (deveTrocarSenha && !opts.permitirSenhaProvisoria) {
    throw new HttpError(403, 'trocar_senha', 'Defina sua nova senha antes de continuar.');
  }
  if (perfil.role !== 'master' && perfil.role !== 'admin') throw new HttpError(403, 'sem_permissao', 'Perfil não reconhecido.');
  // O vínculo vem SEMPRE do banco, nunca do token nem do corpo da requisição.
  const empresas = perfil.role === 'admin' ? await repo.getEmpresasDoUsuario(user.id) : [];
  return { userId: user.id, email: user.email, perfil, deveTrocarSenha, empresas };
}

export function exigirRole(ch: Chamador, permitidos: string[]): void {
  if (!permitidos.includes(ch.perfil.role)) {
    throw new HttpError(403, 'sem_permissao', 'Seu perfil não tem permissão para esta ação.');
  }
}

export function exigirMaster(ch: Chamador): void {
  exigirRole(ch, ['master']);
}

// Define em nome de QUAL empresa a chamada é feita.
//  - master: qualquer empresa (a escolhida no painel); precisa informar empresa_id;
//  - admin : só empresas com vínculo ativo. Sem empresa_id: vale se houver exatamente uma;
//            com várias, precisa escolher. Pedir uma empresa não vinculada => 403 (mesma
//            mensagem, sem revelar se ela existe).
export function resolverEmpresa(ch: Chamador, solicitada: unknown): string {
  const informada = solicitada !== undefined && solicitada !== null && solicitada !== '';
  if (ch.perfil.role === 'master') {
    if (!isUuid(solicitada)) throw new HttpError(400, 'dados_invalidos', 'empresa_id inválido.');
    return solicitada;
  }
  if (!ch.empresas.length) throw new HttpError(403, 'sem_permissao', 'Usuário sem empresa autorizada.');
  if (!informada) {
    if (ch.empresas.length === 1) return ch.empresas[0];
    throw new HttpError(400, 'dados_invalidos', 'Informe empresa_id (você tem acesso a mais de uma empresa).');
  }
  if (typeof solicitada !== 'string' || !ch.empresas.includes(solicitada.toLowerCase())) {
    throw new HttpError(403, 'sem_permissao', 'Você não tem acesso a esta empresa.');
  }
  return solicitada.toLowerCase();
}

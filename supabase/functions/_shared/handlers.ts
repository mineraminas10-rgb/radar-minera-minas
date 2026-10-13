// Handlers HTTP das três Edge Functions, com dependências injetadas.
// Os index.ts só ligam isto ao Deno.serve com as dependências reais (prod.ts).
import { autenticar, exigirMaster } from './autorizacao.ts';
import { HttpError, isUuid, sanitizarErro } from './errors.ts';
import { corsHeaders, json, lerJson, respostaDeErro } from './http.ts';
import { executarIA } from './executar.ts';
import type { ExecDeps } from './executar.ts';
import { CHAVE_OPENAI_RE, SECRET_REF_RE, SEGREDO_GLOBAL, nomeChaveEmpresa, nomeDoSegredo, statusSegredo } from './segredo.ts';
import { gerarSenhaTemporaria, validarSenhaNova } from './senha.ts';
import type { ApiConfig, GetUser, Perfil, Preco, Role } from './types.ts';
import { ROLES } from './types.ts';

// ---------------------------------------------------------------------------
// executar-ai  (qualquer usuário autenticado com papel permitido, só na própria empresa)
// ---------------------------------------------------------------------------
export { criarHandlerExecutarAi } from './handlers_executar.ts';

// ---------------------------------------------------------------------------
// Camada de Auth administrativa (criar convidar, banir...) — injetada para teste
// ---------------------------------------------------------------------------
export interface UsuarioAuthInfo { id: string; email: string | null; last_sign_in_at: string | null; created_at: string | null }
export interface AdminAuth {
  listarUsuarios(): Promise<UsuarioAuthInfo[]>;
  getUsuario(id: string): Promise<UsuarioAuthInfo | null>;
  convidar(email: string, nome: string, redirectTo?: string): Promise<{ id: string }>;
  criarSemEmail(email: string, nome: string): Promise<{ id: string }>;     // para o modo "link"
  // modo "senha temporária": conta criada com senha aleatória + marca must_change_password (app_metadata)
  criarComSenha(email: string, nome: string, senha: string): Promise<{ id: string }>;
  definirSenhaTemporaria(id: string, senha: string): Promise<void>;       // redefinição: nova senha aleatória + marca de troca obrigatória
  definirSenhaDefinitiva(id: string, senha: string): Promise<void>;       // senha escolhida pelo usuário + remove a marca
  senhaConfere(email: string, senha: string): Promise<boolean>;           // a senha informada já é a atual?
  gerarLinkRecuperacao(email: string, redirectTo?: string): Promise<string>;
  enviarRecuperacao(email: string, redirectTo?: string): Promise<void>;
  banir(id: string, banir: boolean): Promise<void>;
}
export interface AdminRepo {
  listarPerfis(): Promise<Perfil[]>;
  upsertPerfil(p: { id: string; role: string; nome: string; ativo: boolean }): Promise<void>;
  updatePerfil(id: string, patch: Partial<Pick<Perfil, 'nome' | 'ativo'>>): Promise<void>;
  // vínculos usuário<->empresa (tabela usuario_empresas): só o backend escreve
  listarVinculos(): Promise<Array<{ usuario_id: string; empresa_id: string; ativo: boolean }>>;
  // deixa EXATAMENTE `empresaIds` ativas para o usuário (cria as novas, reativa, desativa as demais)
  definirVinculos(usuarioId: string, empresaIds: string[], criadoPor: string): Promise<{ antes: string[]; depois: string[] }>;
  contarMastersAtivos(excetoId?: string): Promise<number>;
  listarEmpresas(): Promise<Array<{ id: string; nome: string; slug?: string; ativa: boolean }>>;
  upsertConfig(c: Omit<ApiConfig, 'id' | 'updated_at'> & { updated_by: string }): Promise<ApiConfig>;
  listarPrecos(): Promise<Preco[]>;
  inserirPreco(p: Omit<Preco, 'id'> & { ativo?: boolean }): Promise<Preco>;
  // Cofre: grava/substitui o valor sob o NOME dado; status NUNCA devolve o valor (só presença + últimos 4)
  definirChave(nome: string, valor: string): Promise<void>;
  statusChave(nome: string): Promise<{ presente: boolean; ultimos4: string | null }>;
}

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,255}\.[^\s@]{2,}$/;
const ipDe = (req: Request) => (req.headers.get('x-forwarded-for') || '').split(',')[0].trim().slice(0, 64) || null;

// ---------------------------------------------------------------------------
// admin-usuarios  (SOMENTE master, validado no banco)
// ---------------------------------------------------------------------------
export function criarHandlerAdminUsuarios(deps: ExecDeps, getUser: GetUser, auth: AdminAuth, adm: AdminRepo) {
  return async (req: Request): Promise<Response> => {
    const cors = corsHeaders(deps.getEnv);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      if (req.method !== 'POST') throw new HttpError(405, 'metodo_invalido', 'Use POST.');
      const ch = await autenticar(deps.repo, getUser, req);
      exigirMaster(ch);
      const b = await lerJson(req);
      const ip = ipDe(req);
      const redirectTo = deps.getEnv('APP_URL') || undefined;
      const emailLiberado = deps.getEnv('PERMITIR_FLUXO_EMAIL') === 'true';
      const acao = String(b.acao || '');

      const empresaValida = async (id: unknown): Promise<string> => {
        if (!isUuid(id)) throw new HttpError(400, 'dados_invalidos', 'empresa_id inválido.');
        const e = await deps.repo.getEmpresa(id);
        if (!e || e.ativa === false) throw new HttpError(400, 'dados_invalidos', 'Empresa não encontrada ou inativa.');
        return id;
      };
      const roleValido = (r: unknown): Role => {
        if (typeof r !== 'string' || !(ROLES as string[]).includes(r)) throw new HttpError(400, 'dados_invalidos', 'Perfil (role) inválido.');
        return r as Role;
      };
      // lista de empresas do usuário: array de UUIDs, sem repetição, todas existentes e ativas
      const empresasValidas = async (v: unknown): Promise<string[]> => {
        if (v === undefined || v === null) return [];
        if (!Array.isArray(v) || v.length > 200) throw new HttpError(400, 'dados_invalidos', 'empresa_ids deve ser uma lista de empresas.');
        const out: string[] = [];
        for (const x of v) {
          const id = await empresaValida(x);
          if (!out.includes(id.toLowerCase())) out.push(id.toLowerCase());
        }
        return out;
      };
      const nomeValido = (n: unknown): string => {
        const s = typeof n === 'string' ? n.trim() : '';
        if (s.length < 2 || s.length > 120) throw new HttpError(400, 'dados_invalidos', 'Nome deve ter entre 2 e 120 caracteres.');
        return s;
      };

      if (acao === 'listar') {
        const [perfis, contas, vinculos] = await Promise.all([adm.listarPerfis(), auth.listarUsuarios(), adm.listarVinculos()]);
        const porId = new Map(contas.map((c) => [c.id, c]));
        const usuarios = perfis.map((p) => {
          const c = porId.get(p.id);
          return { id: p.id, email: c?.email ?? null, nome: p.nome, role: p.role, ativo: p.ativo,
                   empresa_ids: p.role === 'master' ? [] : vinculos.filter((v) => v.usuario_id === p.id && v.ativo).map((v) => v.empresa_id),
                   ultimo_acesso: c?.last_sign_in_at ?? null, criado_em: c?.created_at ?? null };
        });
        return json(200, { ok: true, usuarios }, cors);
      }

      if (acao === 'criar') {
        const nome = nomeValido(b.nome);
        const email = String(b.email || '').trim().toLowerCase();
        if (!EMAIL_RE.test(email)) throw new HttpError(400, 'dados_invalidos', 'E-mail inválido.');
        // Só existe UM master (o dono do sistema, definido direto no banco): o painel só cria admins.
        const role = b.role === undefined || b.role === null ? 'admin' : roleValido(b.role);
        if (role === 'master') throw new HttpError(400, 'operacao_bloqueada', 'Só existe um master, definido direto no banco. O painel cria apenas admins.');
        const empresaIds = await empresasValidas(b.empresa_ids);
        // modo: 'senha' (senha temporária única, troca obrigatória no 1º acesso), 'convite' (e-mail) ou 'link'.
        // Compatibilidade: sem "modo", enviar_email=false => link; caso contrário => convite.
        const modo = b.modo === 'senha' || b.modo === 'link' || b.modo === 'convite' ? b.modo : (b.enviar_email === undefined ? 'senha' : b.enviar_email === false ? 'link' : 'convite');
        // Fluxos que dependem de e-mail/link ficam DESLIGADOS até alguem ligar PERMITIR_FLUXO_EMAIL=true nos secrets.
        if (modo !== 'senha' && !emailLiberado) throw new HttpError(400, 'fluxo_email_desligado', 'Convites e links por e-mail estão desligados por enquanto. Use a senha temporária.');
        // Nunca existe senha padrão fixa: a temporária é aleatória, por usuário, mostrada uma única vez.
        let novo: { id: string }; let link: string | null = null; let senhaTemp: string | null = null;
        try {
          if (modo === 'convite') novo = await auth.convidar(email, nome, redirectTo);
          else if (modo === 'senha') { senhaTemp = gerarSenhaTemporaria(); novo = await auth.criarComSenha(email, nome, senhaTemp); }
          else { novo = await auth.criarSemEmail(email, nome); link = await auth.gerarLinkRecuperacao(email, redirectTo); }
        } catch (e) {
          throw new HttpError(400, 'falha_criar_usuario', sanitizarErro(e instanceof Error ? e.message : 'Falha ao criar usuário.'));
        }
        // o trigger já criou o perfil como admin INATIVO; aqui o master o ativa e define as empresas
        await adm.upsertPerfil({ id: novo.id, role, nome, ativo: true });
        const vinc = await adm.definirVinculos(novo.id, empresaIds, ch.userId);
        await deps.repo.insertAuditoria({
          usuario_id: ch.userId, acao: 'usuario_criado', entidade: 'usuarios_perfil', entidade_id: novo.id, ip,
          valor_novo: { email, nome, role, ativo: true, modo, empresa_ids: vinc.depois },
        });
        return json(200, { ok: true, id: novo.id, modo, empresa_ids: vinc.depois, link_definir_senha: link, senha_temporaria: senhaTemp }, cors);
      }

      if (acao === 'atualizar') {
        if (!isUuid(b.id)) throw new HttpError(400, 'dados_invalidos', 'id inválido.');
        const alvo = (await adm.listarPerfis()).find((p) => p.id === b.id);
        if (!alvo) throw new HttpError(404, 'nao_encontrado', 'Usuário não encontrado.');
        const patch: Partial<Pick<Perfil, 'nome' | 'ativo'>> = {};
        if (b.nome !== undefined) patch.nome = nomeValido(b.nome);
        // O perfil não muda por aqui: há um único master e todos os demais são admin.
        if (b.role !== undefined && b.role !== alvo.role) {
          throw new HttpError(400, 'operacao_bloqueada', 'O perfil não pode ser alterado: existe um único master e os demais usuários são admin.');
        }
        if (b.ativo !== undefined) {
          if (typeof b.ativo !== 'boolean') throw new HttpError(400, 'dados_invalidos', 'ativo deve ser true/false.');
          patch.ativo = b.ativo;
        }
        let novasEmpresas: string[] | null = null;
        if (b.empresa_ids !== undefined) {
          if (alvo.role === 'master') throw new HttpError(400, 'operacao_bloqueada', 'O master tem acesso a todas as empresas; não há lista de empresas para ele.');
          novasEmpresas = await empresasValidas(b.empresa_ids);
        }
        // trava de segurança: não se tira o próprio acesso nem o último master
        const perdeMaster = alvo.role === 'master' && alvo.ativo && patch.ativo === false;
        if (perdeMaster) {
          if (alvo.id === ch.userId) throw new HttpError(400, 'operacao_bloqueada', 'Você não pode remover o seu próprio acesso de master.');
          if ((await adm.contarMastersAtivos(alvo.id)) < 1) throw new HttpError(400, 'operacao_bloqueada', 'Não é possível remover o último master ativo.');
        }
        if (alvo.id === ch.userId && patch.ativo === false) throw new HttpError(400, 'operacao_bloqueada', 'Você não pode desativar a si mesmo.');
        if (!Object.keys(patch).length && novasEmpresas === null) throw new HttpError(400, 'dados_invalidos', 'Nada para atualizar.');
        if (Object.keys(patch).length) await adm.updatePerfil(alvo.id, patch);
        let banAplicado: boolean | null = null;
        if (patch.ativo !== undefined) {
          try { await auth.banir(alvo.id, patch.ativo === false); banAplicado = true; } catch { banAplicado = false; }
        }
        if (Object.keys(patch).length) {
          const anterior = { nome: alvo.nome, role: alvo.role, ativo: alvo.ativo };
          const novo = { ...anterior, ...patch };
          const acaoAud = patch.ativo !== undefined && patch.ativo !== alvo.ativo
            ? (patch.ativo ? 'usuario_ativado' : 'usuario_desativado') : 'usuario_atualizado';
          await deps.repo.insertAuditoria({
            usuario_id: ch.userId, acao: acaoAud, entidade: 'usuarios_perfil', entidade_id: alvo.id, valor_anterior: anterior, valor_novo: novo, ip,
          });
        }
        let empresasDepois: string[] | undefined;
        if (novasEmpresas !== null) {
          const v = await adm.definirVinculos(alvo.id, novasEmpresas, ch.userId);
          empresasDepois = v.depois;
          const igual = v.antes.length === v.depois.length && v.antes.every((x) => v.depois.includes(x));
          if (!igual) {
            await deps.repo.insertAuditoria({
              usuario_id: ch.userId, acao: 'usuario_empresas_alteradas', entidade: 'usuario_empresas', entidade_id: alvo.id, ip,
              valor_anterior: { empresa_ids: v.antes }, valor_novo: { empresa_ids: v.depois },
            });
          }
        }
        return json(200, { ok: true, ban_aplicado: banAplicado, ...(empresasDepois ? { empresa_ids: empresasDepois } : {}) }, cors);
      }

      if (acao === 'recuperar_senha') {
        if (!isUuid(b.id)) throw new HttpError(400, 'dados_invalidos', 'id inválido.');
        const conta = await auth.getUsuario(b.id);
        if (!conta || !conta.email) throw new HttpError(404, 'nao_encontrado', 'Usuário não encontrado.');
        let link: string | null = null; let senhaTemp: string | null = null;
        const modoRec = b.modo === 'senha' || b.modo === undefined && b.enviar_email === undefined ? 'senha' : (b.enviar_email === false || b.modo === 'link' ? 'link' : 'email');
        if (modoRec !== 'senha' && !emailLiberado) throw new HttpError(400, 'fluxo_email_desligado', 'Links e e-mails de redefinição estão desligados por enquanto. Use a nova senha temporária.');
        if (modoRec === 'senha') { senhaTemp = gerarSenhaTemporaria(); await auth.definirSenhaTemporaria(b.id, senhaTemp); }
        else if (modoRec === 'link') link = await auth.gerarLinkRecuperacao(conta.email, redirectTo);
        else await auth.enviarRecuperacao(conta.email, redirectTo);
        await deps.repo.insertAuditoria({
          usuario_id: ch.userId, acao: 'senha_recuperacao_solicitada', entidade: 'auth.users', entidade_id: b.id, ip,
          valor_novo: { modo: modoRec },
        });
        return json(200, { ok: true, modo: modoRec, link_definir_senha: link, senha_temporaria: senhaTemp }, cors);
      }

      throw new HttpError(400, 'acao_invalida', 'Ação desconhecida.');
    } catch (e) {
      return respostaDeErro(e, cors);
    }
  };
}

// ---------------------------------------------------------------------------
// admin-api  (SOMENTE master): configuração, preços, teste de conexão, execução manual
// ---------------------------------------------------------------------------
const MODELO_RE = /^[A-Za-z0-9][A-Za-z0-9._:\-]{0,79}$/;
const numOuNull = (v: unknown, nome: string, inteiro = false): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  if (!isFinite(n) || n < 0 || (inteiro && !Number.isInteger(n))) throw new HttpError(400, 'dados_invalidos', `${nome} inválido.`);
  return n;
};

export function criarHandlerAdminApi(deps: ExecDeps, getUser: GetUser, adm: AdminRepo) {
  return async (req: Request): Promise<Response> => {
    const cors = corsHeaders(deps.getEnv);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      if (req.method !== 'POST') throw new HttpError(405, 'metodo_invalido', 'Use POST.');
      const ch = await autenticar(deps.repo, getUser, req);
      exigirMaster(ch);
      const b = await lerJson(req);
      const ip = ipDe(req);
      const acao = String(b.acao || '');
      const empresaId = (): string => {
        if (!isUuid(b.empresa_id)) throw new HttpError(400, 'dados_invalidos', 'empresa_id inválido.');
        return b.empresa_id;
      };

      if (acao === 'obter_config') {
        const id = empresaId();
        const cfg = await deps.repo.getConfig(id, 'openai');
        const precos = await adm.listarPrecos();
        const nome = cfg ? nomeDoSegredo(cfg) : null;
        const stat = (n: string | null) => statusSegredo(n, deps.getEnv, (x) => adm.statusChave(x));
        const atual = await stat(nome);
        return json(200, {
          ok: true, config: cfg,
          // só diz SE existe chave (e os 4 últimos caracteres); nunca o valor
          credencial_presente: atual.presente,
          segredo_nome: nome, precos,
          chaves: { global: await stat(SEGREDO_GLOBAL), empresa: await stat(nomeChaveEmpresa(id)) },
        }, cors);
      }

      if (acao === 'salvar_chave') {
        // cadastra/substitui a chave no cofre. O valor entra aqui e NUNCA volta para o navegador.
        const escopo = String(b.escopo || '');
        if (escopo !== 'global' && escopo !== 'empresa') throw new HttpError(400, 'dados_invalidos', "escopo deve ser 'global' ou 'empresa'.");
        const id = escopo === 'empresa' ? empresaId() : null;
        if (id) {
          const emp = await deps.repo.getEmpresa(id);
          if (!emp) throw new HttpError(404, 'empresa_nao_encontrada', 'Empresa não encontrada.');
        }
        const valor = typeof b.valor === 'string' ? b.valor.trim() : '';
        if (!CHAVE_OPENAI_RE.test(valor)) throw new HttpError(400, 'chave_invalida', 'Isso não parece uma chave da OpenAI (começa com sk-). Cole só a chave, sem espaços.');
        const nome = id ? nomeChaveEmpresa(id) : SEGREDO_GLOBAL;
        const antes = await adm.statusChave(nome);
        await adm.definirChave(nome, valor);
        const depois = await adm.statusChave(nome);
        await deps.repo.insertAuditoria({
          usuario_id: ch.userId, empresa_id: id, acao: id ? 'api_chave_empresa_alterada' : 'api_chave_global_alterada',
          entidade: 'cofre_chave', entidade_id: nome, ip,
          valor_anterior: { presente: antes.presente, ultimos4: antes.ultimos4 }, valor_novo: { presente: depois.presente, ultimos4: depois.ultimos4 },
        });
        return json(200, { ok: true, nome, presente: depois.presente, ultimos4: depois.ultimos4 }, cors);
      }

      if (acao === 'salvar_config') {
        const id = empresaId();
        const emp = await deps.repo.getEmpresa(id);
        if (!emp) throw new HttpError(404, 'empresa_nao_encontrada', 'Empresa não encontrada.');
        const anterior = await deps.repo.getConfig(id, 'openai');
        if (typeof b.ativo !== 'boolean') throw new HttpError(400, 'dados_invalidos', 'ativo deve ser true/false.');
        const usaGlobal = b.usa_credencial_global !== false;
        let secretRef: string | null = null;
        if (!usaGlobal) {
          // chave específica: o nome é derivado da empresa (a chave é cadastrada em salvar_chave).
          // Nome livre só no formato antigo (secret de função) e sempre validado.
          if (b.secret_ref === undefined || b.secret_ref === null || b.secret_ref === '') secretRef = nomeChaveEmpresa(id);
          else if (typeof b.secret_ref === 'string' && SECRET_REF_RE.test(b.secret_ref)) secretRef = b.secret_ref;
          else throw new HttpError(400, 'dados_invalidos', 'secret_ref deve ser o nome de um secret no formato OPENAI_API_KEY_<NOME> (nunca a chave em si).');
        }
        let modelo: string | null = null;
        if (b.modelo_padrao !== undefined && b.modelo_padrao !== null && b.modelo_padrao !== '') {
          if (typeof b.modelo_padrao !== 'string' || !MODELO_RE.test(b.modelo_padrao)) throw new HttpError(400, 'dados_invalidos', 'modelo_padrao inválido.');
          modelo = b.modelo_padrao;
        }
        const novo = await adm.upsertConfig({
          empresa_id: id, provider: 'openai', ativo: b.ativo, usa_credencial_global: usaGlobal, secret_ref: secretRef,
          modelo_padrao: modelo,
          limite_mensal_usd: numOuNull(b.limite_mensal_usd, 'limite_mensal_usd'),
          limite_mensal_tokens: numOuNull(b.limite_mensal_tokens, 'limite_mensal_tokens', true),
          limite_diario_usd: numOuNull(b.limite_diario_usd, 'limite_diario_usd'),
          updated_by: ch.userId,
        });
        const ref = (c: ApiConfig | null) => c && ({ ativo: c.ativo, usa_credencial_global: c.usa_credencial_global, secret_ref: c.secret_ref, modelo_padrao: c.modelo_padrao,
          limite_mensal_usd: c.limite_mensal_usd, limite_mensal_tokens: c.limite_mensal_tokens, limite_diario_usd: c.limite_diario_usd });
        const a = ref(anterior), n = ref(novo)!;
        // um registro por tipo de mudança, para a trilha ser legível
        const mudou = (campos: string[]) => !a || campos.some((k) => (a as Record<string, unknown>)[k] !== (n as Record<string, unknown>)[k]);
        const log = (acaoAud: string) => deps.repo.insertAuditoria({ usuario_id: ch.userId, empresa_id: id, acao: acaoAud, entidade: 'empresa_api_config', entidade_id: novo.id, valor_anterior: a, valor_novo: n, ip });
        if (mudou(['usa_credencial_global', 'secret_ref'])) await log('api_credencial_alterada');
        if (mudou(['limite_mensal_usd', 'limite_mensal_tokens', 'limite_diario_usd'])) await log('api_limite_alterado');
        if (mudou(['ativo', 'modelo_padrao'])) await log('api_config_alterada');
        return json(200, { ok: true, config: novo }, cors);
      }

      if (acao === 'salvar_preco') {
        const modelo = String(b.modelo || '');
        if (!MODELO_RE.test(modelo)) throw new HttpError(400, 'dados_invalidos', 'modelo inválido.');
        const inp = numOuNull(b.input_usd_por_milhao, 'input_usd_por_milhao');
        const out = numOuNull(b.output_usd_por_milhao, 'output_usd_por_milhao');
        if (inp === null || out === null) throw new HttpError(400, 'dados_invalidos', 'Informe preço de entrada e de saída.');
        const novo = await adm.inserirPreco({
          provider: 'openai', modelo, vigente_desde: deps.now().toISOString(), input_usd_por_milhao: inp,
          cached_input_usd_por_milhao: numOuNull(b.cached_input_usd_por_milhao, 'cached_input_usd_por_milhao'), output_usd_por_milhao: out, ativo: true,
        });
        await deps.repo.insertAuditoria({ usuario_id: ch.userId, acao: 'preco_modelo_criado', entidade: 'api_model_pricing', entidade_id: novo.id, valor_novo: novo, ip });
        return json(200, { ok: true, preco: novo }, cors);
      }

      if (acao === 'testar_conexao' || acao === 'executar_teste') {
        const id = empresaId();
        const prompt = acao === 'testar_conexao' ? 'Responda apenas com a palavra: OK' : String(b.prompt || '').trim();
        if (!prompt || prompt.length > 2000) throw new HttpError(400, 'dados_invalidos', 'Informe um prompt de até 2000 caracteres.');
        const r = await executarIA(deps, ch, {
          empresa_id: id, operacao: acao === 'testar_conexao' ? 'teste_conexao' : 'execucao_teste', modulo: 'admin',
          modelo: b.modelo || undefined,
          payload: { input: prompt, max_output_tokens: acao === 'testar_conexao' ? 16 : 512 },
        }, { somenteMaster: true });
        await deps.repo.insertAuditoria({
          usuario_id: ch.userId, empresa_id: id, acao: acao === 'testar_conexao' ? 'api_teste_conexao' : 'api_execucao_manual',
          entidade: 'api_execucoes', entidade_id: String(r.body.execucao_id ?? ''), ip,
          valor_novo: { status_http: r.status, ok: r.body.ok === true, code: r.body.code ?? null },
        });
        // nada de chave aqui: só métricas
        const { ok, code, message, execucao_id, modelo, provider, uso, custo_estimado_usd, latencia_ms, request_id_provider, texto } = r.body as Record<string, unknown>;
        return json(r.status === 200 ? 200 : r.status, {
          ok, code, message, execucao_id, provider, modelo, uso, custo_estimado_usd, latencia_ms, request_id_provider,
          ...(acao === 'executar_teste' ? { texto } : { resposta_ok: typeof texto === 'string' ? texto.trim().toUpperCase().startsWith('OK') : false }),
        }, cors);
      }

      throw new HttpError(400, 'acao_invalida', 'Ação desconhecida.');
    } catch (e) {
      return respostaDeErro(e, cors);
    }
  };
}

// ---------------------------------------------------------------------------
// trocar-senha  (usuário logado com senha temporária define a senha definitiva)
// Só funciona enquanto a conta está marcada como "deve trocar a senha". Aceita o JWT
// do próprio usuário; nenhuma outra função aceita quem ainda está com a senha temporária.
// ---------------------------------------------------------------------------
export function criarHandlerTrocarSenha(deps: ExecDeps, getUser: GetUser, auth: AdminAuth) {
  return async (req: Request): Promise<Response> => {
    const cors = corsHeaders(deps.getEnv);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      if (req.method !== 'POST') throw new HttpError(405, 'metodo_invalido', 'Use POST.');
      const ch = await autenticar(deps.repo, getUser, req, { permitirSenhaProvisoria: true });
      if (!ch.deveTrocarSenha) throw new HttpError(409, 'nao_necessario', 'Sua senha não precisa ser trocada agora.');
      const b = await lerJson(req);
      const nova = validarSenhaNova(b.nova_senha, ch.email);
      // a nova senha não pode ser a própria senha temporária
      if (ch.email && await auth.senhaConfere(ch.email, nova)) {
        throw new HttpError(400, 'senha_fraca', 'A nova senha precisa ser diferente da senha temporária.');
      }
      await auth.definirSenhaDefinitiva(ch.userId, nova);
      await deps.repo.insertAuditoria({
        usuario_id: ch.userId, acao: 'senha_definida_primeiro_acesso',
        entidade: 'auth.users', entidade_id: ch.userId, ip: ipDe(req),
      });
      return json(200, { ok: true }, cors);
    } catch (e) {
      return respostaDeErro(e, cors);
    }
  };
}

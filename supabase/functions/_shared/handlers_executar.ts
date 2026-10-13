// Handler HTTP da função executar-ai, isolado de propósito: é a única função que toca a chave da API,
// então o pacote publicado dela leva o MENOR código possível (sem criação de usuários, senhas, etc.).
import { autenticar } from './autorizacao.ts';
import { HttpError } from './errors.ts';
import { corsHeaders, json, lerJson, respostaDeErro } from './http.ts';
import { executarIA } from './executar.ts';
import { consultarElegibilidade } from './analise.ts';
import type { ExecDeps } from './executar.ts';
import type { GetUser } from './types.ts';

// executar-ai (somente master nas operações assistidas; admin nas demais, só na própria empresa)
export function criarHandlerExecutarAi(deps: ExecDeps, getUser: GetUser) {
  return async (req: Request): Promise<Response> => {
    const cors = corsHeaders(deps.getEnv);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      if (req.method !== 'POST') throw new HttpError(405, 'metodo_invalido', 'Use POST.');
      const ch = await autenticar(deps.repo, getUser, req);
      const body = await lerJson(req);
      if (body.acao === 'elegibilidade') return json(200, await consultarElegibilidade(deps.repo, ch, body), cors);
      const r = await executarIA(deps, ch, body);
      return json(r.status, r.body, cors);
    } catch (e) {
      return respostaDeErro(e, cors);
    }
  };
}

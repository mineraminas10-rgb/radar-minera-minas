// POST /functions/v1/executar-ai   (JWT do usuário obrigatório)
// Corpo: { empresa_id, carteira_id, event_id, execucao_id, operacao, prompt, modulo?, modelo?, payload:{input,...} }
// A chave da API vive só no cofre (Vault) / secrets desta função.
import { criarHandlerExecutarAi } from '../_shared/handlers_executar.ts';
import { criarGetUser, criarRepo, depsProducao } from '../_shared/prod_repo.ts';

Deno.serve(criarHandlerExecutarAi(depsProducao(criarRepo()), criarGetUser()));

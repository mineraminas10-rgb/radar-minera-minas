// Prompts VERSIONADOS. Nenhum texto de prompt fica solto no código: toda operação de módulo
// (M8, M9A, ...) usa uma entrada deste registro, identificada por nome + versão. A versão e o
// hash do texto são gravados em api_execucoes. Para mudar um prompt: criar NOME_V2 (nova
// versão) e desativar a anterior — mudar o texto de uma versão existente é proibido (o teste
// de "congelamento" falha).
export interface PromptReg {
  nome: string;
  versao: string;
  modulo: string;
  operacao: string;
  ativo: boolean;
  instructions: string;
  schema: Record<string, unknown>;      // JSON Schema (modo estrito) da resposta esperada
}

const REGRA_BASE =
  'Use SOMENTE o texto fornecido. Não invente fatos, números, datas, nomes, processos ou fontes. ' +
  'Se uma informação não estiver no texto, use null. Não atribua score, prioridade nem faixa. ' +
  'Responda apenas com o JSON do schema, sem comentários.';

const obj = (props: Record<string, unknown>) => ({
  type: 'object', additionalProperties: false, required: Object.keys(props), properties: props,
});
const str = { type: 'string' };
const strNull = { type: ['string', 'null'] };

export const PROMPTS: PromptReg[] = [
  {
    nome: 'M8_CLASSIFICACAO', versao: 'V1', modulo: 'm8', operacao: 'classificacao', ativo: true,
    instructions: 'Você classifica um comunicado de acidente ambiental da SEMAD/MG quanto ao vínculo com atividade minerária. ' +
      'Escolha vinculo: "confirmado" (o texto liga o acidente a empresa, mina, barragem ou estrutura minerária), ' +
      '"provavel" (indícios fortes, sem confirmação literal), "ambiguo" ou "nao_minerario". Cite em trecho_literal o trecho do texto que sustenta a escolha. ' + REGRA_BASE,
    schema: obj({ vinculo: { enum: ['confirmado', 'provavel', 'ambiguo', 'nao_minerario'] }, trecho_literal: strNull }),
  },
  {
    nome: 'M8_EXTRACAO', versao: 'V1', modulo: 'm8', operacao: 'extracao_estruturada', ativo: true,
    instructions: 'Extraia do comunicado de acidente ambiental os campos pedidos, copiando valores como aparecem no texto. ' + REGRA_BASE,
    schema: obj({ empresa_citada: strNull, local_descrito: strNull, data_hora_ocorrencia: strNull, produto: strNull, volume_quantidade: strNull, atingiu_curso_agua: { type: ['boolean', 'null'] }, trecho_evidencia: strNull }),
  },
  {
    nome: 'M8_PRE_RELEASE', versao: 'V1', modulo: 'm8', operacao: 'pre_release', ativo: true,
    instructions: 'Redija um rascunho de pré-release (até 120 palavras, tom factual e neutro) sobre o acidente descrito, usando apenas os fatos do texto fornecido. ' +
      'Liste em lacunas o que NÃO consta no texto e seria necessário apurar. O rascunho passa por revisão humana antes de qualquer uso. ' + REGRA_BASE,
    schema: obj({ rascunho: str, lacunas: { type: 'array', items: str } }),
  },
  {
    nome: 'M9A_CLASSIFICACAO', versao: 'V1', modulo: 'm9a', operacao: 'classificacao', ativo: true,
    instructions: 'Você classifica uma movimentação de processo minerário da ANM quanto à natureza do ato. ' +
      'Escolha natureza: "ato_material" (muda direitos, titularidade, fase ou prazo), "ato_acessorio" ou "indeterminado". ' + REGRA_BASE,
    schema: obj({ natureza: { enum: ['ato_material', 'ato_acessorio', 'indeterminado'] }, justificativa_curta: strNull }),
  },
  {
    nome: 'M9A_ENRIQUECIMENTO', versao: 'V1', modulo: 'm9a', operacao: 'avaliacao_editorial', ativo: true,
    instructions: 'Resuma o que mudou no processo minerário entre o estado anterior e o atual (campo delta), em até 60 palavras e tom factual. ' +
      'Em lacunas, liste o que não consta nos dados e exigiria apuração humana. ' + REGRA_BASE,
    schema: obj({ resumo_delta: str, lacunas: { type: 'array', items: str } }),
  },
  {
    nome: 'M6_ENRIQUECIMENTO', versao: 'V1', modulo: 'm6', operacao: 'avaliacao_editorial', ativo: true,
    instructions: 'Resuma, em até 60 palavras e tom factual, o ato de outorga/portaria do IGAM descrito no texto: o que foi decidido (verbo decisório), sobre qual processo ou portaria e para qual usuário. ' +
      'Em lacunas, liste o que não consta no texto e exigiria apuração humana (por exemplo finalidade do uso da água, vazão, vínculo com atividade minerária). ' + REGRA_BASE,
    schema: obj({ resumo_ato: str, lacunas: { type: 'array', items: str } }),
  },
];

// ---------------------------------------------------------------------------------------------
// OPERAÇÃO ASSISTIDA — analise_editorial (7 seções separadas, saída validada no servidor).
// A entrada é o DOSSIÊ do evento montado no servidor (campos do evento + evidências numeradas [n]).
// A IA nunca altera score/status, nunca libera publicação: a resposta é rascunho para revisão humana.
// ---------------------------------------------------------------------------------------------
const citacoes = { type: 'array', items: { type: 'integer' } };

export const SCHEMA_ANALISE_EDITORIAL: Record<string, unknown> = obj({
  fato_confirmado: obj({ texto: str, citacoes }),
  contexto_documental: obj({ texto: str, citacoes }),
  avaliacao_editorial: obj({ texto: str }),
  hipotese_apuracao: obj({ texto: str }),
  lacunas: { type: 'array', items: str },
  perguntas_redacao: { type: 'array', items: str },
  proposta_abordagem: obj({ texto: str, rascunho_pre_release: strNull }),
});

const REGRA_ANALISE =
  'Trabalhe SOMENTE com o dossiê fornecido (campos do evento e evidências numeradas [n]). ' +
  'Nunca invente fatos, números, datas, nomes, processos, valores, causas ou consequências; se algo não está no dossiê, não afirme: registre em "lacunas". ' +
  'Separe estritamente as 7 seções do schema. ' +
  '(1) fato_confirmado: apenas o que está literalmente sustentado pelas evidências, com os números [n] usados em "citacoes". ' +
  '(2) contexto_documental: o que os documentos do dossiê informam além do fato (tipo de ato, instrumento, local), também com citações. ' +
  '(3) avaliacao_editorial: seu julgamento sobre o interesse jornalístico, escrito como opinião e sem números que não estejam no dossiê. ' +
  '(4) hipotese_apuracao: uma hipótese a VERIFICAR, redigida como hipótese, nunca como fato. ' +
  '(5) lacunas: o que falta no dossiê para confirmar o caso. ' +
  '(6) perguntas_redacao: perguntas objetivas que a redação deve fazer a fontes, empresa ou órgão. ' +
  '(7) proposta_abordagem: sugestão de abordagem e, se couber, rascunho_pre_release (até 120 palavras, factual, só com o que está em fato_confirmado; senão null). ' +
  'Não atribua score, nota, prioridade ou faixa e não recomende publicar ou liberar: a decisão é humana. ' +
  'Não afirme vínculo com mineração, dano ambiental, infração ou responsabilidade que o dossiê não afirme literalmente. ' +
  'Responda apenas com o JSON do schema.';

PROMPTS.push(
  {
    nome: 'M8_ANALISE_EDITORIAL', versao: 'V1', modulo: 'm8', operacao: 'analise_editorial', ativo: false,
    instructions: 'O dossiê descreve um comunicado de acidente ambiental da SEMAD/MG que uma regra determinística já classificou como de vínculo provável ou confirmado com atividade minerária. ' + REGRA_ANALISE,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
  {
    nome: 'M9A_ANALISE_EDITORIAL', versao: 'V1', modulo: 'm9a', operacao: 'analise_editorial', ativo: false,
    instructions: 'O dossiê descreve um ato ou movimentação de processo minerário da ANM que uma regra determinística já classificou como mudança material. ' + REGRA_ANALISE,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
  {
    nome: 'M6_ANALISE_EDITORIAL', versao: 'V1', modulo: 'm6', operacao: 'analise_editorial', ativo: false,
    instructions: 'O dossiê descreve um ato de outorga ou portaria do IGAM que o filtro determinístico do coletor manteve em apuração. O vínculo com atividade minerária pode não estar estabelecido: se não estiver, diga isso em lacunas. ' + REGRA_ANALISE,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
);

// V2 (piloto, 1ª rodada): a V1 não dizia o tamanho máximo das listas (uma resposta veio com 7 perguntas) nem como escrever datas
// (uma data ISO do dossiê foi reescrita em formato brasileiro). O texto da V1 fica congelado e desativado; a V2 acrescenta só isso.
const LIMITES_V2 =
  'Limites obrigatórios: "lacunas" com no máximo 8 itens e "perguntas_redacao" com no máximo 6 itens (escolha as mais importantes, não liste todas); ' +
  'cada item de lista com no máximo 280 caracteres; cada texto com no máximo 1.400 caracteres. ' +
  'Datas: copie-as como estão no dossiê (aaaa-mm-dd) ou escreva dd/mm/aaaa com os mesmos dia, mês e ano; nunca calcule nem deduza datas, prazos ou vencimentos que o dossiê não traga. ';
const REGRA_ANALISE_V2 = REGRA_ANALISE.replace(/Responda apenas com o JSON do schema\.$/, LIMITES_V2 + 'Responda apenas com o JSON do schema.');

PROMPTS.push(
  {
    nome: 'M8_ANALISE_EDITORIAL', versao: 'V2', modulo: 'm8', operacao: 'analise_editorial', ativo: true,
    instructions: 'O dossiê descreve um comunicado de acidente ambiental da SEMAD/MG que uma regra determinística já classificou como de vínculo provável ou confirmado com atividade minerária. ' + REGRA_ANALISE_V2,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
  {
    nome: 'M9A_ANALISE_EDITORIAL', versao: 'V2', modulo: 'm9a', operacao: 'analise_editorial', ativo: true,
    instructions: 'O dossiê descreve um ato ou movimentação de processo minerário da ANM que uma regra determinística já classificou como mudança material. ' + REGRA_ANALISE_V2,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
  {
    nome: 'M6_ANALISE_EDITORIAL', versao: 'V2', modulo: 'm6', operacao: 'analise_editorial', ativo: true,
    instructions: 'O dossiê descreve um ato de outorga ou portaria do IGAM que o filtro determinístico do coletor manteve em apuração. O vínculo com atividade minerária pode não estar estabelecido: se não estiver, diga isso em lacunas. ' + REGRA_ANALISE_V2,
    schema: SCHEMA_ANALISE_EDITORIAL,
  },
);

export function buscarPrompt(nomeCompleto: string): PromptReg | null {
  return PROMPTS.find((p) => `${p.nome}_${p.versao}` === nomeCompleto) ?? null;
}
export const idPrompt = (p: PromptReg) => `${p.nome}_${p.versao}`;

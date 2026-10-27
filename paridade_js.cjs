// Oráculo: roda as regras ANTIGAS do index.html (JS) sobre os mesmos cenários e imprime o resultado em JSON.
const fs = require('fs');
const [,, indexPath, cenariosPath] = process.argv;
const html = fs.readFileSync(indexPath, 'utf8');
const ini = html.indexOf('const SCORE_CORTE');
const fim = html.indexOf('// Motivos que impedem avançar');
const iM = html.indexOf('function montarItemFila');
const fM = html.indexOf('async function carregarFila');
const iC = html.indexOf('function compararItens');
const fC = html.indexOf('function renderFila');
if ([ini, fim, iM, fM, iC, fC].some(x => x < 0)) { console.error('trechos não encontrados'); process.exit(2); }
const codigo = html.slice(ini, fim) + '\n' + html.slice(iM, fM) + '\n' + html.slice(iC, fC);
const fabrica = new Function('esc', 'document', 'iaAnalisados', codigo + '\nagoraMs = () => Date.parse("2026-10-20T00:00:00Z");\nreturn { montarItemFila, compararItens };');
const { montarItemFila, compararItens } = fabrica(x => x, { getElementById: () => null }, {});
const cenarios = JSON.parse(fs.readFileSync(cenariosPath, 'utf8'));
const itens = cenarios.map(c => {
  const e = { id: c.id, status_editorial: c.status, data_evento: c.data_evento, data_publicacao: null, created_at: c.created_at, url_oficial: c.url_oficial || null,
              evidencias: c.evidencias, documentos: c.documentos };
  const vig = c.score ? { estagio: c.score.estagio, score_normalizado: c.score.valor, score_relevancia: c.score.estagio === 'editorial' ? c.score.valor : null,
                          componentes: c.comp, versao_score: 'V', prioridade: 'B' }
                       : { estagio: null, score_normalizado: null, score_relevancia: null, componentes: c.comp, versao_score: null, prioridade: 'B' };   // linha de score sem valor
  return montarItemFila(e, vig, {});
});
const ordem = [...itens].sort(compararItens).map(i => i.event.id);
const saida = {};
for (const i of itens) saida[i.event.id] = {
  codigo: i.prioridadeEditorial.codigo, motivo: i.prioridadeEditorial.motivo, texto: i.prioridadeEditorial.texto, aviso: i.prioridadeEditorial.aviso,
  inedito: i.ineditismo.inedito, atualizado: i.atual.atualizado, qualidade: i.qualidadeEvidencia, situacao: i.situacao.codigo,
  criticidade: i.criticidade, decisorio: i.decisao.score_decisorio, valor: i.decisao.score_valor, material_ts: i.atual.material.ts };
console.log(JSON.stringify({ saida, ordem }));

// Senha temporária de primeiro acesso + regras da senha definitiva.
// A senha temporária é ALEATÓRIA e DIFERENTE para cada usuário (nunca uma senha padrão fixa),
// aparece uma única vez para o master e nunca é gravada em log, auditoria ou tabela.
import { HttpError } from './errors.ts';

// sem caracteres ambíguos (0/O, 1/l/I) para ser fácil de ditar/copiar
const MAIUSC = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
const MINUSC = 'abcdefghijkmnpqrstuvwxyz';
const NUMS = '23456789';
const TODOS = MAIUSC + MINUSC + NUMS;

function sorteio(n: number): number {
  // sorteio uniforme sem viés de módulo
  const lim = Math.floor(0x100000000 / n) * n;
  const buf = new Uint32Array(1);
  do { crypto.getRandomValues(buf); } while (buf[0] >= lim);
  return buf[0] % n;
}
const pick = (s: string) => s[sorteio(s.length)];

export function gerarSenhaTemporaria(tamanho = 14): string {
  const chars = [pick(MAIUSC), pick(MINUSC), pick(NUMS)];
  while (chars.length < tamanho) chars.push(pick(TODOS));
  for (let i = chars.length - 1; i > 0; i--) { const j = sorteio(i + 1); [chars[i], chars[j]] = [chars[j], chars[i]]; }
  return chars.join('');
}

const COMUNS = new Set([
  '123456', '1234567', '12345678', '123456789', '1234567890', 'password', 'senha', 'senha123', 'senha1234', 'admin', 'admin123',
  'qwerty', 'qwerty123', 'abc123', 'abcd1234', '111111', '000000', 'radar123', 'radar1234', 'minera123', 'mudar123', 'trocar123',
]);

export const SENHA_MIN = 10;
export const SENHA_MAX = 72;

// Regras da senha definitiva: 10+ caracteres, letra e número, nada de senha óbvia nem o próprio e-mail.
export function validarSenhaNova(senha: unknown, email?: string | null): string {
  if (typeof senha !== 'string') throw new HttpError(400, 'senha_fraca', 'Informe a nova senha.');
  if (senha.length < SENHA_MIN) throw new HttpError(400, 'senha_fraca', `A senha precisa ter pelo menos ${SENHA_MIN} caracteres.`);
  if (senha.length > SENHA_MAX) throw new HttpError(400, 'senha_fraca', `A senha pode ter no máximo ${SENHA_MAX} caracteres.`);
  if (!/[A-Za-z]/.test(senha) || !/[0-9]/.test(senha)) throw new HttpError(400, 'senha_fraca', 'Use letras e números na senha.');
  if (/^(.)\1+$/.test(senha)) throw new HttpError(400, 'senha_fraca', 'Escolha uma senha menos previsível.');
  const baixa = senha.toLowerCase();
  if (COMUNS.has(baixa) || /^(0123456789|1234567890|abcdefghij)/.test(baixa)) throw new HttpError(400, 'senha_fraca', 'Essa senha é muito comum. Escolha outra.');
  if (email && (baixa === email.toLowerCase() || baixa === email.split('@')[0].toLowerCase())) {
    throw new HttpError(400, 'senha_fraca', 'A senha não pode ser igual ao seu e-mail.');
  }
  return senha;
}

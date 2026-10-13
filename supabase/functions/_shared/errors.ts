export class HttpError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// Remove qualquer coisa que pareça chave/token antes de gravar ou devolver um erro.
// (Erros do provedor às vezes ecoam parte da chave: "Incorrect API key provided: sk-...abcd".)
export function sanitizarErro(msg: unknown, segredos: Array<string | undefined | null> = []): string {
  let s = String(msg ?? '');
  for (const seg of segredos) {
    if (seg && seg.length >= 6) s = s.split(seg).join('[redigido]');
  }
  s = s.replace(/sk-[A-Za-z0-9_\-*.]{6,}/g, '[redigido]')
       .replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, 'Bearer [redigido]')
       .replace(/eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*/g, '[redigido]');
  return s.length > 500 ? s.slice(0, 500) + '…' : s;
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (v: unknown): v is string => typeof v === 'string' && UUID_RE.test(v);

import { HttpError } from './errors.ts';

export function corsHeaders(getEnv: (n: string) => string | undefined): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': getEnv('ALLOWED_ORIGIN') || '*',
    'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Vary': 'Origin',
  };
}

export function json(status: number, body: unknown, cors: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

export async function lerJson(req: Request, maxBytes = 200_000): Promise<Record<string, unknown>> {
  const len = Number(req.headers.get('content-length') || '0');
  if (len > maxBytes) throw new HttpError(413, 'payload_grande', 'Requisição grande demais.');
  const txt = await req.text();
  if (txt.length > maxBytes) throw new HttpError(413, 'payload_grande', 'Requisição grande demais.');
  try {
    const v = JSON.parse(txt || '{}');
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('não é objeto');
    return v as Record<string, unknown>;
  } catch {
    throw new HttpError(400, 'json_invalido', 'Corpo da requisição não é um JSON válido.');
  }
}

export function respostaDeErro(e: unknown, cors: Record<string, string>): Response {
  if (e instanceof HttpError) {
    return json(e.status, { ok: false, code: e.code, message: e.message }, cors);
  }
  console.error('erro inesperado:', e instanceof Error ? e.message : 'desconhecido');
  return json(500, { ok: false, code: 'erro_interno', message: 'Erro interno. Tente novamente.' }, cors);
}

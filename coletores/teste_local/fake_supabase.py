"""
Shim LOCAL-ONLY para testar db_writer.py/main.py dos coletores (M8/M9A)
contra um Postgres local (réplica que espelha o schema de produção), sem
precisar de um projeto Supabase real nem do binário PostgREST (nenhum dos
dois está disponível neste ambiente de desenvolvimento).

Implementa só o subconjunto da API fluente do `supabase-py` que
db_writer.py de fato usa (select/insert/update/upsert/eq/neq/is_/order/
limit/execute) — não é um mock de comportamento, é uma tradução real para
SQL executado contra Postgres de verdade via psycopg2, então os resultados
refletem o schema e as constraints reais (FKs, checks, unique), não um
double artificial.

NÃO é usado pelo coletor em produção — get_client() em db_writer.py
continua lendo SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY normalmente e
falando com o Supabase real via supabase-py. Este arquivo só existe para
os testes locais deste diretório (_teste_local/), nunca é importado pelo
código de produção.
"""
import json
import psycopg2
import psycopg2.extras


def _adapt(value):
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value)
    return value


class _Resultado:
    def __init__(self, data):
        self.data = data


class _QueryBuilder:
    def __init__(self, conn, tabela):
        self.conn = conn
        self.tabela = tabela
        self.modo = None
        self.payload = None
        self.on_conflict = None
        self.filtros = []  # list of (op, col, val)
        self.order_col = None
        self.order_desc = False
        self.limite = None
        self.select_cols = "*"

    def select(self, cols="*"):
        self.modo = self.modo or "select"
        self.select_cols = cols
        return self

    def insert(self, payload):
        self.modo = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.modo = "update"
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.modo = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def eq(self, col, val):
        self.filtros.append(("=", col, val))
        return self

    def neq(self, col, val):
        self.filtros.append(("<>", col, val))
        return self

    def is_(self, col, val):
        # supabase-py usa is_(col, "null") para IS NULL
        self.filtros.append(("is", col, None if val == "null" else val))
        return self

    def order(self, col, desc=False):
        self.order_col = col
        self.order_desc = desc
        return self

    def limit(self, n):
        self.limite = n
        return self

    def _where_sql(self):
        if not self.filtros:
            return "", []
        partes, valores = [], []
        for op, col, val in self.filtros:
            if op == "is":
                partes.append(f'"{col}" IS NULL')
            else:
                partes.append(f'"{col}" {op} %s')
                valores.append(val)
        return " WHERE " + " AND ".join(partes), valores

    def execute(self):
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            if self.modo in (None, "select"):
                cols = self.select_cols if self.select_cols != "*" else "*"
                if cols != "*":
                    cols = ", ".join(f'"{c.strip()}"' for c in cols.split(","))
                sql = f'SELECT {cols} FROM "{self.tabela}"'
                where_sql, valores = self._where_sql()
                sql += where_sql
                if self.order_col:
                    sql += f' ORDER BY "{self.order_col}" {"DESC" if self.order_desc else "ASC"}'
                if self.limite:
                    sql += f" LIMIT {int(self.limite)}"
                cur.execute(sql, valores)
                rows = cur.fetchall()
                return _Resultado([dict(r) for r in rows])

            if self.modo == "insert":
                payload = self.payload
                linhas = payload if isinstance(payload, list) else [payload]
                resultados = []
                for linha in linhas:
                    cols = list(linha.keys())
                    col_sql = ", ".join(f'"{c}"' for c in cols)
                    ph_sql = ", ".join(["%s"] * len(cols))
                    valores = [_adapt(linha[c]) for c in cols]
                    sql = f'INSERT INTO "{self.tabela}" ({col_sql}) VALUES ({ph_sql}) RETURNING *'
                    cur.execute(sql, valores)
                    resultados.append(dict(cur.fetchone()))
                self.conn.commit()
                return _Resultado(resultados)

            if self.modo == "update":
                payload = self.payload
                cols = list(payload.keys())
                set_sql = ", ".join(f'"{c}" = %s' for c in cols)
                valores = [_adapt(payload[c]) for c in cols]
                where_sql, where_valores = self._where_sql()
                sql = f'UPDATE "{self.tabela}" SET {set_sql}{where_sql} RETURNING *'
                cur.execute(sql, valores + where_valores)
                rows = [dict(r) for r in cur.fetchall()]
                self.conn.commit()
                return _Resultado(rows)

            if self.modo == "upsert":
                payload = self.payload
                cols = list(payload.keys())
                col_sql = ", ".join(f'"{c}"' for c in cols)
                ph_sql = ", ".join(["%s"] * len(cols))
                valores = [_adapt(payload[c]) for c in cols]
                conflito_cols = [c.strip() for c in (self.on_conflict or "").split(",") if c.strip()]
                conflito_sql = ", ".join(f'"{c}"' for c in conflito_cols)
                update_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in conflito_cols)
                sql = (f'INSERT INTO "{self.tabela}" ({col_sql}) VALUES ({ph_sql}) '
                       f'ON CONFLICT ({conflito_sql}) DO UPDATE SET {update_sql} RETURNING *')
                cur.execute(sql, valores)
                row = dict(cur.fetchone())
                self.conn.commit()
                return _Resultado([row])

            raise RuntimeError(f"modo de query não suportado: {self.modo}")
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()


class FakeSupabaseClient:
    """Substitui o `Client` do supabase-py nos testes locais. Uso:
    `sb = FakeSupabaseClient(dsn="dbname=radar_draft_test ...")`, depois
    passa `sb` direto pras funções de db_writer.py (elas só chamam
    sb.table(...), nunca instanciam o client sozinhas)."""

    def __init__(self, dsn: str):
        self.conn = psycopg2.connect(dsn)

    def table(self, nome: str) -> _QueryBuilder:
        return _QueryBuilder(self.conn, nome)

    def close(self):
        self.conn.close()

"""
PostgreSQL management (Databases → PostgreSQL).

Isolation model — one database per project/website, nothing shared:
  * every database has a login role with the SAME name, owning it;
  * pg_hba allows a role to connect only to its own database (`sameuser`),
    from 127.0.0.1 with a password — see deploy/serverhub-postgres.sh;
  * PUBLIC is revoked from every database; roles are NOSUPERUSER, NOCREATEDB,
    NOCREATEROLE, with a connection limit and a statement timeout, so one
    project can neither read another's data nor starve the server.

The panel talks to PostgreSQL as the `postgres` admin over the local socket
(peer auth mapped to the panel user — no admin password exists). Anything a
person runs from the panel (query runner, import) runs under the database's
own role, so it has exactly that project's rights and no more.
"""
from __future__ import annotations

import re
import secrets
import string
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from ..config import settings

SOCKET_DIR = "/var/run/postgresql"
HELPER = str(settings.PANEL_ROOT / "bin" / "serverhub-postgres")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
RESERVED = {"postgres", "template0", "template1", "serverhub", "root", "admin", "public", "pg_signal_backend"}
STATEMENT_TIMEOUT = "5min"          # per role: a runaway query can't hog the server
QUERY_TIMEOUT = "60s"               # the panel's query runner
MAX_ROWS = 1000
# The runner works under the database's role; these would step out of it.
_ESCAPE_RE = re.compile(r"\b(reset\s+role|set\s+(local\s+|session\s+)?role|session\s+authorization|"
                        r"reset\s+all|set\s+(local\s+|session\s+)?session_authorization)\b", re.I)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _psycopg():
    try:
        import psycopg
        from psycopg import sql
        return psycopg, sql
    except ImportError:
        raise HTTPException(500, "The psycopg package is missing — run deploy/update.sh to install it.")


def check_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not NAME_RE.match(name) or name in RESERVED or name.startswith("pg_"):
        raise HTTPException(400, "Name: 3–63 characters, lowercase letters, numbers and _ , "
                                 "starting with a letter (and not a reserved name).")
    return name


def new_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(32))


def server_port() -> int:
    """
    The port PostgreSQL listens on. 5432 normally — but when something else on
    the server (e.g. a Docker container) already holds 5432, the helper picks
    the next free one and writes it to conf.d/serverhub.conf.
    """
    for conf in sorted(Path("/etc/postgresql").glob("*/main/conf.d/serverhub.conf"), reverse=True):
        try:
            m = re.search(r"(?m)^\s*port\s*=\s*'?(\d+)", conf.read_text(encoding="utf-8"))
        except OSError:
            continue
        if m:
            return int(m.group(1))
    return 5432


def connect(database: str = "postgres"):
    psycopg, _ = _psycopg()
    try:
        return psycopg.connect(host=SOCKET_DIR, port=server_port(), user="postgres", dbname=database,
                               autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        raise HTTPException(503, f"Can't reach PostgreSQL: {str(exc).strip()[:300]}")


def _helper(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["sudo", "-n", HELPER, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "sudo not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------
def status() -> dict:
    code, out = _helper("status")
    info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    st = {"installed": info.get("installed") == "yes", "running": info.get("running") == "yes",
          "version": info.get("version"), "port": int(info.get("port") or 5432), "helper": code == 0}
    if code != 0:
        st["error"] = out[-300:] or "The PostgreSQL helper isn't installed yet — run deploy/update.sh."
    if st["running"]:
        try:
            with connect() as conn:
                row = conn.execute("""SELECT current_setting('server_version'),
                                             current_setting('shared_buffers'),
                                             current_setting('max_connections')::int,
                                             (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend')
                                   """).fetchone()
                st.update(server_version=row[0], shared_buffers=row[1], max_connections=row[2], connections=row[3])
        except HTTPException as exc:
            st["error"] = exc.detail
    return st


def install() -> str:
    code, out = _helper("install", timeout=900)
    if code != 0:
        raise HTTPException(500, f"Install failed: {out[-800:]}")
    return out


def reconfigure() -> str:
    code, out = _helper("configure", timeout=120)
    if code != 0:
        raise HTTPException(500, f"Configure failed: {out[-800:]}")
    return out


# ---------------------------------------------------------------------------
# databases
# ---------------------------------------------------------------------------
def list_databases() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""
            SELECT d.datname, pg_database_size(d.datname), r.rolconnlimit,
                   COALESCE(s.numbackends, 0)
            FROM pg_database d
            LEFT JOIN pg_roles r ON r.rolname = d.datname
            LEFT JOIN pg_stat_database s ON s.datname = d.datname
            WHERE NOT d.datistemplate AND d.datname <> 'postgres'
            ORDER BY d.datname""").fetchall()
    return [{"name": n, "size": size, "conn_limit": limit, "connections": active} for n, size, limit, active in rows]


def create_database(name: str, conn_limit: int = 20) -> str:
    """Role + database of the same name, locked to each other. Returns the password."""
    _, sql = _psycopg()
    name = check_name(name)
    conn_limit = max(1, min(int(conn_limit or 20), 50))
    password = new_password()
    ident = sql.Identifier(name)
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s UNION ALL "
                              "SELECT 1 FROM pg_database WHERE datname = %s", (name, name)).fetchone()
        if exists:
            raise HTTPException(409, f"A database or user named “{name}” already exists.")
        conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                             "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {}")
                     .format(ident, sql.Literal(password), sql.Literal(conn_limit)))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(ident, sql.Literal(STATEMENT_TIMEOUT)))
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(ident, ident))
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(ident))
    with connect(name) as conn:
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(ident))
    return password


def set_password(name: str) -> str:
    _, sql = _psycopg()
    name = check_name(name)
    password = new_password()
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone():
            raise HTTPException(404, f"No database user “{name}”.")
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))
    return password


def set_conn_limit(name: str, limit: int) -> None:
    _, sql = _psycopg()
    with connect() as conn:
        conn.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT {}")
                     .format(sql.Identifier(check_name(name)), sql.Literal(max(1, min(int(limit), 50)))))


def drop_database(name: str) -> Path:
    """Back the database up, then drop it and its role. Returns the backup file."""
    _, sql = _psycopg()
    name = check_name(name)
    backup = export_database(name, backup_dir() / f"{name}-before-delete-{datetime.now():%Y%m%d-%H%M%S}.sql")
    with connect() as conn:
        conn.execute(sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS false").format(sql.Identifier(name)))
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,))
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))
    return backup


def backup_dir() -> Path:
    path = settings.PANEL_ROOT / "backups" / "postgres"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# browsing + query runner
# ---------------------------------------------------------------------------
def list_tables(name: str) -> list[dict]:
    """Tables with an estimated row count (no COUNT(*) — that would scan big tables)."""
    with connect(check_name(name)) as conn:
        rows = conn.execute("""
            SELECT n.nspname, c.relname, GREATEST(c.reltuples, 0)::bigint, pg_total_relation_size(c.oid)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND n.nspname NOT LIKE 'pg_toast%%'
            ORDER BY n.nspname, c.relname""").fetchall()
    return [{"schema": s, "name": t if s == "public" else f"{s}.{t}", "rows": r, "size": size}
            for s, t, r, size in rows]


def _table_parts(table: str) -> tuple[str, str]:
    schema, _, tbl = table.rpartition(".")
    return schema or "public", tbl


def _table_columns(conn, schema: str, tbl: str, table: str) -> list:
    cols = conn.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position""", (schema, tbl)).fetchall()
    if not cols:
        raise HTTPException(404, f"No table “{table}”.")
    return cols


def _table_select(sql, schema: str, tbl: str, search: str, sort: str | None, desc: bool, col_names: list[str],
                  columns: list[str] | None = None):
    """SELECT cols FROM table [WHERE row ILIKE search] [ORDER BY col] — identifiers validated against the table."""
    if columns:
        unknown = [c for c in columns if c not in col_names]
        if unknown:
            raise HTTPException(400, f"Unknown column(s): {', '.join(unknown)}")
        select = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    else:
        select = sql.SQL("*")
    query = sql.SQL("SELECT {} FROM {}.{} AS t").format(select, sql.Identifier(schema), sql.Identifier(tbl))
    params: list = []
    if search:
        query += sql.SQL(" WHERE t::text ILIKE %s")          # matches text in ANY column
        params.append(f"%{search}%")
    if sort:
        if sort not in col_names:
            raise HTTPException(400, f"Unknown column “{sort}”.")
        query += sql.SQL(" ORDER BY {} {} NULLS LAST").format(sql.Identifier(sort), sql.SQL("DESC" if desc else "ASC"))
    return query, params


def describe_table(name: str, table: str, limit: int = 100, offset: int = 0, search: str = "",
                   sort: str | None = None, desc: bool = False) -> dict:
    """One page of a table's rows (any page, any column order, optional search) + the total count."""
    _, sql = _psycopg()
    psycopg, _ = _psycopg()
    name = check_name(name)
    schema, tbl = _table_parts(table)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    search = (search or "").strip()[:200]
    with connect(name) as conn:
        cols = _table_columns(conn, schema, tbl, table)
        col_names = [c[0] for c in cols]
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(name)))
        conn.execute("SET statement_timeout = '30s'")
        base, params = _table_select(sql, schema, tbl, search, sort, desc, col_names)
        cur = conn.execute(base + sql.SQL(" LIMIT {} OFFSET {}").format(sql.Literal(limit), sql.Literal(offset)), params)
        rows = [[_cell(v) for v in r] for r in cur.fetchall()]
        names = [d.name for d in cur.description]
        # Exact total, but never let a huge table stall the page: 5 s, then the planner's estimate.
        exact = True
        try:
            conn.execute("SET statement_timeout = '5s'")
            count_q = sql.SQL("SELECT count(*) FROM ({}) AS c").format(base)
            total = conn.execute(count_q, params).fetchone()[0]
        except psycopg.errors.QueryCanceled:
            exact = False
            total = conn.execute("SELECT GREATEST(reltuples, 0)::bigint FROM pg_class WHERE oid = %s::regclass",
                                 (f'"{schema}"."{tbl}"',)).fetchone()[0]
    return {"table": table,
            "columns": [{"name": c[0], "type": c[1], "null": c[2], "default": c[3]} for c in cols],
            "preview": {"columns": names, "rows": rows},
            "total": total, "total_exact": exact, "offset": offset, "limit": limit}


def table_csv(name: str, table: str, search: str = "", sort: str | None = None, desc: bool = False,
              columns: list[str] | None = None):
    """Yield the whole table (or the searched part) as CSV, streamed — no file kept on disk."""
    _, sql = _psycopg()
    name = check_name(name)
    schema, tbl = _table_parts(table)
    conn = connect(name)
    try:
        col_names = [c[0] for c in _table_columns(conn, schema, tbl, table)]
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(name)))
        conn.execute("SET statement_timeout = '10min'")
        base, params = _table_select(sql, schema, tbl, (search or "").strip()[:200], sort, desc, col_names, columns)
        with conn.cursor().copy(sql.SQL("COPY ({}) TO STDOUT WITH (FORMAT csv, HEADER true)").format(base), params) as cp:
            yield "\ufeff".encode("utf-8")                     # BOM so Excel reads Urdu/UTF-8 text correctly
            for chunk in cp:
                yield bytes(chunk)
    finally:
        conn.close()


EXCEL_MAX_ROWS = 1_048_575          # per sheet (Excel's limit minus the header row)


def _excel_value(v):
    """What openpyxl/Excel can store: numbers/dates stay real, the rest becomes text."""
    import datetime as dt
    import decimal
    if v is None or isinstance(v, (bool, int, float, str, decimal.Decimal, dt.date)):
        if isinstance(v, dt.datetime) and v.tzinfo is not None:
            return v.replace(tzinfo=None)                    # Excel has no time zones
        if isinstance(v, dt.time) and v.tzinfo is not None:
            return v.replace(tzinfo=None)
        if isinstance(v, str) and v[:1] in "=+-@" and len(v) > 1:
            return "'" + v                                   # never let text become a formula
        return v
    if isinstance(v, dt.time):
        return v
    if isinstance(v, (bytes, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


def _sheet_title(name: str, used: set) -> str:
    title = re.sub(r"[\\/*?:\[\]]", "_", name)[:31] or "sheet"
    base, n = title, 2
    while title.lower() in used:
        suffix = f" ({n})"
        title = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(title.lower())
    return title


def _write_query_to_sheets(wb, conn, query, params, title: str, used: set) -> int:
    """Stream a query into one or more sheets (server-side cursor, 2000 rows at a time)."""
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    bold = Font(bold=True)
    rows_written = 0
    with conn.transaction():
        cur = conn.cursor(name="xlsx_export")
        cur.itersize = 2000
        cur.execute(query, params)
        ws, in_sheet, part = None, 0, 1
        for row in cur:
            if ws is None or in_sheet >= EXCEL_MAX_ROWS:
                ws = wb.create_sheet(_sheet_title(title if part == 1 else f"{title} {part}", used))
                part += 1
                header = []
                for d in cur.description:
                    cell = WriteOnlyCell(ws, value=d.name)
                    cell.font = bold
                    header.append(cell)
                ws.append(header)
                in_sheet = 0
            ws.append([_excel_value(v) for v in row])
            in_sheet += 1
            rows_written += 1
        if ws is None:                                       # empty table: still a sheet with headers
            ws = wb.create_sheet(_sheet_title(title, used))
            ws.append([d.name for d in cur.description or []])
        cur.close()
    return rows_written


def export_excel(name: str, dest: Path, table: str | None = None, search: str = "",
                 sort: str | None = None, desc: bool = False, columns: list[str] | None = None) -> Path:
    """
    One table (optionally only some columns / the searched rows) or the whole
    database (one sheet per table) as .xlsx. Written row by row in openpyxl's
    write-only mode, so memory stays small even for big tables.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(500, "The openpyxl package is missing — run deploy/update.sh to install it.")
    _, sql = _psycopg()
    name = check_name(name)
    wb = Workbook(write_only=True)
    used: set = set()
    with connect(name) as conn:
        if table:
            schema, tbl = _table_parts(table)
            col_names = [c[0] for c in _table_columns(conn, schema, tbl, table)]
            targets = [(table, schema, tbl, col_names)]
        else:
            targets = []
            for t in list_tables(name):
                schema, tbl = _table_parts(t["name"])
                targets.append((t["name"], schema, tbl, None))
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(name)))
        conn.execute("SET statement_timeout = '30min'")
        for label, schema, tbl, col_names in targets:
            if table:
                query, params = _table_select(sql, schema, tbl, (search or "").strip()[:200], sort, desc,
                                              col_names, columns)
            else:
                query, params = sql.SQL("SELECT * FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(tbl)), []
            _write_query_to_sheets(wb, conn, query, params, label, used)
    if not used:
        wb.create_sheet("empty").append(["This database has no tables yet."])
    wb.save(dest)
    return dest


def _cell(v):
    if v is None or isinstance(v, (int, float, bool, str)):
        return v
    return str(v)


def run_query(name: str, query: str) -> dict:
    """Run SQL as the database's own role, with a timeout and a row cap."""
    _, sql = _psycopg()
    name = check_name(name)
    if _ESCAPE_RE.search(query or ""):
        raise HTTPException(400, "Changing the role or session user isn't allowed here.")
    psycopg, _ = _psycopg()
    with connect(name) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(name)))
        conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(QUERY_TIMEOUT)))
        try:
            cur = conn.execute(query)
        except psycopg.Error as exc:
            raise HTTPException(400, str(exc).strip()[:1000])
        if cur.description is None:
            return {"columns": [], "rows": [], "message": f"OK ({cur.rowcount} row(s) affected)"
                    if cur.rowcount >= 0 else "OK"}
        rows = cur.fetchmany(MAX_ROWS + 1)
        more = len(rows) > MAX_ROWS
        return {"columns": [d.name for d in cur.description],
                "rows": [[_cell(v) for v in r] for r in rows[:MAX_ROWS]],
                "message": f"{min(len(rows), MAX_ROWS)} row(s)" + (f" (first {MAX_ROWS} shown)" if more else "")}


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------
def export_database(name: str, dest: Path) -> Path:
    name = check_name(name)
    try:
        r = subprocess.run(["pg_dump", "-h", SOCKET_DIR, "-p", str(server_port()), "-U", "postgres",
                            "--no-owner", "--no-privileges",
                            "-f", str(dest), name], capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise HTTPException(500, "pg_dump isn't installed (install PostgreSQL from this page first).")
    if r.returncode != 0:
        raise HTTPException(500, f"pg_dump failed: {r.stderr.strip()[-500:]}")
    return dest


def import_sql(name: str, path: Path) -> str:
    """Load a plain .sql dump as the database's own role (so it owns what it creates)."""
    name = check_name(name)
    try:
        r = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", SOCKET_DIR,
                            "-p", str(server_port()), "-U", "postgres",
                            "-d", name, "-c", f'SET ROLE "{name}"', "-f", str(path)],
                           capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise HTTPException(500, "psql isn't installed (install PostgreSQL from this page first).")
    if r.returncode != 0:
        raise HTTPException(400, f"Import failed: {r.stderr.strip()[-800:]}")
    return r.stdout.strip()[-300:]

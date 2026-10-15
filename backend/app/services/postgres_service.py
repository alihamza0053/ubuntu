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


def connect(database: str = "postgres"):
    psycopg, _ = _psycopg()
    try:
        return psycopg.connect(host=SOCKET_DIR, user="postgres", dbname=database,
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
          "version": info.get("version"), "helper": code == 0}
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


def describe_table(name: str, table: str, limit: int = 50) -> dict:
    _, sql = _psycopg()
    name = check_name(name)
    schema, _, tbl = table.rpartition(".")
    schema = schema or "public"
    limit = max(1, min(int(limit), 500))
    with connect(name) as conn:
        cols = conn.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position""", (schema, tbl)).fetchall()
        if not cols:
            raise HTTPException(404, f"No table “{table}”.")
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(name)))
        cur = conn.execute(sql.SQL("SELECT * FROM {}.{} LIMIT {}")
                           .format(sql.Identifier(schema), sql.Identifier(tbl), sql.Literal(limit)))
        rows = [[_cell(v) for v in r] for r in cur.fetchall()]
        names = [d.name for d in cur.description]
    return {"table": table, "columns": [{"name": c[0], "type": c[1], "null": c[2], "default": c[3]} for c in cols],
            "preview": {"columns": names, "rows": rows}}


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
        r = subprocess.run(["pg_dump", "-h", SOCKET_DIR, "-U", "postgres", "--no-owner", "--no-privileges",
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
        r = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", SOCKET_DIR, "-U", "postgres",
                            "-d", name, "-c", f'SET ROLE "{name}"', "-f", str(path)],
                           capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise HTTPException(500, "psql isn't installed (install PostgreSQL from this page first).")
    if r.returncode != 0:
        raise HTTPException(400, f"Import failed: {r.stderr.strip()[-800:]}")
    return r.stdout.strip()[-300:]

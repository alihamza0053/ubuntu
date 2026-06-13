"""
MySQL management via the `mysql` / `mysqldump` CLIs.

We shell out to the official clients (argument lists, no shell=True) rather
than adding a Python driver, so the panel works with the system MySQL using
the local root socket auth. Identifiers are strictly validated because they
cannot be parameterized in DDL.
"""
import re
import subprocess
from pathlib import Path

from fastapi import HTTPException

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
MYSQL = ["sudo", "-n", "mysql"]
MYSQLDUMP = ["sudo", "-n", "mysqldump"]


def _ident(name: str) -> str:
    """Validate a database/user identifier (DDL can't be parameterized)."""
    if not IDENT_RE.match(name or ""):
        raise HTTPException(status_code=400,
                            detail="Names may contain only letters, numbers and underscore")
    return name


def _run(cmd: list[str], stdin: str | None = None, timeout: int = 60):
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="mysql client not installed on this host")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="mysql command timed out")


def _exec_sql(sql: str, database: str | None = None) -> str:
    cmd = list(MYSQL)
    if database:
        cmd += [_ident(database)]
    cmd += ["--batch", "-e", sql]
    result = _run(cmd, timeout=120)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "mysql error")
    return result.stdout


def list_databases() -> list[str]:
    out = _exec_sql("SHOW DATABASES;")
    skip = {"Database", "information_schema", "performance_schema", "mysql", "sys"}
    return [line for line in out.splitlines() if line and line not in skip]


def create_database(name: str, user: str | None = None, password: str | None = None) -> None:
    db = _ident(name)
    _exec_sql(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4;")
    if user and password:
        u = _ident(user)
        # password is passed as a quoted string literal; escape single quotes
        pw = password.replace("\\", "\\\\").replace("'", "\\'")
        _exec_sql(
            f"CREATE USER IF NOT EXISTS '{u}'@'localhost' IDENTIFIED BY '{pw}';"
            f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{u}'@'localhost';"
            f"FLUSH PRIVILEGES;"
        )


def drop_database(name: str) -> None:
    _exec_sql(f"DROP DATABASE IF EXISTS `{_ident(name)}`;")


# ---------- Schema browsing ----------

def list_tables(database: str) -> list[dict]:
    """Tables in a database, each with its row count."""
    out = _exec_sql("SHOW TABLES;", database=database)
    lines = out.splitlines()
    names = lines[1:] if len(lines) > 1 else []   # first line is the header
    tables = []
    for t in names:
        if not t:
            continue
        try:
            cnt_out = _exec_sql(f"SELECT COUNT(*) FROM `{_ident(t)}`;", database=database)
            cnt_lines = cnt_out.splitlines()
            rows = int(cnt_lines[1]) if len(cnt_lines) > 1 else 0
        except Exception:
            rows = None
        tables.append({"name": t, "rows": rows})
    return tables


def describe_table(database: str, table: str) -> dict:
    """Column definitions + row count for one table."""
    t = _ident(table)
    out = _exec_sql(f"SHOW FULL COLUMNS FROM `{t}`;", database=database)
    lines = out.splitlines()
    columns = []
    if len(lines) > 1:
        header = lines[0].split("\t")
        idx = {h: i for i, h in enumerate(header)}

        def field(parts, key):
            i = idx.get(key)
            return parts[i] if i is not None and i < len(parts) else ""

        for line in lines[1:]:
            parts = line.split("\t")
            columns.append({
                "name": field(parts, "Field"),
                "type": field(parts, "Type"),
                "null": field(parts, "Null"),
                "key": field(parts, "Key"),
                "default": field(parts, "Default"),
                "extra": field(parts, "Extra"),
                "comment": field(parts, "Comment"),
            })

    cnt = _exec_sql(f"SELECT COUNT(*) FROM `{t}`;", database=database).splitlines()
    try:
        row_count = int(cnt[1]) if len(cnt) > 1 else 0
    except ValueError:
        row_count = 0
    return {"table": table, "columns": columns, "row_count": row_count}


def preview_table(database: str, table: str, limit: int = 50) -> dict:
    """First `limit` rows of a table as columns + rows."""
    t = _ident(table)
    limit = max(1, min(int(limit), 500))
    out = _exec_sql(f"SELECT * FROM `{t}` LIMIT {limit};", database=database)
    lines = out.splitlines()
    columns = lines[0].split("\t") if lines else []
    rows = [line.split("\t") for line in lines[1:]] if len(lines) > 1 else []
    return {"columns": columns, "rows": rows}


def _quote(value) -> str:
    """Escape a value as a SQL string literal (or NULL)."""
    if value is None:
        return "NULL"
    s = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def update_row(database: str, table: str, pk_column: str, pk_value: str,
               changes: dict) -> None:
    """
    UPDATE one row, identified by its primary-key column = value, setting only
    the changed columns. Identifiers are validated; values are escaped.
    """
    t = _ident(table)
    pk = _ident(pk_column)
    if not changes:
        return
    set_parts = [f"`{_ident(col)}` = {_quote(val)}" for col, val in changes.items()]
    sql = (f"UPDATE `{t}` SET {', '.join(set_parts)} "
           f"WHERE `{pk}` = {_quote(pk_value)} LIMIT 1;")
    _exec_sql(sql, database=database)


def delete_row(database: str, table: str, pk_column: str, pk_value: str) -> None:
    """DELETE one row by its primary-key value."""
    t = _ident(table)
    pk = _ident(pk_column)
    _exec_sql(f"DELETE FROM `{t}` WHERE `{pk}` = {_quote(pk_value)} LIMIT 1;",
              database=database)


def run_query(database: str, sql: str) -> dict:
    """Run arbitrary SQL against a database; return columns + rows (tab-parsed)."""
    out = _exec_sql(sql, database=database)
    lines = out.splitlines()
    if not lines:
        return {"columns": [], "rows": [], "message": "OK (no result set)"}
    columns = lines[0].split("\t")
    rows = [line.split("\t") for line in lines[1:]]
    return {"columns": columns, "rows": rows, "message": f"{len(rows)} row(s)"}


def export_database(name: str, dest: Path) -> Path:
    """Dump a database to a .sql file and return its path."""
    db = _ident(name)
    result = _run(MYSQLDUMP + ["--databases", db], timeout=300)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "mysqldump error")
    dest.write_text(result.stdout, encoding="utf-8")
    return dest


def import_sql(name: str, sql_text: str) -> None:
    """Import a .sql dump into a database."""
    db = _ident(name)
    result = _run(MYSQL + [db], stdin=sql_text, timeout=300)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "import error")

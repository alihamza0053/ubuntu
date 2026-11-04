"""
HR API for the Flutter app: one employee's attendance, net salary and expense
claims, from the employee_attendance PostgreSQL database.

Read-only. The employee is taken from the verified login token, NEVER from the
request, so nobody can ask for another person's data by changing an ID.

Host it as a panel project: put this file at dashboard/app.py, install the
packages in requirements.txt, assign a domain and request SSL. PostgreSQL stays
closed to the internet; only this API talks to it.

Calls (all need "Authorization: Bearer <token>"):
  GET /me                                 attendance + salary + claims together
  GET /attendance?date_from=&date_to=     check in / check out per day
  GET /salary                             net salary per pay period
  GET /claims?date_from=&date_to=         expense claim lines
  GET /health                             no token; says only that the API is up
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, timedelta

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ============================ SETTINGS ============================
DB_CONNECTION = ("host=127.0.0.1 port=5433 dbname=employee_attendance "
                 "user=employee_attendance password=PUT_THE_DATABASE_PASSWORD_HERE")

# The key your login signs its tokens with. Until this is set every request is
# refused, so the API can't go live without login protection by mistake.
LOGIN_TOKEN_SECRET = ""
LOGIN_TOKEN_ALGORITHM = "HS256"
EMP_CODE_CLAIM = "emp_code"          # which field of the token holds the employee code

DEFAULT_DAYS = 31                    # attendance/claims window when no dates are given
MAX_DAYS = 400                       # longest range one request may ask for
MAX_ROWS = 500
# ==================================================================

# Read-only at the database level too, with a limit on slow queries.
pool = ConnectionPool(DB_CONNECTION, min_size=1, max_size=8, open=False, timeout=10,
                      kwargs={"row_factory": dict_row, "autocommit": True,
                              "options": "-c default_transaction_read_only=on -c statement_timeout=10000"})


@asynccontextmanager
async def lifespan(_app):
    pool.open()
    yield
    pool.close()


app = FastAPI(title="HR API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def current_employee(authorization: str = Header(default="")) -> str:
    """
    Who is asking. This is the only place that decides it, and the only part to
    change for a different login system (Firebase, Supabase…): return the
    employee code from a VERIFIED token, or refuse.
    """
    if not LOGIN_TOKEN_SECRET:
        raise HTTPException(503, "Login isn't configured yet.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Log in first.", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(token, LOGIN_TOKEN_SECRET, algorithms=[LOGIN_TOKEN_ALGORITHM],
                            options={"require": ["exp"]})
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Log in again.", headers={"WWW-Authenticate": "Bearer"})
    emp_code = str(claims.get(EMP_CODE_CLAIM) or "").strip()
    if not emp_code:
        raise HTTPException(401, "Log in again.", headers={"WWW-Authenticate": "Bearer"})
    return emp_code


def date_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or date.today()
    start = date_from or end - timedelta(days=DEFAULT_DAYS)
    if start > end or (end - start).days > MAX_DAYS:
        raise HTTPException(400, f"Pick a date range of up to {MAX_DAYS} days.")
    return start, end


def rows(sql: str, params: tuple) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def iso(value):
    # ERP columns aren't all real date/time types: some arrive as plain text.
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def number(value):
    return float(value) if value is not None else None


def attendance_for(emp_code: str, start: date, end: date) -> list[dict]:
    found = rows("""SELECT att_date, time_in, time_out FROM erp_attendance
                    WHERE emp_code = %s AND att_date BETWEEN %s AND %s
                    ORDER BY att_date DESC LIMIT %s""", (emp_code, start, end, MAX_ROWS))
    return [{"date": iso(r["att_date"]), "check_in": iso(r["time_in"]), "check_out": iso(r["time_out"])}
            for r in found]


def salary_for(emp_code: str) -> list[dict]:
    found = rows("""SELECT period_start, period_end, net_salary FROM erp_payroll
                    WHERE emp_code = %s ORDER BY period_start DESC LIMIT 36""", (emp_code,))
    return [{"period_start": iso(r["period_start"]), "period_end": iso(r["period_end"]),
             "net_salary": number(r["net_salary"])} for r in found]


def claims_for(emp_code: str, start: date, end: date) -> list[dict]:
    found = rows("""SELECT voucher_no, voucher_date, line_description, amount FROM erp_expense_claims
                    WHERE emp_code = %s AND voucher_date BETWEEN %s AND %s
                    ORDER BY voucher_date DESC LIMIT %s""", (emp_code, start, end, MAX_ROWS))
    return [{"voucher_no": r["voucher_no"], "date": iso(r["voucher_date"]),
             "description": r["line_description"], "amount": number(r["amount"])} for r in found]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(emp_code: str = Depends(current_employee)):
    start, end = date_range(None, None)
    return {"employee_id": emp_code, "attendance": attendance_for(emp_code, start, end),
            "salary": salary_for(emp_code), "claims": claims_for(emp_code, start, end)}


@app.get("/attendance")
def attendance(date_from: date | None = Query(None), date_to: date | None = Query(None),
               emp_code: str = Depends(current_employee)):
    return attendance_for(emp_code, *date_range(date_from, date_to))


@app.get("/salary")
def salary(emp_code: str = Depends(current_employee)):
    return salary_for(emp_code)


@app.get("/claims")
def claims(date_from: date | None = Query(None), date_to: date | None = Query(None),
           emp_code: str = Depends(current_employee)):
    return claims_for(emp_code, *date_range(date_from, date_to))

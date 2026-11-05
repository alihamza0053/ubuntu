"""
HR API for the Flutter app: one employee's attendance, net salary and expense
claims, from the employee_attendance PostgreSQL database.

Read-only. The employee is worked out from the verified Firebase login token,
NEVER from the request, so nobody can ask for another person's data by changing
an ID. No Firebase secret lives here: tokens are checked with Google's public
keys, and the employee code is read from the person's own Firestore profile
using their own token. Employees can't edit that field (see firestore.rules).

Host it as a panel project: put this file at dashboard/app.py, install the
packages in requirements.txt, assign a domain and request SSL. PostgreSQL stays
closed to the internet; only this API talks to it.

Calls (all need "Authorization: Bearer <Firebase ID token>"):
  GET /me                                 attendance + salary + claims together
  GET /attendance?date_from=&date_to=     check in / check out per day
  GET /salary                             net salary per pay period
  GET /claims?date_from=&date_to=         expense claim lines
  GET /health                             no token; 503 if the database or login keys are unavailable
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from datetime import date, timedelta

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ============================ SETTINGS ============================
DB_CONNECTION = ("host=127.0.0.1 port=5433 dbname=employee_attendance "
                 "user=employee_attendance password=PUT_THE_DATABASE_PASSWORD_HERE")

FIREBASE_PROJECT_ID = "mg-apparel-app-yuze"
EMP_CODE_FIELD = "employee_code"     # field of Firestore profiles/{uid}
PROFILE_CACHE_SECONDS = 300          # how long a change to a profile can take to apply

DEFAULT_DAYS = 31                    # attendance/claims window when no dates are given
MAX_DAYS = 400                       # longest range one request may ask for
MAX_ROWS = 500
# ==================================================================

FIREBASE_KEYS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
KEYS_MAX_AGE = 6 * 3600
KEYS_RETRY_SECONDS = 60
KEYS_FIRST_LOAD_RETRY_SECONDS = 5    # sooner while we hold no keys at all
NOT_LINKED = "This account isn't linked to an active employee record."
TRY_AGAIN = "Please try again shortly."
log = logging.getLogger("uvicorn.error")      # ends up in the project's error log

# Read-only at the database level too, with a limit on slow queries.
pool = ConnectionPool(DB_CONNECTION, min_size=1, max_size=8, open=False, timeout=10,
                      kwargs={"row_factory": dict_row, "autocommit": True,
                              "options": "-c default_transaction_read_only=on -c statement_timeout=10000"})


@asynccontextmanager
async def lifespan(_app):
    pool.open()
    refresh_keys()      # so the first employee of the day doesn't pay for this
    yield
    pool.close()


app = FastAPI(title="HR API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def fetch_json(url: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.load(response)


def login_required(message: str = "Log in again.") -> HTTPException:
    return HTTPException(401, message, headers={"WWW-Authenticate": "Bearer"})


# Google's public keys. An unknown key ID only triggers a refresh once a minute,
# so made-up tokens can't turn this API into a flood of requests to Google.
_keys: dict = {}
_keys_loaded = 0.0
_keys_tried = 0.0
_keys_lock = threading.Lock()


def refresh_keys(kid: str | None = None) -> None:
    """Never raises: keys we already hold keep working if Google can't be reached."""
    global _keys, _keys_loaded, _keys_tried
    with _keys_lock:
        now = time.time()
        wanted = not _keys or now - _keys_loaded > KEYS_MAX_AGE or (kid is not None and kid not in _keys)
        wait = KEYS_RETRY_SECONDS if _keys else KEYS_FIRST_LOAD_RETRY_SECONDS
        if not wanted or now - _keys_tried < wait:
            return
        _keys_tried = now
    # Outside the lock: a slow answer from Google must delay this request only.
    try:
        found = jwt.PyJWKSet.from_dict(fetch_json(FIREBASE_KEYS_URL))
    except (OSError, ValueError, jwt.PyJWTError) as error:
        log.warning("Could not load Google's login keys: %r", error)
        return
    _keys_loaded = time.time()
    _keys = {key.key_id: key.key for key in found.keys}


def signing_key(kid: str | None):
    refresh_keys(kid)
    keys = _keys        # one snapshot: another thread may swap in new keys at any moment
    if not keys:
        # We can't check any login right now, which isn't the same as a bad login.
        # A 401 here would make the app sign out people with valid tokens.
        raise HTTPException(503, TRY_AGAIN)
    if kid not in keys:
        raise login_required()
    return keys[kid]


def verified_uid(token: str) -> str:
    """The Firebase user ID from a genuine token for this project, or refuse."""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        claims = jwt.decode(token, signing_key(kid), algorithms=["RS256"], audience=FIREBASE_PROJECT_ID,
                            issuer=f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}",
                            leeway=30, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.InvalidTokenError:
        raise login_required()
    return claims["sub"]


# uid -> (employee code, time it was read)
_profiles: dict[str, tuple[str, float]] = {}


def employee_code_of(uid: str, token: str) -> str:
    cached = _profiles.get(uid)
    if cached and time.time() - cached[1] < PROFILE_CACHE_SECONDS:
        return cached[0]
    url = (f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
           f"/databases/(default)/documents/profiles/{urllib.parse.quote(uid, safe='')}")
    try:
        fields = fetch_json(url, token).get("fields", {})
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 404):
            if error.code != 404:
                log.warning("Firestore refused a profile read: HTTP %s", error.code)
            raise HTTPException(403, NOT_LINKED)
        log.warning("Firestore profile read failed: HTTP %s", error.code)
        raise HTTPException(503, TRY_AGAIN)
    except (OSError, ValueError) as error:
        log.warning("Firestore profile read failed: %r", error)
        raise HTTPException(503, TRY_AGAIN)
    value = fields.get(EMP_CODE_FIELD, {})
    emp_code = str(value.get("stringValue") or value.get("integerValue") or "").strip()
    status = fields.get("status", {}).get("stringValue", "active")
    if not emp_code or status != "active":
        _profiles.pop(uid, None)
        raise HTTPException(403, NOT_LINKED)
    if len(_profiles) > 20000:
        _profiles.clear()
    _profiles[uid] = (emp_code, time.time())
    return emp_code


def current_employee(authorization: str = Header(default="")) -> str:
    """
    Who is asking. This is the only place that decides it: return the employee
    code of a VERIFIED Firebase login, or refuse.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise login_required("Log in first.")
    return employee_code_of(verified_uid(token), token)


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
    refresh_keys()
    try:
        with pool.connection(timeout=3) as conn:
            conn.execute("SELECT 1")
        database = "ok"
    except Exception:
        database = "error"
    login = "ok" if _keys else "error"
    healthy = database == "ok" and login == "ok"
    return JSONResponse({"status": "ok" if healthy else "error", "database": database, "login": login},
                        status_code=200 if healthy else 503)


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

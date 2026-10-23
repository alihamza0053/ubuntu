"""
Operations Dashboard — JSON API for the Company Knowledge chatbot.

Serves the SAME numbers the dashboard shows, by loading the dashboard's own
functions straight out of app.py (its loaders, calculations and colour rules).
app.py is not changed and not copied: edit the dashboard and the API follows.

How: app.py is read up to its "CACHE REFRESH THREAD" section (everything before
it only defines functions) and executed with a stand-in for Streamlit, so no
page is drawn and no Streamlit server is needed. Data is reloaded every
CACHE_REFRESH_SECONDS, exactly like the dashboard's own background thread.

Run:   uvicorn api:app --host 127.0.0.1 --port 8095
Call:  curl -H "X-API-Key: <API_KEY>" "http://127.0.0.1:8095/api/kpis?month=Aug-26&unit=Both"

Endpoints (all need the X-API-Key header, except /health):
  GET /api/months                       month filter options ("All", "Sep-26", …)
  GET /api/kpis?month=&unit=            every KPI for one month/unit + a readable summary
  GET /api/monthly?unit=                one record per month (for the chatbot's index mode)
  GET /api/knowledge                    the values the dashboard shows, one record per KPI and filter (index mode)
  GET /api/report?month=&unit=         the values for one filter (tool mode)
  GET /health                           is data loaded?
"""
from __future__ import annotations

import math
import os
import re
import secrets
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

# ============================ SETTINGS ============================
# The API key the chatbot (or anything else) must send as the X-API-Key header.
API_KEY = os.getenv("OPS_API_KEY", "asdft64tgfdtryu456355tergsd")

# The dashboard file to read. First match wins.
DASHBOARD_APP_CANDIDATES = [
    os.getenv("DASHBOARD_APP", ""),
    str(Path(__file__).resolve().parent / "app.py"),
    "/srv/projects/mga-ops-dashboard/dashboard/app.py",
]
# ==================================================================

UNITS = ["Both", "Unit 1", "Unit 2"]
STATUS_BY_COLOR = {"#1F6437": "good", "#135A11": "good", "#D9B300": "warning",
                   "#D64550": "bad", "#808080": "no_target"}
CUT_MARKERS = ("# ================= CACHE REFRESH THREAD", "start_scheduler()", "# ================= UI")


# ---------------------------------------------------------------------------
# Load the dashboard's functions without running its page
# ---------------------------------------------------------------------------
class _Anything:
    """Stand-in for any Streamlit object: every attribute/call returns itself."""

    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]                      # used as a bare decorator: @st.cache_resource
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


def _fake_streamlit() -> types.ModuleType:
    st = types.ModuleType("streamlit")
    anything = _Anything()

    def cache(func=None, **_kwargs):            # @st.cache_resource and @st.cache_resource(...)
        return func if callable(func) else (lambda f: f)

    st.cache_resource = cache
    st.cache_data = cache
    st.__getattr__ = lambda name: anything      # st.markdown, st.columns, … → no-ops
    return st


def _find_dashboard() -> Path:
    for candidate in DASHBOARD_APP_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("Dashboard app.py not found — set DASHBOARD_APP_CANDIDATES at the top of api.py.")


def load_dashboard() -> dict:
    path = _find_dashboard()
    source = path.read_text(encoding="utf-8")
    cut = min((source.find(m) for m in CUT_MARKERS if m in source), default=-1)
    if cut < 0:
        raise RuntimeError(f"Couldn't find where {path.name}'s page code starts.")
    source = source[:cut]

    real = {name: sys.modules.get(name) for name in ("streamlit", "streamlit_autorefresh")}
    sys.modules["streamlit"] = _fake_streamlit()
    autorefresh = types.ModuleType("streamlit_autorefresh")
    autorefresh.st_autorefresh = lambda *a, **k: None
    sys.modules["streamlit_autorefresh"] = autorefresh
    try:
        namespace = {"__file__": str(path), "__name__": "ops_dashboard"}
        exec(compile(source, str(path), "exec"), namespace)
    finally:
        for name, module in real.items():          # don't leave the stand-in installed
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    for needed in ("refresh_cache", "shared_state", "get_month_options", "calculate_cts"):
        if needed not in namespace:
            raise RuntimeError(f"{path.name} has no `{needed}` — the dashboard changed shape.")
    namespace["__path__"] = str(path)
    return namespace


# A broken load must not take the API down (that shows up as a bare 502 from
# nginx): stay up and return the reason on every request instead.
try:
    D = load_dashboard()
    LOAD_ERROR = None
except Exception:  # noqa: BLE001
    import traceback
    D, LOAD_ERROR = {}, traceback.format_exc(limit=3)
    print(LOAD_ERROR, file=sys.stderr, flush=True)
state = {"loaded_at": None, "loading": False, "error": LOAD_ERROR,
         "refresh_seconds": D.get("CACHE_REFRESH_SECONDS", 300)}
_lock = threading.Lock()


def refresh() -> None:
    with _lock:
        state["loading"] = True
        try:
            D["refresh_cache"]()
            state["loaded_at"], state["error"] = datetime.now(), None
        except Exception as exc:  # noqa: BLE001 — keep the previous data, report the problem
            state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            state["loading"] = False


def _refresher() -> None:
    while True:
        refresh()
        if state["loaded_at"] is not None:
            try:
                rebuild_knowledge()             # only re-reads when a data file changed
                state["knowledge_error"] = None
            except Exception as exc:  # noqa: BLE001
                state["knowledge_error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(state["refresh_seconds"])


if D:
    threading.Thread(target=_refresher, daemon=True, name="ops-api-refresh").start()


# ---------------------------------------------------------------------------
# KPIs — the same steps the dashboard's page runs, returned as data
# ---------------------------------------------------------------------------
def _num(value, digits: int = 2):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def _status(color: str | None) -> str | None:
    return STATUS_BY_COLOR.get((color or "").upper()) if color else None


def _strip_html(text) -> str:
    return re.sub(r"<[^>]+>", "", str(text)).strip()


def compute_kpis(month: str, unit: str) -> dict:
    s = D["shared_state"]
    pd = D["pd"]
    cts_df, oql_df, supply_df = s["cts_df"], s["oql_df"], s["supply_df"]
    f_cts, f_oql, f_supply = cts_df, oql_df, supply_df
    if month != "All":
        period = pd.Period(datetime.strptime(month, "%b-%y"), freq="M")
        if cts_df is not None:
            f_cts = cts_df[cts_df["last_ship_date"].dt.to_period("M") == period]
        if oql_df is not None:
            f_oql = oql_df[oql_df["audit_date"].dt.to_period("M") == period]
        if supply_df is not None:
            f_supply = supply_df[supply_df["dispatch_date"].dt.to_period("M") == period]

    cts = D["calculate_cts"](f_cts)
    fpr = D["calculate_first_pass_ratio"](f_oql)
    dispatch = D["calculate_till_date_dispatch"](f_supply)
    dispatch_target = D["get_dispatch_target"]()
    dispatch_status = "no_target" if dispatch_target is None else ("good" if dispatch >= dispatch_target else "bad")

    b2, leftover, sample = D["calculate_b2_metrics"](s["b2_metrics"], month)
    dhu1, dhu2, dhu_both = s.get("dhu_metrics") or (0, 0, 0)
    earned, plan, percent, variance = D["get_minutes_variance"](month, unit)
    otp, otif = s["otp"] or 0, s["otif"] or 0

    wip_df = D["calculate_wip"](s["wip_df"])
    wip_targets = D["load_wip_targets"]()
    wip = [{"process": r["Process"], "value": _num(r["Value"], 0), "target": _num(wip_targets.get(r["Process"]), 0),
            "status": _status(D["get_wip_color"](r["Value"], wip_targets.get(r["Process"])))}
           for _, r in wip_df.iterrows()] if not wip_df.empty else []

    dept_df = D["get_dept_efficiency"](month, unit)
    targets_df = (s["dept_efficiency"] or {}).get("targets") if s["dept_efficiency"] else None
    dept = [{"department": r["Department"], "efficiency_percent": _num(r["Efficiency"]),
             "status": _status(D["get_target_efficiency_color"](r["Department"], r["Efficiency"], unit, month, targets_df))}
            for _, r in dept_df.iterrows()] if not dept_df.empty else []

    mtd_df = D["get_mtd_backlog"](unit)
    mtd = []
    for _, r in (mtd_df.iterrows() if not mtd_df.empty else []):
        color = re.search(r"color:\s*(#[0-9A-Fa-f]{6})", str(r["Output"]))
        mtd.append({"department": r["Dept"], "backlog": _num(str(r["Backlog"]).replace(",", ""), 0),
                    "output": _num(_strip_html(r["Output"]).replace(",", ""), 0),
                    "output_status": _status(color.group(1)) if color else None})

    kpis = {
        "cts_percent": {"value": _num(cts), "status": _status(D["get_cts_color"](cts))},
        "first_pass_ratio_percent": {"value": _num(fpr), "status": _status(D["get_fpr_color"](fpr))},
        "till_date_dispatch": {"value": _num(dispatch, 0), "target": _num(dispatch_target, 0), "status": dispatch_status},
        "b2_percent": {"b2": _num(b2), "leftover": _num(leftover), "sample": _num(sample)},
        "dhu_percent": {"unit_1": _num(dhu1), "unit_2": _num(dhu2), "both": _num(dhu_both),
                        "status_both": _status(D["get_dhu_color"](dhu_both))},
        "minutes_variance": {"earned": _num(earned, 0), "plan_available": _num(plan, 0), "percent": _num(percent),
                             "variance": _num(variance, 0), "status": _status(D["get_mv_percent_color"](percent))},
        "otp_percent": {"value": _num(otp), "status": _status(D["get_otp_color"](otp))},
        "dispatch_otif_percent": {"value": _num(otif), "status": _status(D["get_otif_color"](otif))},
        "wip": wip,
        "dept_efficiency": dept,
        "mtd_backlog": mtd,
    }
    return {"dashboard": "Operations Dashboard", "month": month, "unit": unit,
            "data_loaded_at": state["loaded_at"].isoformat(timespec="seconds") if state["loaded_at"] else None,
            "kpis": kpis, "summary": summary_text(month, unit, kpis)}


def summary_text(month: str, unit: str, k: dict) -> str:
    """One readable paragraph — what the chatbot indexes or quotes."""
    fmt = D.get("format_number", lambda v: str(v))
    period = "all months" if month == "All" else month
    parts = [f"Operations Dashboard, {period}, {unit}:",
             f"CTS {k['cts_percent']['value']}% ({k['cts_percent']['status']}),",
             f"First Pass Ratio {k['first_pass_ratio_percent']['value']}%,",
             f"Till Date Dispatch {fmt(k['till_date_dispatch']['value'] or 0)} vs target {fmt(k['till_date_dispatch']['target'] or 0)},",
             f"B2 {k['b2_percent']['b2']}% / Leftover {k['b2_percent']['leftover']}% / Sample {k['b2_percent']['sample']}%,",
             f"DHU Unit 1 {k['dhu_percent']['unit_1']}%, Unit 2 {k['dhu_percent']['unit_2']}%, both {k['dhu_percent']['both']}%,",
             f"Minutes earned {fmt(k['minutes_variance']['earned'] or 0)} of {fmt(k['minutes_variance']['plan_available'] or 0)} "
             f"planned ({k['minutes_variance']['percent']}%), variance {fmt(k['minutes_variance']['variance'] or 0)},",
             f"OTP {k['otp_percent']['value']}%, Dispatch OTIF {k['dispatch_otif_percent']['value']}%."]
    if k["wip"]:
        parts.append("WIP: " + ", ".join(f"{w['process']} {fmt(w['value'] or 0)}" for w in k["wip"]) + ".")
    if k["dept_efficiency"]:
        parts.append("Efficiency: " + ", ".join(f"{d['department'].title()} {d['efficiency_percent']}%"
                                                for d in k["dept_efficiency"]) + ".")
    if k["mtd_backlog"]:
        parts.append("MTD backlog: " + ", ".join(f"{m['department']} backlog {fmt(m['backlog'] or 0)}, output {fmt(m['output'] or 0)}"
                                                 for m in k["mtd_backlog"]) + ".")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Chatbot records — the values the dashboard shows right now, nothing else
# ---------------------------------------------------------------------------
# One short record per KPI and filter, written the way the page shows it
# (counts as K/M/B, percentages as on the cards). No targets, no formulas.
# Rebuilt whenever a data file changes, so it always matches the live page.
#   /api/knowledge  → chatbot data source in INDEX mode (records: records, id: id, template: {text})
#   /api/report     → chatbot data source in TOOL mode (month + unit → that view's values)
knowledge = {"records": None, "built_at": None, "signature": None}
FACTORY = "(factory-wide: the same for Unit 1, Unit 2 and Both)"


def _blank(v) -> bool:
    if v is None:
        return True
    try:
        return bool(D["pd"].isna(v))
    except (TypeError, ValueError):
        return False


def _n(v) -> str:
    """A count the way the dashboard writes it: 89.02M, 28.02K."""
    if _blank(v):
        return "-"
    try:
        return D["format_number"](float(v))
    except (TypeError, ValueError):
        return str(v)


def _p(v, digits: int = 2) -> str:
    return "-" if _blank(v) else f"{float(v):.{digits}f}%"


def _when(month: str) -> str:
    """How a month filter is said: the default view is the 'current' dashboard."""
    if month == "All":
        return "current dashboard view (live, latest, overall, all months, no month filter)"
    full = datetime.strptime(month, "%b-%y")
    return f"{month} / {full:%B %Y} ({full:%b %Y})"


def kpi_lines(month: str, unit: str) -> list[tuple[str, str, str]]:
    """(record id, KPI, sentence) for every value the page shows with these filters."""
    k = compute_kpis(month, unit)["kpis"]
    when, m, u = _when(month), month.replace(" ", ""), unit.replace(" ", "")
    out = []
    mv = k["minutes_variance"]
    out.append((f"minutes-{m}-{u}", "Minutes & Variance",
                f"{when}, {unit}: Earned {_n(mv['earned'])}, Earned % {_p(mv['percent'], 0)}, "
                f"Plan Available {_n(mv['plan_available'])}, Variance {_n(mv['variance'])}."))
    if k["dept_efficiency"]:
        out.append((f"eff-{m}-{u}", "Dept Wise Efficiency", f"{when}, {unit}: " + ", ".join(
            f"{e['department'].title()} {_p(e['efficiency_percent'])}" for e in k["dept_efficiency"]) + "."))
    if unit == "Both":                                  # the unit filter doesn't change these
        out.append((f"dispatch-{m}", "Till Date Dispatch", f"{when}: {_n(k['till_date_dispatch']['value'])} {FACTORY}."))
        out.append((f"cts-{m}", "CTS %", f"{when}: {_p(k['cts_percent']['value'])} {FACTORY}."))
        b = k["b2_percent"]
        out.append((f"b2-{m}", "B2 % (B2, Leftover, Sample)",
                    f"{when}: B2 {_p(b['b2'])}, Leftover {_p(b['leftover'])}, Sample {_p(b['sample'])} {FACTORY}."))
        out.append((f"fpr-{m}", "First Pass Ratio", f"{when}: {_p(k['first_pass_ratio_percent']['value'])} {FACTORY}."))
    if month == "All":                                  # the month filter doesn't change these
        if k["mtd_backlog"]:
            out.append((f"mtd-{u}", "MTD Backlog", f"current (month to date), {unit}: " + "; ".join(
                f"{x['department']} backlog {_n(x['backlog'])}, output {_n(x['output'])}" for x in k["mtd_backlog"]) + "."))
        if unit == "Both":
            h = k["dhu_percent"]
            out.append(("dhu", "DHU", f"current (any month filter): Unit 1 {_p(h['unit_1'])}, "
                                      f"Unit 2 {_p(h['unit_2'])}, Both {_p(h['both'])}."))
            out.append(("otp-otif", "OTP and Dispatch OTIF",
                        f"current (any month or unit filter): OTP {_p(k['otp_percent']['value'])}, "
                        f"Dispatch OTIF {_p(k['dispatch_otif_percent']['value'])}."))
            if k["wip"]:
                out.append(("wip", "WIP (work in progress)", "current (any month or unit filter): " + ", ".join(
                    f"{w['process']} {_n(w['value'])}" for w in k["wip"]) + "."))
    return out


def dashboard_values(month: str, unit: str) -> str:
    """Everything the page shows for one month/unit filter, one line per KPI."""
    k = compute_kpis(month, unit)["kpis"]
    when = _when(month)
    lines = [f"Operations Dashboard — {when}, {unit}:"]
    if k["mtd_backlog"]:
        lines.append("MTD Backlog: " + "; ".join(f"{x['department']} backlog {_n(x['backlog'])}, output {_n(x['output'])}"
                                                 for x in k["mtd_backlog"]) + ".")
    mv = k["minutes_variance"]
    lines.append(f"Minutes & Variance: Earned {_n(mv['earned'])}, Earned % {_p(mv['percent'], 0)}, "
                 f"Plan Available {_n(mv['plan_available'])}, Variance {_n(mv['variance'])}.")
    if k["dept_efficiency"]:
        lines.append("Dept Wise Efficiency: " + ", ".join(f"{e['department'].title()} {_p(e['efficiency_percent'])}"
                                                          for e in k["dept_efficiency"]) + ".")
    lines.append(f"Till Date Dispatch: {_n(k['till_date_dispatch']['value'])}.")
    lines.append(f"CTS %: {_p(k['cts_percent']['value'])}.")
    b = k["b2_percent"]
    lines.append(f"B2 %: B2 {_p(b['b2'])}, Leftover {_p(b['leftover'])}, Sample {_p(b['sample'])}.")
    h = k["dhu_percent"]
    lines.append(f"DHU: Unit 1 {_p(h['unit_1'])}, Unit 2 {_p(h['unit_2'])}, Both {_p(h['both'])}.")
    lines.append(f"OTP: {_p(k['otp_percent']['value'])}. Dispatch OTIF: {_p(k['dispatch_otif_percent']['value'])}.")
    if k["wip"]:
        lines.append("WIP: " + ", ".join(f"{w['process']} {_n(w['value'])}" for w in k["wip"]) + ".")
    lines.append(f"First Pass Ratio: {_p(k['first_pass_ratio_percent']['value'])}.")
    return "\n".join(lines)


def _files_signature():
    paths = [D.get(k) for k in ("CTS_FILE", "OQL_FILE", "SUPPLY_FILE", "TNA_FILE", "MANUAL_FILE", "DPS_FILE",
                                "CHECKED_PCS_1", "CHECKED_PCS_2", "TOTAL_FAULTS_1", "TOTAL_FAULTS_2")]
    paths.append(D["get_cut_to_pack_file"]())
    sig = []
    for p in paths:
        try:
            sig.append((p, os.path.getmtime(p)))
        except (OSError, TypeError):
            sig.append((p, None))
    return tuple(sig)


def rebuild_knowledge(force: bool = False) -> None:
    sig = _files_signature()
    if not force and knowledge["records"] is not None and sig == knowledge["signature"]:
        return
    records = []
    for month in D["get_month_options"]():
        for unit in UNITS:
            for rid, kpi, text in kpi_lines(month, unit):
                records.append({"id": rid, "kpi": kpi, "month": month, "unit": unit,
                                "text": f"{kpi} — Operations Dashboard — {text}"})
    knowledge.update(records=records, built_at=datetime.now(), signature=sig)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
app = FastAPI(title="Operations Dashboard API", docs_url=None, redoc_url=None, openapi_url=None)


def require_key(request: Request) -> None:
    if not API_KEY or API_KEY.startswith("change-me"):
        raise HTTPException(503, "Set API_KEY at the top of api.py first.")
    sent = request.headers.get("x-api-key") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        sent = sent or auth[7:]
    if not secrets.compare_digest(sent.encode(), API_KEY.encode()):
        raise HTTPException(401, "Missing or wrong API key (send it as the X-API-Key header).")


def require_data() -> None:
    if state["loaded_at"] is None:
        raise HTTPException(503, "Data is still loading — try again in a moment."
                                 + (f" Last error: {state['error']}" if state["error"] else ""))


def _check(month: str, unit: str) -> tuple[str, str]:
    options = D["get_month_options"]()
    month = month.strip() or "All"
    match = next((m for m in options if m.lower() == month.lower()), None)
    if match is None:
        raise HTTPException(400, f"Unknown month “{month}”. Available: {', '.join(options)}")
    unit_match = next((u for u in UNITS if u.lower() == unit.strip().lower()), None)
    if unit_match is None:
        raise HTTPException(400, f"Unit must be one of: {', '.join(UNITS)}")
    return match, unit_match


@app.get("/health")
@app.get("/api/health")
def health():
    ok = state["loaded_at"] is not None
    status = "ok" if ok else ("error" if LOAD_ERROR else "loading")
    return JSONResponse({"status": status, "dashboard": D.get("__path__"),
                         "data_loaded_at": state["loaded_at"].isoformat(timespec="seconds") if ok else None,
                         "error": state["error"]}, status_code=200 if ok else 503)


@app.get("/api/months", dependencies=[Depends(require_key), Depends(require_data)])
def months():
    return {"months": D["get_month_options"](), "units": UNITS}


@app.get("/api/kpis", dependencies=[Depends(require_key), Depends(require_data)])
def kpis(month: str = Query("All", description="e.g. Aug-26, or All"),
         unit: str = Query("Both", description="Both, Unit 1 or Unit 2")):
    month, unit = _check(month, unit)
    return compute_kpis(month, unit)


@app.get("/api/knowledge", dependencies=[Depends(require_key), Depends(require_data)])
def knowledge_records():
    """The values the dashboard shows, one record per KPI and filter — sync into the chatbot (index mode)."""
    if knowledge["records"] is None:
        raise HTTPException(503, "The records are still being built — try again in a minute."
                                 + (f" Last error: {state.get('knowledge_error')}" if state.get("knowledge_error") else ""))
    return {"dashboard": "Operations Dashboard", "built_at": knowledge["built_at"].isoformat(timespec="seconds"),
            "count": len(knowledge["records"]), "records": knowledge["records"]}


@app.get("/api/report", dependencies=[Depends(require_key), Depends(require_data)])
def report(month: str = Query("All", description="e.g. Sep-26, or All (= the current dashboard view)"),
           unit: str = Query("Both", description="Both, Unit 1 or Unit 2")):
    """The values the dashboard shows for one month/unit filter (chatbot TOOL mode)."""
    month, unit = _check(month, unit)
    return {"month": month, "unit": unit, "values": dashboard_values(month, unit),
            "available_months": D["get_month_options"]()}


@app.get("/api/monthly", dependencies=[Depends(require_key), Depends(require_data)])
def monthly(unit: str = Query("Both")):
    """One record per month — sync this into the chatbot (index mode, id field: id)."""
    _, unit = _check("All", unit)
    records = []
    for month in D["get_month_options"]():
        data = compute_kpis(month, unit)
        records.append({"id": f"{month}|{unit}", "month": month, "unit": unit,
                        "data_loaded_at": data["data_loaded_at"], "summary": data["summary"], "kpis": data["kpis"]})
    return {"records": records}

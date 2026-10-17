import streamlit as st
import pandas as pd
import os
import time
import threading
import subprocess
import calendar
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import warnings
import plotly.express as px
import plotly.graph_objects as go
from openpyxl import load_workbook
import logging
logging.getLogger("streamlit").setLevel(logging.ERROR)
logging.getLogger("watchdog").setLevel(logging.ERROR)
import streamlit as st2

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode, DataReturnMode
    _AGGRID_AVAILABLE = True
except ImportError:
    _AGGRID_AVAILABLE = False

warnings.filterwarnings("ignore")

# ================= CONFIG =================
# All Excel files live in the project's data/ folder on the server.
#   - The 4 "report" files are produced by the download scripts in code/
#     (run them from the panel Scheduler tab).
#   - The rest are uploaded manually via the project's Data Files tab.
# Override the base location with the DATA_DIR env var if needed.
DATA_DIR = os.getenv("DATA_DIR", "/srv/projects/mga-ops-dashboard/data")

# --- Produced by the download scripts ---
CTS_FILE = os.path.join(DATA_DIR, "MG_Apparel_Order_Closing_Report.xls")
OQL_FILE = os.path.join(DATA_DIR, "OQL Audit Report.xlsx")
SUPPLY_FILE = os.path.join(DATA_DIR, "Supply Register Report_V10.xlsx")
# cut-to-pack.py saves MG_Cut_to_Pack_Report.xlsx/.xls into data/
CUT_TO_PACK_FOLDER = DATA_DIR


DATA_DIR2 = os.getenv("DATA_DIR", "/srv/projects/mga-ops-dashboard/data/onedrivefiles")

# --- Uploaded manually via the Data Files tab (formerly OneDrive) ---
TNA_FILE = os.path.join(DATA_DIR2, "TNA 2.xlsx")

CHECKED_PCS_1 = os.path.join(DATA_DIR2, "Checked Pieces.xlsx")
CHECKED_PCS_2 = os.path.join(DATA_DIR2, "Checked Pieces 2.xlsx")
TOTAL_FAULTS_1 = os.path.join(DATA_DIR2, "Total Faults.xlsx")
TOTAL_FAULTS_2 = os.path.join(DATA_DIR2, "Total Faults 2.xlsx")

MANUAL_FILE = os.path.join(DATA_DIR2, "Mannual Sheet.xlsx")
EFF_REPORT_FILE = os.path.join(DATA_DIR, "Eff report Sys.xlsx")
DPS_FILE = os.path.join(DATA_DIR2, "DPS.xlsx")
# Source workbook for the "DPS Dashboard" drill-down button on the MTD Backlog KPI.
DPS_DASHBOARD_FILE = os.path.join(DATA_DIR2, "DPS Dashboard.xlsx")
WIP_TARGET_FILE = os.path.join(DATA_DIR2, "targets ops.xlsx")
WIP_AGING_FILE = "/srv/projects/mga-ceo-dashboard/onedrivefiles/Cut to pack wip.xlsx"

REFRESH_INTERVAL_SECONDS = 15      # how often the Streamlit UI auto-reruns
CACHE_REFRESH_SECONDS = 300        # how often the dashboard re-reads data/ files

# ================= SHARED STATE =================
@st.cache_resource
def get_shared_state():
    return {
        "cts_df": None,
        "oql_df": None,
        "supply_df": None,
        "wip_df": None,
        "otp": None,
        "otif": None,
        "b2_metrics": None,
        "dhu_metrics": None,
        "dept_efficiency": None,
        "mtd_backlog": None,
        "minutes_variance": None,
    }

shared_state = get_shared_state()

# ================= HELPERS =================
def _is_file_stable(path, checks=2, interval=0.15):
    """
    True if the file's size/mtime don't change across a couple of quick
    checks — i.e. nothing is actively writing to it right now.

    Download/upload scripts (see the Scheduler tab) write these Excel files
    in place. If a loader reads mid-write, pandas/openpyxl can succeed but
    return partial/blank data (this is what caused Till Date Dispatch, and
    potentially other KPIs, to briefly show 0 while a script was RUNNING).
    Gating file_exists() on stability means every load_*() function below
    automatically falls through to its `return shared_state[...]` fallback
    during a write, and only picks up the new file once it's finished.
    """
    try:
        prev = os.stat(path)
    except OSError:
        return False

    for _ in range(checks):
        time.sleep(interval)
        try:
            cur = os.stat(path)
        except OSError:
            return False
        if cur.st_mtime != prev.st_mtime or cur.st_size != prev.st_size:
            return False
        prev = cur

    return True


def file_exists(path):
    if not os.path.exists(path):
        return False
    return _is_file_stable(path)


def get_cut_to_pack_file():
    xlsx = os.path.join(CUT_TO_PACK_FOLDER, "MG_Cut_to_Pack_Report.xlsx")
    xls = os.path.join(CUT_TO_PACK_FOLDER, "MG_Cut_to_Pack_Report.xls")

    if os.path.exists(xlsx) and _is_file_stable(xlsx):
        return xlsx
    elif os.path.exists(xls) and _is_file_stable(xls):
        return xls
    return None


def format_number(value):
    if value is None:
        return "0"

    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:.2f}K"
    else:
        return f"{value:,.0f}"

def get_cts_color(value):
    if value >= 97.5:
        return "#1F6437"   # Green
    elif value >= 96:
        return "#D9B300"   # Yellow
    else:
        return "#D64550"   # Red

def get_fpr_color(value):
    if value > 99:
        return "#1F6437"
    else:
        return "#D64550"

def get_dhu_color(value):
    if value is None:
        return "#1F6437"
    if value < 7.0:
        return "#1F6437"   # Green
    elif value < 8.0:
        return "#D9B300"   # Yellow
    else:
        return "#D64550"   # Red

def get_otp_color(value):
    if value is None:
        return "#D64550"
    if value > 99:
        return "#1F6437"
    else:
        return "#D64550"

def get_otif_color(value):
    if value is None:
        return "#D64550"
    if value > 85:
        return "#1F6437"
    else:
        return "#D64550"

def get_mv_percent_color(value):
    if value is None:
        return "#D64550"
    if value >= 100:
        return "#1F6437"
    elif value >= 95:
        return "#D9B300"
    else:
        return "#D64550"

def get_variance_color(value):
    if value is None:
        return "#D64550"
    if value >= 0:
        return "#1F6437"
    else:
        return "#D64550"

def get_wip_color(actual, target):
    if pd.isna(target):
        return "#808080"

    if actual > target:
        return "#D64550"
    else:
        return "#1F6437"

def get_target_efficiency_color(dept, actual, selected_unit, selected_month, targets_df):
    if targets_df is None or targets_df.empty:
        fallback = {
            "CUTTING": "#D64550",
            "STITCHING": "#00B050",
            "WASHING": "#D9B300",
            "FINISHING": "#D64550"
        }
        return fallback.get(dept.upper(), "#808080")

    dept_upper = dept.upper()
    if selected_unit == "Both":
        mapping = {
            "CUTTING": "Cutting",
            "STITCHING": "Total Stitching",
            "WASHING": "Washing Total",
            "FINISHING": "Finishing Total"
        }
    else:
        mapping = {
            "CUTTING": "Cutting",
            "STITCHING": "Stitching",
            "WASHING": "Washing",
            "FINISHING": "Finishing"
        }
    
    target_dept_name = mapping.get(dept_upper, dept)

    target_col = "Value"
    if selected_month and selected_month != "All":
        try:
            sel_dt = datetime.strptime(selected_month, "%b-%y")
            for col in targets_df.columns:
                if isinstance(col, datetime) or hasattr(col, "year"):
                    if col.year == sel_dt.year and col.month == sel_dt.month:
                        target_col = col
                        break
                elif isinstance(col, str):
                    col_clean = col.strip().lower()
                    month_name_full = sel_dt.strftime("%B").lower()
                    month_name_abbr = sel_dt.strftime("%b").lower()
                    if col_clean == month_name_full or col_clean == month_name_abbr or col_clean in month_name_full:
                        target_col = col
                        break
        except:
            target_col = "Value"

    try:
        row = targets_df[
            (targets_df['Dept'].astype(str).str.strip() == target_dept_name) & 
            (targets_df['Unit'].astype(str).str.strip() == selected_unit)
        ]
        if row.empty:
            return "#808080"
        
        target_val = float(row.iloc[0][target_col])
        if pd.isna(target_val) or target_val == 0:
            return "#808080"
            
        tolerance = target_val * 0.98
        
        if actual >= target_val:
            return "#00B050"   # Green
        elif actual >= tolerance:
            return "#D9B300"   # Yellow
        else:
            return "#D64550"   # Red
    except Exception as e:
        return "#808080"

def get_dispatch_target():
    return 685152
        
def load_wip_targets():
    return {
        "Cutting": 60000,
        "Stitching": 210000,
        "Washing": 120000,
        "Finishing": 150000,
        "Packing": 90000,
        "RFD": 150000
    }

# ================= CTS =================
def load_cts_data():
    if not file_exists(CTS_FILE):
        return shared_state["cts_df"]

    try:
        df = pd.read_excel(CTS_FILE, header=6)

        df = df[[
            "Till Date Cutting",
            "Till Date Dispatch Qty",
            "Last Shipment Date",
            "BAL To Ship"
        ]].copy()

        df.columns = [
            "cut_qty",
            "dispatch_qty",
            "last_ship_date",
            "bal_to_ship"
        ]

        df["cut_qty"] = pd.to_numeric(df["cut_qty"], errors="coerce").fillna(0)
        df["dispatch_qty"] = pd.to_numeric(df["dispatch_qty"], errors="coerce").fillna(0)
        df["bal_to_ship"] = pd.to_numeric(df["bal_to_ship"], errors="coerce").fillna(0)
        df["last_ship_date"] = pd.to_datetime(df["last_ship_date"], errors="coerce")

        df = df[df["cut_qty"] > 0]
        return df
    except:
        return shared_state["cts_df"]


def calculate_cts(df):
    if df is None or df.empty:
        return 0.0

    total_cut = df["cut_qty"].sum()
    total_dispatch = df["dispatch_qty"].sum()
    total_balance = df["bal_to_ship"].sum()

    if total_cut == 0:
        return 0.0

    return ((total_dispatch + total_balance) / total_cut) * 100


# ================= OQL =================
def load_oql_data():
    if not file_exists(OQL_FILE):
        return shared_state["oql_df"]

    try:
        df = pd.read_excel(OQL_FILE)
        df = df.iloc[:, [2, 14, 15]].copy()

        df.columns = [
            "audit_date",
            "oql_status",
            "audit_status"
        ]

        df["audit_date"] = pd.to_datetime(df["audit_date"], errors="coerce")
        return df
    except:
        return shared_state["oql_df"]


def calculate_first_pass_ratio(df):
    if df is None or df.empty:
        return 0.0

    first_time = df[
        df["audit_status"].astype(str).str.strip().str.lower() == "1st time"
    ]

    if first_time.empty:
        return 0.0

    pass_count = first_time[
        first_time["oql_status"].astype(str).str.strip().str.upper() == "PASS"
    ]

    return (len(pass_count) / len(first_time)) * 100


# ================= SUPPLY =================
def load_supply_data():
    if not file_exists(SUPPLY_FILE):
        return shared_state["supply_df"]

    try:
        df = pd.read_excel(SUPPLY_FILE)

        df = df.iloc[:, [0, 2, 11, 16, 42, 47]].copy()

        df.columns = [
            "dispatch_date",
            "order_no",
            "description",
            "qty_units",
            "party_name",
            "sale_type"
        ]

        # Column A (Date) and column AQ (Party) are merged cells in the source
        # sheet — Excel only stores the value in the first row of the merge and
        # leaves the rest blank, so forward-fill to "unmerge" them.
        df["dispatch_date"] = df["dispatch_date"].ffill()
        df["party_name"] = df["party_name"].ffill()
        df["dispatch_date"] = pd.to_datetime(df["dispatch_date"], errors="coerce")
        df["qty_units"] = pd.to_numeric(df["qty_units"], errors="coerce").fillna(0)

        # Short display name = first word of the full party/company name
        # e.g. "BESTSELLER Bestseller A/S Fredskovvej 1 7330 Brande DK" -> "BESTSELLER"
        df["party_short"] = df["party_name"].astype(str).str.strip().str.split().str[0]

        mask_exp = (
            df["sale_type"].astype(str).str.strip() == "Exp Sale/App1"
        )
        mask_loc_stylers = (
            (df["sale_type"].astype(str).str.strip().str.contains("Loc Sale/App1", na=False)) &
            (df["party_name"].astype(str).str.strip().str.contains(
                "Stylers International", na=False  # ← simplified, removes "(Private) Limited" mismatch risk
            ))
        )
        mask_loc_taiga = (
            (df["sale_type"].astype(str).str.strip().str.contains("Loc Sale/App1", na=False)) &
            (df["party_name"].astype(str).str.strip().str.contains(
                "TAIGA APPAREL", na=False
            ))
        )
        # Rantex is only counted through Jul-26; from Aug-26 onwards their
        # dispatches should no longer be included in Till Date Dispatch.
        mask_loc_rantex = (
            (df["sale_type"].astype(str).str.strip().str.contains("Loc Sale/App1", na=False)) &
            (df["party_name"].astype(str).str.strip().str.contains(
                "Rantex", na=False
            )) &
            (df["dispatch_date"] < pd.Timestamp("2026-08-01"))
        )
        mask_loc = mask_loc_stylers | mask_loc_taiga | mask_loc_rantex

        df = df[
            df["description"].notna() &
            (df["description"].astype(str).str.strip() != "") &
            (mask_exp | mask_loc)
        ]

        # Guard against reading the file mid-write: the download script may
        # briefly leave it truncated/blank (still a valid Excel file, just
        # with no rows) while it's being overwritten. A real refresh should
        # never wipe out all rows, so treat an empty result as a failed
        # read and keep whatever is already cached instead of blanking the
        # KPI to 0.
        #
        # NOTE: file_exists() now also verifies size/mtime stability before
        # a load_*() ever gets this far, so this empty-df guard should
        # rarely (if ever) trigger anymore — it's kept as a second line of
        # defense in case a write completes between the two stability
        # checks with a momentarily-empty intermediate save.
        if df.empty and shared_state["supply_df"] is not None and not shared_state["supply_df"].empty:
            return shared_state["supply_df"]

        return df

    except Exception as e:
        return shared_state["supply_df"]


def calculate_till_date_dispatch(df):
    if df is None or df.empty:
        return 0.0

    valid_rows = df[
        df["description"].astype(str).str.strip() != ""
    ]

    return valid_rows["qty_units"].sum()


# ================= WIP =================
def load_wip_data():
    file_path = get_cut_to_pack_file()

    if not file_path:
        return shared_state["wip_df"]

    try:
        df = pd.read_excel(file_path)

        df = df.iloc[:, [9, 20, 37, 40, 55, 90, 96, 73, 58, 101, 118, 5]].copy()

        df.columns = [
            "book_x_factory",
            "cutting",
            "stitching",
            "rigid_area",
            "washing_balance",
            "packing",
            "wh_rfi",
            "finishing",
            "ready_fin",
            "rfd",
            "status",
            "tracking_number"
        ]

        df["book_x_factory"] = pd.to_datetime(
            df["book_x_factory"],
            format="%d-%m-%Y",
            errors="coerce"
        )

        df = df[df["book_x_factory"] >= pd.Timestamp("2025-07-01")]

        df = df[
            df["status"].astype(str).str.strip().str.lower() != "dispatch"
        ]

        numeric_cols = [
            "cutting",
            "stitching",
            "rigid_area",
            "washing_balance",
            "packing",
            "wh_rfi",
            "finishing",
            "ready_fin",
            "rfd"
        ]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        return df
    except:
        return shared_state["wip_df"]


def calculate_wip(df):
    if df is None or df.empty:
        return pd.DataFrame()

    data = {
        "Process": [
            "Cutting",
            "Stitching",
            "Washing",
            "Finishing",
            "Packing",
            "RFD"
        ],
        "Value": [
            df["cutting"].sum(),
            df["stitching"].sum(),
            df["rigid_area"].sum() + df["washing_balance"].sum(),
            df["finishing"].sum() + df["ready_fin"].sum(),
            df["packing"].sum() + df["wh_rfi"].sum(),
            df["rfd"].sum()
        ]
    }

    return pd.DataFrame(data)

def load_wip_aging_data():
    """
    WIP Aging breakdown shown on the WIP KPI drill-down, sourced from a
    separate file (mga-ceo-dashboard project, not the ops dashboard's own
    data/). Row 1 = headers, rows 2-9 = data including the 'Total Wip' row.
    """
    if not file_exists(WIP_AGING_FILE):
        return None

    try:
        df = pd.read_excel(
            WIP_AGING_FILE,
            sheet_name="Sheet1",
            header=0,
            nrows=8,
            engine="openpyxl"
        )
        df = df.iloc[:, :8].copy()

        expected_cols = [
            "WIP Aging", "Cutting WIP", "Sewing WIP", "Washing WIP",
            "Finishing WIP", "RFI", "RFD WIP", "RFE"
        ]
        df.columns = expected_cols[:len(df.columns)]

        return df
    except Exception as e:
        logging.getLogger("wip_aging").exception("WIP Aging load error: %s", e)
        return None


def _fmt_wip_aging_cell(v):
    """Mirrors the source sheet's number format: 0/blank -> '-',
    negatives -> '(1,234)', everything else -> '1,234'."""
    if pd.isna(v):
        return "-"
    try:
        num = float(v)
    except (ValueError, TypeError):
        return str(v)
    if num == 0:
        return "-"
    if num < 0:
        return f"({abs(num):,.0f})"
    return f"{num:,.0f}"


def _fmt_generic(v):
    """Blank-safe display formatter: blank cells stay blank, numbers get
    thousands separators, everything else is shown as-is (used for the
    DPS Dashboard tables)."""
    if v is None or (isinstance(v, str) and v.strip() == "") or pd.isna(v):
        return ""
    if isinstance(v, (int, float)):
        try:
            if float(v).is_integer():
                return f"{v:,.0f}"
            return f"{v:,.2f}"
        except (ValueError, TypeError):
            return str(v)
    return str(v).strip()


def _fmt_signed_paren(v):
    """Number formatter for the Deviation/Diff columns: blank -> blank,
    negatives shown in parentheses (colored red via _style_pos_neg),
    positives shown plain (colored green via _style_pos_neg)."""
    if v is None or (isinstance(v, str) and v.strip() == "") or pd.isna(v):
        return ""
    try:
        num = float(v)
    except (ValueError, TypeError):
        return str(v)
    if num < 0:
        return f"({abs(num):,.0f})" if float(num).is_integer() else f"({abs(num):,.2f})"
    return f"{num:,.0f}" if float(num).is_integer() else f"{num:,.2f}"


# ================= OTP / OTIF =================
def load_tna_data():
    if not file_exists(TNA_FILE):
        return shared_state["otp"], shared_state["otif"]

    def normalize_pct(value):
        """
        Dynamically handle percentage values:
        - If value > 1 and <= 100: already a percentage (e.g. 83 → 83%)
        - If value <= 1: decimal percentage (e.g. 0.83 → 83%)
        - If value > 100: wrong column picked up (e.g. 284719 → invalid)
        """
        if value is None or pd.isna(value):
            return 0
        value = float(value)
        if value <= 1:
            return value * 100        # decimal → percentage
        elif value <= 100:
            return value              # already a percentage
        else:
            return 0                  # clearly not a percentage (e.g. qty)

    try:
        df = pd.read_excel(
            TNA_FILE,
            sheet_name="Dispatch OTIF"
        )

        row = df[
            df.iloc[:, 1].astype(str).str.strip() == "Grand Total"
        ]

        if row.empty:
            return shared_state["otp"], shared_state["otif"]

        # Try columns 4 & 5 first; if OTP looks wrong, scan for correct columns
        otp_raw  = row.iloc[0, 5]
        otif_raw = row.iloc[0, 6]

        # If col 4 gives an unreasonable value, scan all columns for OTP/OTIF headers
        otp_val  = normalize_pct(otp_raw)
        otif_val = normalize_pct(otif_raw)

        # Fallback: if both are 0, try scanning column headers for OTP/OTIF
        if otp_val == 0 and otif_val == 0:
            for col_idx, col_name in enumerate(df.columns):
                col_str = str(col_name).strip().upper()
                if "OTP" in col_str:
                    otp_val = normalize_pct(row.iloc[0, col_idx])
                if "OTIF" in col_str:
                    otif_val = normalize_pct(row.iloc[0, col_idx])

        return otp_val, otif_val

    except:
        try:
            wb = load_workbook(
                TNA_FILE,
                read_only=True,
                data_only=True
            )

            ws = wb["Dispatch OTIF"]

            # Find OTP / OTIF column indices from header row
            otp_col_idx  = None
            otif_col_idx = None

            for header_row in ws.iter_rows(min_row=1, max_row=5):
                for cell in header_row:
                    cell_str = str(cell.value or "").strip().upper()
                    if "OTP" in cell_str and otp_col_idx is None:
                        otp_col_idx = cell.column - 1   # 0-based
                    if "OTIF" in cell_str and otif_col_idx is None:
                        otif_col_idx = cell.column - 1

            def normalize_pct(value):
                if value is None:
                    return 0
                try:
                    value = float(value)
                except:
                    return 0
                if value <= 1:
                    return value * 100
                elif value <= 100:
                    return value
                else:
                    return 0

            for row in ws.iter_rows():
                if str(row[1].value).strip() == "Grand Total":
                    # Use detected column indices, fallback to 4 & 5
                    otp_raw  = row[otp_col_idx].value  if otp_col_idx  is not None else row[5].value
                    otif_raw = row[otif_col_idx].value if otif_col_idx is not None else row[6].value

                    return normalize_pct(otp_raw), normalize_pct(otif_raw)

        except:
            pass

        return shared_state["otp"], shared_state["otif"]


# ================= B2% AND DHU =================

def load_b2_metrics():
    if not file_exists(CTS_FILE):
        return shared_state["b2_metrics"]

    try:
        df = pd.read_excel(CTS_FILE, header=6)

        required = [
            "Till Date Cutting",
            "WH B2 Balance",
            "WH Leftover Balance",
            "Total Approved Samples",
            "Last Shipment Date"
        ]

        df = df[required].copy()

        df.columns = [
            "cut_qty",
            "b2",
            "leftover",
            "sample",
            "last_ship_date"
        ]

        df["cut_qty"] = pd.to_numeric(df["cut_qty"], errors="coerce").fillna(0)
        df["b2"] = pd.to_numeric(df["b2"], errors="coerce").fillna(0)
        df["leftover"] = pd.to_numeric(df["leftover"], errors="coerce").fillna(0)
        df["sample"] = pd.to_numeric(df["sample"], errors="coerce").fillna(0)
        df["last_ship_date"] = pd.to_datetime(df["last_ship_date"], errors="coerce")

        return df

    except:
        return shared_state["b2_metrics"]


def calculate_b2_metrics(df, selected_month=None):
    if df is None or df.empty:
        return (0, 0, 0)

    if selected_month and selected_month != "All":
        selected_period = pd.Period(
            datetime.strptime(selected_month, "%b-%y"),
            freq="M"
        )

        df = df[
            df["last_ship_date"].dt.to_period("M") == selected_period
        ]

    total_cut = df["cut_qty"].sum()

    if total_cut == 0:
        return (0, 0, 0)

    b2 = (df["b2"].sum() / total_cut) * 100
    leftover = (df["leftover"].sum() / total_cut) * 100
    sample = (df["sample"].sum() / total_cut) * 100

    return b2, leftover, sample


def read_excel_a4(path):
    if not file_exists(path):
        # File missing OR mid-write — signal "unknown" rather than 0 so
        # calculate_dhu_metrics() can fall back to the last cached value
        # instead of computing a false 0%/low DHU off a partial file.
        return None
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        value = ws["A4"].value
        return float(value) if value else 0
    except:
        return None


def calculate_dhu_metrics():
    prev = shared_state.get("dhu_metrics") or (0, 0, 0)

    faults1 = read_excel_a4(TOTAL_FAULTS_1)
    pcs1 = read_excel_a4(CHECKED_PCS_1)

    faults2 = read_excel_a4(TOTAL_FAULTS_2)
    pcs2 = read_excel_a4(CHECKED_PCS_2)

    # Any of the 4 source files missing or currently being written ->
    # keep showing the last good DHU numbers instead of recomputing off
    # a partial read.
    if None in (faults1, pcs1, faults2, pcs2):
        return prev

    dhu1 = (faults1 / pcs1) * 100 if pcs1 else 0
    dhu2 = (faults2 / pcs2) * 100 if pcs2 else 0

    total_faults = faults1 + faults2
    total_pcs = pcs1 + pcs2

    both = (total_faults / total_pcs) * 100 if total_pcs else 0

    return dhu1, dhu2, both

# ================= DEPT EFF =================
def load_dept_efficiency():
    if not file_exists(MANUAL_FILE):
        return shared_state["dept_efficiency"]

    try:
        unit1 = pd.read_excel(
            MANUAL_FILE,
            sheet_name="Eff Unit 1"
        )

        unit2 = pd.read_excel(
            MANUAL_FILE,
            sheet_name="EFF unit 2"
        )

        targets = pd.read_excel(
            MANUAL_FILE,
            sheet_name="Targets",
            header=1
        )

        unit1["Date"] = pd.to_datetime(unit1.iloc[:, 0], errors="coerce")
        unit2["Date"] = pd.to_datetime(unit2.iloc[:, 0], errors="coerce")

        return {
            "unit1": unit1,
            "unit2": unit2,
            "targets": targets
        }

    except:
        return shared_state["dept_efficiency"]


def get_dept_efficiency(selected_month, selected_unit):
    data = shared_state["dept_efficiency"]

    if not data:
        return pd.DataFrame()

    unit1 = data["unit1"]
    unit2 = data["unit2"]

    if selected_month != "All":
        selected_period = pd.Period(
            datetime.strptime(selected_month, "%b-%y"),
            freq="M"
        )

        unit1 = unit1[
            unit1["Date"].dt.to_period("M") == selected_period
        ]

        unit2 = unit2[
            unit2["Date"].dt.to_period("M") == selected_period
        ]

    if unit1.empty:
        return pd.DataFrame()

    if selected_unit == "Unit 1":
        row = unit1.iloc[0]

        chart_data = pd.DataFrame({
            "Department": [
                "CUTTING",
                "STITCHING",
                "WASHING",
                "FINISHING"
            ],
            "Efficiency": [
                row.iloc[1],
                row.iloc[2],
                row.iloc[3],
                row.iloc[4]
            ]
        })

    elif selected_unit == "Unit 2":
        if unit2.empty:
            return pd.DataFrame()

        row = unit2.iloc[0]

        chart_data = pd.DataFrame({
            "Department": [
                "STITCHING",
                "WASHING",
                "FINISHING"
            ],
            "Efficiency": [
                row.iloc[2],
                row.iloc[3],
                row.iloc[4]
            ]
        })

    else:
        row = unit1.iloc[0]

        chart_data = pd.DataFrame({
            "Department": [
                "CUTTING",
                "STITCHING",
                "WASHING",
                "FINISHING"
            ],
            "Efficiency": [
                row.iloc[9] * 100,
                row.iloc[6],
                row.iloc[7],
                row.iloc[8]
            ]
        })

    return chart_data

# ================= MTD Backlog =================

def load_mtd_backlog():
    if not file_exists(DPS_FILE):
        return shared_state["mtd_backlog"]

    try:
        df = pd.read_excel(DPS_FILE, header=None)

        backlog_row = df.iloc[7]
        output_row = df.iloc[5]
        target_row = df.iloc[6]

        data = {
            "Cutting": {
                "backlog": backlog_row[1],
                "output": output_row[1],
                "target": target_row[1]
            },
            "Sewing Unit 1": {
                "backlog": backlog_row[2],
                "output": output_row[2],
                "target": target_row[2]
            },
            "Sewing Unit 2": {
                "backlog": backlog_row[3],
                "output": output_row[3],
                "target": target_row[3]
            },
            "Sewing Total": {
                "backlog": backlog_row[4],
                "output": output_row[4],
                "target": target_row[4]
            },
            "Washing Unit 1": {
                "backlog": backlog_row[5],
                "output": output_row[5],
                "target": target_row[5]
            },
            "Washing Unit 2": {
                "backlog": backlog_row[6],
                "output": output_row[6],
                "target": target_row[6]
            },
            "Washing Total": {
                "backlog": backlog_row[7],
                "output": output_row[7],
                "target": target_row[7]
            },
            "Packing Unit 1": {
                "backlog": backlog_row[8],
                "output": output_row[8],
                "target": target_row[8]
            },
            "Packing Unit 2": {
                "backlog": backlog_row[9],
                "output": output_row[9],
                "target": target_row[9]
            },
            "Packing Total": {
                "backlog": backlog_row[10],
                "output": output_row[10],
                "target": target_row[10]
            }
        }

        return data

    except:
        return shared_state["mtd_backlog"]


def get_mtd_backlog(selected_unit):
    data = shared_state["mtd_backlog"]

    if not data:
        return pd.DataFrame()

    if selected_unit == "Unit 1":
        rows = [
            ("1", "Cutting"),
            ("2", "Sewing Unit 1"),
            ("5", "Washing Unit 1"),
            ("8", "Packing Unit 1")
        ]

    elif selected_unit == "Unit 2":
        rows = [
            ("3", "Sewing Unit 2"),
            ("6", "Washing Unit 2"),
            ("9", "Packing Unit 2")
        ]

    else:
        rows = [
            ("4", "Sewing Total"),
            ("7", "Washing Total"),
            ("10", "Packing Total")
        ]

    result = []

    for sr, dept in rows:
        backlog_val = data[dept]['backlog']
        output_val = data[dept]['output']
        target_val = data[dept].get('target', None)

        try:
            backlog_int = int(backlog_val)
            backlog_str = f"{backlog_int:,}"
        except:
            backlog_str = str(backlog_val)

        try:
            output_int = int(output_val)
            output_str = f"{output_int:,}"
        except:
            output_str = str(output_val)

        try:
            out_f = float(output_val)
            tgt_f = float(target_val) if target_val is not None else None
            
            if tgt_f is None or pd.isna(tgt_f):
                color = "#808080"
            elif out_f >= tgt_f:
                color = "#135A11"
            else:
                color = "#D64550"
        except:
            color = "#808080"

        result.append({
            "Sr": sr,
            "Dept": dept,
            "Backlog": backlog_str,
            "Output": f'<span style="color: {color}; font-weight: bold;">{output_str}</span>'
        })

    return pd.DataFrame(result)

# =================MINUTES & VARIANCE =================

def load_minutes_variance():
    if not file_exists(MANUAL_FILE):
        return shared_state["minutes_variance"]

    try:
        df = pd.read_excel(
            MANUAL_FILE,
            sheet_name="Sheet 1"
        )

        df["Date"] = pd.to_datetime(df.iloc[:, 0], errors="coerce")

        df = df.rename(columns={
            df.columns[1]: "Earned",
            df.columns[4]: "PlanAvailable",
            df.columns[3]: "Unit"
        })

        return df

    except:
        return shared_state["minutes_variance"]


def get_minutes_variance(selected_month, selected_unit):
    df = shared_state["minutes_variance"]

    if df is None or df.empty:
        return 0, 0, 0, 0

    if selected_month != "All":
        selected_period = pd.Period(
            datetime.strptime(selected_month, "%b-%y"),
            freq="M"
        )

        df = df[
            df["Date"].dt.to_period("M") == selected_period
        ]

    if selected_unit == "Unit 1":
        df = df[df["Unit"] == 1]

    elif selected_unit == "Unit 2":
        df = df[df["Unit"] == 2]

    else:
        df = df[
            df["Unit"].astype(str).str.lower() == "both"
        ]

    earned = df["Earned"].sum()
    plan = df["PlanAvailable"].sum()

    if plan == 0:
        percent = 0
    else:
        percent = (earned / plan) * 100

    variance = earned - plan

    return earned, plan, percent, variance


# ================= DETAIL / DRILL-DOWN VIEWS =================
# Clicking a KPI opens a new browser tab pointed at "?view=<key>" on this
# same app URL. When that query param is present we skip the whole
# dashboard and render only the relevant raw source data instead.

DETAIL_VIEW_TITLES = {
    "mtd_backlog":        "MTD Backlog",
    "minutes_variance":   "Minutes & Variance",
    "dept_efficiency":    "Dept Wise Efficiency",
    "till_date_dispatch": "Till Date Dispatch",
    "cts":                "CTS %",
    "b2_dhu":              "B2% & DHU",
    "wip":                "WIP",
    "first_pass_ratio":   "First Pass Ratio",
    "dps_dashboard":      "DPS Dashboard",
}


def _style_pos_neg(val):
    """Green for positive numbers, red for negative — mirrors the source sheet."""
    try:
        v = float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return ""
    if v < 0:
        return "color:#D64550; font-weight:700;"
    elif v > 0:
        return "color:#1F6437; font-weight:700;"
    return ""


def _render_filterable_table(df, key, height=520):
    """
    Renders df with per-column text filter boxes using only native Streamlit
    widgets (no custom component / iframe), so there's no dependency on an
    external JS bundle loading over the proxy. Returns the filtered df.
    """
    filter_key = f"{key}_filters"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = {}

    with st.expander("🔍 Filters", expanded=False):
        cols = st.columns(min(len(df.columns), 4))
        for i, col in enumerate(df.columns):
            with cols[i % len(cols)]:
                val = st.text_input(col, key=f"{key}_{col}", placeholder="contains...")
                st.session_state[filter_key][col] = val

    filtered = df.copy()
    for col, val in st.session_state[filter_key].items():
        if val:
            filtered = filtered[
                filtered[col].astype(str).str.contains(val, case=False, na=False, regex=False)
            ]

    st.caption(f"Showing {len(filtered):,} of {len(df):,} rows")
    st.dataframe(filtered, use_container_width=True, height=height, hide_index=True)

    return filtered


def _read_workbook_cell(path, cell, sheet_name=None):
    """Read a single cell's numeric value from an Excel workbook (e.g. 'B2')."""
    if not file_exists(path):
        return None
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet_name] if sheet_name else wb.active
        value = ws[cell].value
        return float(value) if value is not None else None
    except Exception:
        return None


def _load_budget_target_series():
    """DPS Dashboard 'Target' sheet: month headers on row 1 (cols C:N) and
    values on row 2 (cols C:N) -> {Period('2026-07'): 664716.0, ...}."""
    if not file_exists(DPS_DASHBOARD_FILE):
        return None
    try:
        raw = pd.read_excel(DPS_DASHBOARD_FILE, sheet_name="Target", header=None)
        header_row = raw.iloc[0]
        value_row = raw.iloc[1]

        months = {}
        for col_idx in range(2, raw.shape[1]):  # column C onward
            header_val = header_row[col_idx]
            if pd.isna(header_val):
                continue
            try:
                if isinstance(header_val, str):
                    month_dt = datetime.strptime(header_val.strip(), "%b-%y")
                elif hasattr(header_val, "year"):
                    month_dt = datetime(header_val.year, header_val.month, 1)
                else:
                    continue
            except (ValueError, TypeError):
                continue

            val = pd.to_numeric(value_row[col_idx], errors="coerce")
            if pd.notna(val):
                months[pd.Period(month_dt, freq="M")] = float(val)

        return months or None
    except Exception:
        return None


def _get_budget_cutoff_period():
    """Last month the cumulative Budget total should include. Normally the
    prior month; once the current month reaches its last or second-to-last
    day it's treated as closed and folded into the total instead."""
    today = datetime.now()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    current_period = pd.Period(today, freq="M")
    if today.day >= days_in_month - 1:
        return current_period
    return current_period - 1


def _load_actual_output_series():
    """Cut to Pack report: 'First Output Date' (col AD) grouped by month,
    summed on 'Total Sewing Output' (col AH) -> {Period('2026-07'): 21780.0, ...}.
    Same dynamic -1 month cutoff as the Budget series (see
    _get_budget_cutoff_period) is applied by the caller, not here."""
    file_path = get_cut_to_pack_file()
    if not file_path:
        return None
    try:
        raw = pd.read_excel(file_path)
        if raw.shape[1] <= 33:
            return None

        dates = pd.to_datetime(raw.iloc[:, 29], errors="coerce")   # AD: First Output Date
        values = pd.to_numeric(raw.iloc[:, 33], errors="coerce")   # AH: Total Sewing Output

        df = pd.DataFrame({"date": dates, "value": values}).dropna(subset=["date"])
        df = df[df["date"] >= pd.Timestamp("2026-07-01")]
        if df.empty:
            return None

        grouped = df.groupby(df["date"].dt.to_period("M"))["value"].sum(min_count=1)
        months = {p: float(v) for p, v in grouped.items() if pd.notna(v)}

        return months or None
    except Exception:
        return None


def _detail_header(title, note=None):
    st.markdown(f"""
        <div style="padding:6px 0 18px 0;">
            <a href="?" style="text-decoration:none; color:#6c757d; font-size:13px;">&larr; Back to Dashboard</a>
            <h2 style="margin:8px 0 2px 0; color:#31333F;">{title}</h2>
        </div>
    """, unsafe_allow_html=True)
    if note:
        st.caption(note)


def _render_mtd_backlog_detail():
    _detail_header("MTD Backlog — Department Wise Target vs Actual Summary")

    st.markdown(
        '<a href="?view=dps_dashboard" target="_blank" style="'
        'display:inline-flex; align-items:center; justify-content:center; '
        'background:#f0f2f6; color:#31333F; font-weight:500; font-size:13px; '
        'border:1px solid #e6e9ef; border-radius:8px; padding:0 16px; height:38px; '
        'text-decoration:none; white-space:nowrap; margin-bottom:16px;">'
        'DPS Dashboard</a>',
        unsafe_allow_html=True
    )

    ppc_target = _read_workbook_cell(DPS_FILE, "E10")
    budget_target = _read_workbook_cell(DPS_DASHBOARD_FILE, "B2", sheet_name="Target")
    variance = (
        ppc_target - budget_target
        if ppc_target is not None and budget_target is not None
        else None
    )
    variance_color = get_variance_color(variance) if variance is not None else "#808080"

    budget_series = _load_budget_target_series()
    cutoff_period = _get_budget_cutoff_period()
    cumulative_budget = None
    budget_range_label = ""
    if budget_series:
        in_range = {p: v for p, v in budget_series.items() if p <= cutoff_period}
        if in_range:
            start_period = min(in_range.keys())
            cumulative_budget = sum(in_range.values())
            budget_range_label = f"{start_period.strftime('%b-%y')} to {cutoff_period.strftime('%b-%y')}"

    # Actual uses the same dynamic cutoff_period as Budgeted, so both
    # cumulative totals always cover the same month range.
    actual_series = _load_actual_output_series()
    cumulative_actual = None
    actual_range_label = ""
    if actual_series:
        in_range_actual = {p: v for p, v in actual_series.items() if p <= cutoff_period}
        if in_range_actual:
            start_period_actual = min(in_range_actual.keys())
            cumulative_actual = sum(in_range_actual.values())
            actual_range_label = f"{start_period_actual.strftime('%b-%y')} to {cutoff_period.strftime('%b-%y')}"

    budget_actual_variance = (
        cumulative_actual - cumulative_budget
        if cumulative_actual is not None and cumulative_budget is not None
        else None
    )
    budget_actual_variance_color = (
        get_variance_color(budget_actual_variance) if budget_actual_variance is not None else "#808080"
    )

    st.markdown(f"""
        <div style="display:flex; gap:32px; margin:0 0 20px 0;">
            <div>
                <div style="font-size:14px;font-weight:700;color:#31333F;">PPC Monthly Target</div>
                <div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(ppc_target) if ppc_target is not None else "-"}</div>
            </div>
            <div>
                <div style="font-size:14px;font-weight:700;color:#31333F;">Budget Target Monthly</div>
                <div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(budget_target) if budget_target is not None else "-"}</div>
            </div>
            <div>
                <div style="font-size:14px;font-weight:700;color:#31333F;">Variance</div>
                <div style="font-size:32px;font-weight:700;color:{variance_color};">{format_number(variance) if variance is not None else "-"}</div>
            </div>
            <div style="margin-left:auto; text-align:right;">
                <div style="font-size:13px;font-weight:600;color:#6c757d;">{budget_range_label}</div>
                <div style="font-size:14px;font-weight:700;color:#31333F;margin-top:4px;">Budgeted</div>
                <div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(cumulative_budget) if cumulative_budget is not None else "-"}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:13px;font-weight:600;color:#6c757d;">{actual_range_label}</div>
                <div style="font-size:14px;font-weight:700;color:#31333F;margin-top:4px;">Actual</div>
                <div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(cumulative_actual) if cumulative_actual is not None else "-"}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:14px;font-weight:700;color:#31333F;margin-top:21px;">Variance</div>
                <div style="font-size:32px;font-weight:700;color:{budget_actual_variance_color};">{format_number(budget_actual_variance) if budget_actual_variance is not None else "-"}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if not file_exists(DPS_FILE):
        st.warning("Source file not found on disk.")
        return

    df = pd.read_excel(DPS_FILE, header=1)
    df = df.rename(columns={df.columns[0]: "Metric"})
    df = df.dropna(how="all")

    numeric_cols = [c for c in df.columns if c != "Metric"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    def fmt(v):
        if pd.isna(v):
            return ""
        if float(v).is_integer():
            return f"{v:,.0f}"
        return f"{v:,.2f}"

    styler = df.style
    try:
        styler = styler.map(_style_pos_neg, subset=numeric_cols)          # pandas >= 2.1
    except AttributeError:
        styler = styler.applymap(_style_pos_neg, subset=numeric_cols)     # older pandas

    styled = (
        styler
        .format(fmt, subset=numeric_cols)
        .set_properties(subset=["Metric"], **{"font-weight": "700"})
    )

    st.dataframe(styled, use_container_width=True, height=560)


def _render_dps_dashboard_detail():
    _detail_header("DPS Dashboard")

    if not file_exists(DPS_DASHBOARD_FILE):
        st.warning("Source file not found on disk.")
        return

    try:
        raw = pd.read_excel(DPS_DASHBOARD_FILE, header=None)
    except Exception as e:
        st.error(f"Could not read source data: {e}")
        return

    # ── Table 1: Production Summary — headers A2:I2, data A3:I13 ──────────
    st.subheader("Production Summary", anchor=False)
    try:
        headers1 = raw.iloc[1, 0:9].tolist()
        col_names1 = [str(h).strip() if pd.notna(h) and str(h).strip() != "" else f"Col{i+1}"
                      for i, h in enumerate(headers1)]

        data1 = raw.iloc[2:13, 0:9].copy()
        data1.columns = col_names1

        dev_col = next((c for c in col_names1 if c.strip().lower() == "deviation"), None)
        eff_col = next((c for c in col_names1 if "efficiency" in c.strip().lower()), None)
        dept_col = col_names1[0]

        display1 = data1.copy()
        for c in col_names1:
            if c in (dev_col, eff_col):
                continue
            display1[c] = display1[c].apply(_fmt_generic)

        if eff_col is not None:
            display1[eff_col] = pd.to_numeric(data1[eff_col], errors="coerce").apply(
                lambda v: f"{v * 100:.0f}%" if pd.notna(v) else ""
            )

        # Bold whole rows for section headers/totals, mirroring the bold
        # formatting on these rows in the source sheet (CUTTING, Sew Total,
        # Wash Total, Packing Total).
        BOLD_DEPT_ROWS = {"CUTTING", "Sew Total", "Wash Total", "Packing Total"}

        def _bold_total_row(row):
            if str(row[dept_col]).strip() in BOLD_DEPT_ROWS:
                return ["font-weight:700;"] * len(row)
            return [""] * len(row)

        styler1 = display1.style.apply(_bold_total_row, axis=1)
        if dev_col is not None:
            try:
                styler1 = styler1.map(_style_pos_neg, subset=[dev_col])
            except AttributeError:
                styler1 = styler1.applymap(_style_pos_neg, subset=[dev_col])
            styler1 = styler1.format({dev_col: _fmt_signed_paren})
        st.dataframe(styler1, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not render Production Summary: {e}")

    st.markdown("---")

    # ── Table 2: WIP — headers A16:E16, data A17:E25 ───────────────────────
    st.subheader("WIP", anchor=False)
    try:
        headers2 = raw.iloc[15, 0:5].tolist()
        col_names2 = [str(h).strip() if pd.notna(h) and str(h).strip() != "" else f"Col{i+1}"
                      for i, h in enumerate(headers2)]

        data2 = raw.iloc[16:25, 0:5].copy()
        data2.columns = col_names2

        diff_col = next((c for c in col_names2 if c.strip().lower() == "diff"), None)

        display2 = data2.copy()
        for c in col_names2:
            if c == diff_col:
                continue
            display2[c] = display2[c].apply(_fmt_generic)

        if diff_col is not None:
            styler2 = display2.style
            try:
                styler2 = styler2.map(_style_pos_neg, subset=[diff_col])
            except AttributeError:
                styler2 = styler2.applymap(_style_pos_neg, subset=[diff_col])
            styler2 = styler2.format({diff_col: _fmt_signed_paren})
            st.dataframe(styler2, use_container_width=True, hide_index=True)
        else:
            st.dataframe(display2, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not render WIP: {e}")

    st.markdown("---")

    # ── Table 3: Production Backlog — dept A29:A35, value C29:C35 ─────────
    st.subheader("Production Backlog", anchor=False)
    try:
        dept3 = raw.iloc[28:35, 0].tolist()
        val3 = raw.iloc[28:35, 2].tolist()
        table3 = pd.DataFrame({"Dept": dept3, "Value": val3})
        table3["Dept"] = table3["Dept"].apply(_fmt_generic)
        table3["Value"] = table3["Value"].apply(_fmt_generic)
        st.dataframe(table3, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not render Production Backlog: {e}")

    st.markdown("---")

    # ── Table 4: Production Backlog Reasons — dept A39:A45, reason C39:C45
    st.subheader("Production Backlog Reasons", anchor=False)
    try:
        dept4 = raw.iloc[38:45, 0].tolist()
        reason4 = raw.iloc[38:45, 2].tolist()
        table4 = pd.DataFrame({"Dept": dept4, "Reason": reason4})
        table4["Dept"] = table4["Dept"].apply(_fmt_generic)
        table4["Reason"] = table4["Reason"].apply(_fmt_generic)
        st.dataframe(table4, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not render Production Backlog Reasons: {e}")

    st.markdown("---")

    # ── Table 5: Dispatch Backlog — dept A49:A55, qty B49:B55 ───────────────
    st.subheader("Dispatch Backlog", anchor=False)
    try:
        dept5 = raw.iloc[48:55, 0].tolist()
        qty5 = raw.iloc[48:55, 1].tolist()
        table5 = pd.DataFrame({"Dept": dept5, "Qty": qty5})
        table5["Dept"] = table5["Dept"].apply(_fmt_generic)
        table5["Qty"] = pd.to_numeric(table5["Qty"], errors="coerce").fillna(0).apply(lambda v: f"{v:,.0f}")
        st.dataframe(table5, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not render Dispatch Backlog: {e}")


def _render_minutes_variance_detail():
    _detail_header("Minutes & Variance - Breakdown", "Sheet: 'Sheet 1'")

    if not file_exists(MANUAL_FILE):
        st.warning("Source file not found on disk.")
        return

    try:
        raw_df = pd.read_excel(MANUAL_FILE, sheet_name="Sheet 1")
    except Exception as e:
        st.error(f"Could not read source data: {e}")
        return

    # A = Date, B = Earned Minutes, C = Plan Minutes, D = Unit,
    # E = Plan Available, F = Variance
    if raw_df.shape[1] < 6:
        st.error(f"Source sheet only has {raw_df.shape[1]} columns; expected at least 6.")
        return

    df = raw_df.iloc[:, [0, 1, 2, 3, 4, 5]].copy()
    df.columns = ["Date", "Earned Minutes", "Plan Minutes", "Unit", "Plan Available", "Variance"]

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in ["Earned Minutes", "Plan Minutes", "Plan Available", "Variance"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(how="all", subset=["Earned Minutes", "Plan Minutes", "Unit"])

    if df.empty:
        st.info("No data available.")
        return

    # Reserve space for the summary metrics ABOVE the table — filled in
    # after the table renders, using whatever rows are currently visible
    # (e.g. filtered down to Unit "1" and a specific Date), so it updates
    # live as you filter — same pattern as the CTS / B2 / Dispatch pages.
    metrics_placeholder = st.empty()

    st.markdown("<br>", unsafe_allow_html=True)

    display_df = df.sort_values("Date", ascending=False).copy()
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
    for col in ["Earned Minutes", "Plan Minutes", "Plan Available", "Variance"]:
        display_df[col] = display_df[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

    # _render_filterable_table gives a "contains" filter box for every
    # column shown, which covers Date and Unit as requested (plus the
    # numeric columns too, at no extra cost).
    filtered_df = _render_filterable_table(display_df, key="minutes_variance_grid")

    def _num(col):
        if filtered_df.empty:
            return 0
        return pd.to_numeric(
            filtered_df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
        ).fillna(0).sum()

    total_earned = _num("Earned Minutes")
    total_plan = _num("Plan Minutes")
    total_variance = _num("Variance")

    with metrics_placeholder.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Earned Minutes", format_number(total_earned))
        c2.metric("Plan Minutes", format_number(total_plan))
        c3.metric("Variance", format_number(total_variance))


def _render_dept_efficiency_detail():
    _detail_header("Efficiency Breakdown")

    if not file_exists(EFF_REPORT_FILE):
        st.warning("Source file not found on disk.")
        return

    try:
        raw_df = pd.read_excel(EFF_REPORT_FILE)
    except Exception as e:
        st.error(f"Could not read source data: {e}")
        return

    # (Excel column letter, 0-indexed position, is this a % column?)
    # F, N, S, Y are the "...Today Efficiency" columns per department block.
    col_map = [
        ("B", 1,  False),
        ("C", 2,  False),
        ("F", 5,  True),
        ("H", 7,  False),
        ("I", 8,  False),
        ("J", 9,  False),
        ("N", 13, True),
        ("O", 14, False),
        ("S", 18, True),
        ("T", 19, False),
        ("U", 20, False),
        ("Y", 24, True),
    ]

    max_col = max(idx for _, idx, _ in col_map)
    if raw_df.shape[1] <= max_col:
        st.error(
            f"Source sheet only has {raw_df.shape[1]} columns; expected at least "
            f"{max_col + 1} to reach column {col_map[-1][0]}."
        )
        return

    positions = [idx for _, idx, _ in col_map]
    pct_flags = [is_pct for _, _, is_pct in col_map]

    df = raw_df.iloc[:, positions].copy()

    # Keep the sheet's own header text for every column except the first,
    # which is explicitly renamed from "Efficiency Date" -> "Date".
    original_names = list(df.columns)
    new_names = ["Date"] + [str(c).strip() for c in original_names[1:]]
    df.columns = new_names

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    if df.empty:
        st.info("No data available.")
        return

    display_df = df.sort_values("Date", ascending=False).copy()
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")

    for col, is_pct in zip(new_names, pct_flags):
        if col == "Date":
            continue
        numeric = pd.to_numeric(display_df[col], errors="coerce")
        if is_pct:
            display_df[col] = numeric.apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "")
        elif numeric.notna().any():
            # Comma-format only columns that are actually numeric — text
            # columns like Unit/Line names pass through untouched.
            display_df[col] = numeric.apply(
                lambda v: (f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}") if pd.notna(v) else ""
            )

    _render_filterable_table(display_df, key="dept_efficiency_grid")


def _render_till_date_dispatch_detail():
    _detail_header("Till Date Dispatch")

    if not file_exists(SUPPLY_FILE):
        st.warning("Source file not found on disk.")
        return

    df = load_supply_data()
    if df is None or df.empty:
        st.info("No matching rows found.")
        return

    target = get_dispatch_target()

    # Reserve space for the metrics ABOVE the table — filled in after the
    # table renders, using whatever rows are currently visible (e.g.
    # filtered down to one Party), so this updates live as you filter.
    metrics_placeholder = st.empty()

    st.markdown("<br>", unsafe_allow_html=True)

    display_df = df[["dispatch_date", "order_no", "qty_units", "sale_type", "party_short"]].copy()
    display_df.columns = ["Date", "Order No.", "Quantity", "Unit", "Party"]
    display_df = display_df.sort_values("Date", ascending=False)
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
    display_df["Quantity"] = display_df["Quantity"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

    filtered_df = _render_filterable_table(display_df, key="till_date_dispatch_grid")

    filtered_qty = (
        pd.to_numeric(
            filtered_df["Quantity"].astype(str).str.replace(",", "", regex=False),
            errors="coerce"
        ).fillna(0).sum()
        if not filtered_df.empty else 0
    )

    with metrics_placeholder.container():
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div style="font-size:14px;font-weight:700;color:#31333F;">Target</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(target)}</div>', unsafe_allow_html=True)
        with c2:
            st.markdown('<div style="font-size:14px;font-weight:700;color:#31333F;">Till Date Dispatch (filtered)</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="font-size:32px;font-weight:700;color:#31333F;">{format_number(filtered_qty)}</div>', unsafe_allow_html=True)

def _load_cts_detail_df():
    if not file_exists(CTS_FILE):
        return None
    try:
        df = pd.read_excel(CTS_FILE, header=6)
        df = df[[
            "Customer Name",
            "Tracking Number",
            "Till Date Cutting",
            "Till Date Dispatch Qty",
            "Last Shipment Date",
            "BAL To Ship"
        ]].copy()

        df.columns = ["Customer Name", "Tracking Number", "Cut Qty", "Dispatch Qty", "Date", "Balance to Ship"]

        df["Cut Qty"] = pd.to_numeric(df["Cut Qty"], errors="coerce").fillna(0)
        df["Dispatch Qty"] = pd.to_numeric(df["Dispatch Qty"], errors="coerce").fillna(0)
        df["Balance to Ship"] = pd.to_numeric(df["Balance to Ship"], errors="coerce").fillna(0)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        # Same row filter used to calculate the CTS % KPI (calculate_cts / load_cts_data)
        df = df[df["Cut Qty"] > 0]
        return df
    except Exception:
        return None


def _render_cts_detail():
    _detail_header("CTS% Breakdown")

    if not file_exists(CTS_FILE):
        st.warning("Source file not found on disk.")
        return

    df = _load_cts_detail_df()
    if df is None or df.empty:
        st.info("No data available.")
        return

    metrics_placeholder = st.empty()

    st.markdown("<br>", unsafe_allow_html=True)

    display_df = df[["Customer Name", "Tracking Number", "Cut Qty", "Dispatch Qty", "Date", "Balance to Ship"]].copy()
    display_df = display_df.sort_values("Date", ascending=False)
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
    for col in ["Cut Qty", "Dispatch Qty", "Balance to Ship"]:
        display_df[col] = display_df[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

    filtered_df = _render_filterable_table(display_df, key="cts_grid")

    def _num(col):
        if filtered_df.empty:
            return 0
        return pd.to_numeric(
            filtered_df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
        ).fillna(0).sum()

    filtered_cut_qty = _num("Cut Qty")
    filtered_dispatch = _num("Dispatch Qty")
    filtered_balance = _num("Balance to Ship")
    filtered_cts = ((filtered_dispatch + filtered_balance) / filtered_cut_qty * 100) if filtered_cut_qty else 0

    with metrics_placeholder.container():
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Cut Qty", format_number(filtered_cut_qty))
        c2.metric("Dispatch Qty", format_number(filtered_dispatch))
        c3.metric("CTS %", f"{filtered_cts:.2f}%")

def _load_b2_detail_df():
    if not file_exists(CTS_FILE):
        return None
    try:
        df = pd.read_excel(CTS_FILE, header=6)
        df = df[[
            "Customer Name",
            "Tracking Number",
            "Till Date Cutting",
            "WH B2 Balance",
            "WH Leftover Balance",
            "Total Approved Samples",
            "Last Shipment Date"
        ]].copy()

        df.columns = ["Customer Name", "Tracking Number", "Cut Qty", "B2", "Leftover", "Sample", "Date"]

        for c in ["Cut Qty", "B2", "Leftover", "Sample"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        return df
    except Exception:
        return None


def _render_b2_dhu_detail():
    _detail_header("B2% & DHU — Detail")

    st.subheader("B2 / Leftover / Sample", anchor=False)

    if not file_exists(CTS_FILE):
        st.warning("Source file not found on disk.")
    else:
        df = _load_b2_detail_df()
        if df is None or df.empty:
            st.info("No data available.")
        else:
            metrics_placeholder = st.empty()

            st.markdown("<br>", unsafe_allow_html=True)

            display_df = df.sort_values("Date", ascending=False).copy()
            display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")
            for col in ["Cut Qty", "B2", "Leftover", "Sample"]:
                display_df[col] = display_df[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

            filtered_df = _render_filterable_table(display_df, key="b2_grid")

            def _num(col):
                if filtered_df.empty:
                    return 0
                return pd.to_numeric(
                    filtered_df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
                ).fillna(0).sum()

            filtered_cut = _num("Cut Qty")
            filtered_b2 = _num("B2")
            filtered_leftover = _num("Leftover")
            filtered_sample = _num("Sample")

            b2_pct = (filtered_b2 / filtered_cut * 100) if filtered_cut else 0
            leftover_pct = (filtered_leftover / filtered_cut * 100) if filtered_cut else 0
            sample_pct = (filtered_sample / filtered_cut * 100) if filtered_cut else 0

            with metrics_placeholder.container():
                c1, c2, c3 = st.columns(3)
                c1.metric("B2 %", f"{b2_pct:.2f}%")
                c2.metric("Leftover %", f"{leftover_pct:.2f}%")
                c3.metric("Sample %", f"{sample_pct:.2f}%")

    st.markdown("---")
    st.subheader("DHU (Faults / Checked Pieces)", anchor=False)
    dhu_files = {
        "Checked Pieces — Unit 1": CHECKED_PCS_1,
        "Total Faults — Unit 1":   TOTAL_FAULTS_1,
        "Checked Pieces — Unit 2": CHECKED_PCS_2,
        "Total Faults — Unit 2":   TOTAL_FAULTS_2,
    }
    cols = st.columns(4)
    for i, (label, path) in enumerate(dhu_files.items()):
        with cols[i]:
            st.caption(label)
            if file_exists(path):
                val = read_excel_a4(path)
                st.metric(label.split(" — ")[0], f"{val:,.0f}" if val is not None else "—")
            else:
                st.warning("Not found")

    dhu1, dhu2, both = calculate_dhu_metrics()
    c1, c2, c3 = st.columns(3)
    c1.metric("DHU Unit 1", f"{dhu1:.2f}%")
    c2.metric("DHU Unit 2", f"{dhu2:.2f}%")
    c3.metric("DHU Both", f"{both:.2f}%")


def _render_otp_otif_detail():
    _detail_header("OTP / Dispatch OTIF - Detail", "Sheet: 'Dispatch OTIF'")

    if not file_exists(TNA_FILE):
        st.warning("Source file not found on disk.")
        return

    try:
        # Actual headers (Ship Mnth, Team, Cstmr, Shpd Qty., OTP', OTIF') live
        # on row 7 of the sheet -> header=6 (0-indexed).
        df = pd.read_excel(TNA_FILE, sheet_name="Dispatch OTIF", header=6)
    except Exception as e:
        st.error(f"Could not read source data: {e}")
        return

    # Column C = Team, D = Customer, E = Shipped Qty, F = OTP, G = OTIF
    df = df.iloc[:, [2, 3, 4, 5, 6]].copy()
    df.columns = ["Team", "Customer", "Shipped Qty", "OTP", "OTIF"]

    # Team is a merged cell in the source pivot (only set on the first row of
    # each group) -> forward-fill to "unmerge" it, same pattern used for the
    # Supply Register's merged Date/Party columns above.
    df["Team"] = df["Team"].ffill()

    # Drop fully blank trailing rows
    df = df.dropna(how="all", subset=["Customer", "Shipped Qty"])

    df["Shipped Qty"] = pd.to_numeric(df["Shipped Qty"], errors="coerce")
    df["OTP"] = pd.to_numeric(df["OTP"], errors="coerce")
    df["OTIF"] = pd.to_numeric(df["OTIF"], errors="coerce")

    if df.empty:
        st.info("No data available.")
        return

    display_df = df.copy()
    display_df["Shipped Qty"] = display_df["Shipped Qty"].apply(
        lambda v: f"{v:,.0f}" if pd.notna(v) else ""
    )
    display_df["OTP"] = display_df["OTP"].apply(
        lambda v: f"{v * 100:.0f}%" if pd.notna(v) else ""
    )
    display_df["OTIF"] = display_df["OTIF"].apply(
        lambda v: f"{v * 100:.0f}%" if pd.notna(v) else ""
    )

    _render_filterable_table(display_df, key="otp_otif_grid")


def _render_wip_detail():
    file_path = get_cut_to_pack_file()
    _detail_header("WIP - Detail")

    st.markdown("**WIP Aging**")
    aging_df = load_wip_aging_data()
    if aging_df is None or aging_df.empty:
        st.info("WIP Aging source file not found or empty.")
    else:
        display_aging = aging_df.copy()
        for col in display_aging.columns[1:]:
            display_aging[col] = display_aging[col].apply(_fmt_wip_aging_cell)
        st.dataframe(display_aging, use_container_width=True, hide_index=True)

    st.markdown("---")

    if not file_path:
        st.warning("Source file not found on disk.")
        return

    df = load_wip_data()
    if df is None or df.empty:
        st.info("No WIP data available.")
        return

    st.markdown("**Summary**")
    summary_df = calculate_wip(df).copy()
    summary_df["Value"] = summary_df["Value"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.markdown("**Underlying Records**")
    display_df = df.copy()
    display_df["book_x_factory"] = display_df["book_x_factory"].dt.strftime("%Y-%m-%d")

    numeric_cols = [
        "cutting", "stitching", "rigid_area", "washing_balance",
        "packing", "wh_rfi", "finishing", "ready_fin", "rfd"
    ]
    for col in numeric_cols:
        display_df[col] = display_df[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "")

    display_df = display_df.rename(columns={
        "tracking_number": "Tracking Number",
        "book_x_factory": "Book X Factory Date",
        "cutting": "Cutting",
        "stitching": "Stitching",
        "rigid_area": "Rigid Area",
        "washing_balance": "Washing Balance",
        "packing": "Packing",
        "wh_rfi": "WH RFI",
        "finishing": "Finishing",
        "ready_fin": "Ready Fin",
        "rfd": "RFD",
        "status": "Status"
    })

    col_order = [
        "Tracking Number", "Book X Factory Date", "Cutting", "Stitching",
        "Rigid Area", "Washing Balance", "Packing", "WH RFI",
        "Finishing", "Ready Fin", "RFD", "Status"
    ]
    display_df = display_df[col_order]

    st.dataframe(display_df, use_container_width=True, height=450, hide_index=True)


def _render_first_pass_ratio_detail():
    _detail_header("First Pass Ratio - Detail")

    if not file_exists(OQL_FILE):
        st.warning("Source file not found on disk.")
        return

    try:
        raw_df = pd.read_excel(OQL_FILE)
    except Exception as e:
        st.error(f"Could not read source data: {e}")
        return

    # A = Tracking Number, B = Customer, C = Audit Date, O = OQL Status,
    # P = Audit Status, R = Auditor Name
    df = raw_df.iloc[:, [0, 1, 2, 14, 15, 17]].copy()
    df.columns = ["Tracking Number", "Customer", "Date", "OQL Status", "Audit Status", "Auditor Name"]
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    if df.empty:
        st.info("No data available.")
        return

    # Reserve space for the overall metric ABOVE the table — filled in after
    # the grid renders using whatever rows are currently visible, so it
    # updates live as the user filters (e.g. down to one Customer).
    metrics_placeholder = st.empty()

    st.markdown("<br>", unsafe_allow_html=True)

    display_df = df.sort_values("Date", ascending=False).copy()
    display_df["Date"] = display_df["Date"].dt.strftime("%Y-%m-%d")

    filtered_df = _render_filterable_table(display_df, key="first_pass_ratio_grid")

    def _fpr(d):
        if d is None or d.empty:
            return 0.0
        first_time = d[d["Audit Status"].astype(str).str.strip().str.lower() == "1st time"]
        if first_time.empty:
            return 0.0
        passed = first_time[first_time["OQL Status"].astype(str).str.strip().str.upper() == "PASS"]
        return (len(passed) / len(first_time)) * 100

    with metrics_placeholder.container():
        st.metric("First Pass Ratio (filtered)", f"{_fpr(filtered_df):.2f}%")

    # ── Customer wise breakdown ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("First Pass Ratio — Customer Wise", anchor=False)

    if filtered_df is not None and not filtered_df.empty:
        cust_rows = []
        for cust, group in filtered_df.groupby("Customer"):
            first_time = group[group["Audit Status"].astype(str).str.strip().str.lower() == "1st time"]
            total_ft = len(first_time)
            passed = first_time[first_time["OQL Status"].astype(str).str.strip().str.upper() == "PASS"]
            cust_rows.append({
                "Customer": cust,
                "1st Time Audits": total_ft,
                "Passed": len(passed),
                "First Pass Ratio": (len(passed) / total_ft * 100) if total_ft else 0.0
            })

        cust_df = pd.DataFrame(cust_rows).sort_values("First Pass Ratio", ascending=False)

        fig = px.bar(
            cust_df, x="Customer", y="First Pass Ratio", text="First Pass Ratio",
            color="First Pass Ratio", color_continuous_scale=["#D64550", "#D9B300", "#1F6437"],
            range_color=[0, 100]
        )
        fig.update_traces(texttemplate="<b>%{text:.1f}%</b>", textposition="outside", textfont=dict(size=10))
        fig.update_layout(
            height=380, showlegend=False, coloraxis_showscale=False,
            xaxis=dict(title="", tickangle=-45, tickfont=dict(size=10)),
            yaxis=dict(title="", range=[0, 110]),
            margin=dict(t=20, b=80, l=10, r=10)
        )
        st.plotly_chart(fig, width="stretch")

        cust_display = cust_df.copy()
        cust_display["First Pass Ratio"] = cust_display["First Pass Ratio"].apply(lambda v: f"{v:.2f}%")
        st.dataframe(cust_display, use_container_width=True, hide_index=True)
    else:
        st.info("No rows to summarize.")


_DETAIL_RENDERERS = {
    "mtd_backlog": _render_mtd_backlog_detail,
    "minutes_variance": _render_minutes_variance_detail,
    "dept_efficiency": _render_dept_efficiency_detail,
    "till_date_dispatch": _render_till_date_dispatch_detail,
    "cts": _render_cts_detail,
    "b2_dhu": _render_b2_dhu_detail,
    "wip": _render_wip_detail,
    "first_pass_ratio": _render_first_pass_ratio_detail,
    "dps_dashboard": _render_dps_dashboard_detail,
}


def render_detail_page(view):
    renderer = _DETAIL_RENDERERS.get(view)
    if renderer is None:
        st.warning("Unknown detail view.")
        return
    try:
        renderer()
    except Exception as e:
        st.error(f"Could not load detail data for '{view}': {e}")


# ================= MONTH FILTER (PATCHED) =================
def get_month_options():
    all_dates = []

    if shared_state["cts_df"] is not None:
        all_dates.extend(shared_state["cts_df"]["last_ship_date"].dropna().tolist())

    if shared_state["oql_df"] is not None:
        all_dates.extend(shared_state["oql_df"]["audit_date"].dropna().tolist())

    if shared_state["supply_df"] is not None:
        all_dates.extend(shared_state["supply_df"]["dispatch_date"].dropna().tolist())

    # NEW: also pull dates from the Manual Sheet (Dept Wise Efficiency source),
    # so months that only have data entered there (e.g. current month, before
    # OQL/Supply Register entries start) still show up as selectable options.
    dept_eff = shared_state["dept_efficiency"]
    if dept_eff is not None:
        unit1 = dept_eff.get("unit1")
        unit2 = dept_eff.get("unit2")
        if unit1 is not None and "Date" in unit1.columns:
            all_dates.extend(unit1["Date"].dropna().tolist())
        if unit2 is not None and "Date" in unit2.columns:
            all_dates.extend(unit2["Date"].dropna().tolist())

    if not all_dates:
        return ["All"]

    dates = pd.Series(all_dates)
    months = sorted(dates.dt.to_period("M").unique(), reverse=True)

    return ["All"] + [m.strftime("%b-%y") for m in months]


# ================= CACHE =================
def refresh_cache():
    shared_state["cts_df"] = load_cts_data()
    shared_state["oql_df"] = load_oql_data()
    shared_state["supply_df"] = load_supply_data()
    shared_state["wip_df"] = load_wip_data()

    otp, otif = load_tna_data()
    shared_state["otp"] = otp
    shared_state["otif"] = otif
    shared_state["b2_metrics"] = load_b2_metrics()
    shared_state["dhu_metrics"] = calculate_dhu_metrics()
    shared_state["dept_efficiency"] = load_dept_efficiency()
    shared_state["mtd_backlog"] = load_mtd_backlog()
    shared_state["minutes_variance"] = load_minutes_variance()


# ================= CACHE REFRESH THREAD =================
def scheduler():
    # Background thread: periodically re-read the Excel files from data/ so the
    # dashboard reflects newly downloaded/uploaded reports.
    # The download scripts themselves are run by the panel Scheduler tab —
    # this thread only reloads data, it does not launch any subprocess.
    refresh_cache()

    while True:
        time.sleep(CACHE_REFRESH_SECONDS)
        refresh_cache()


@st.cache_resource
def start_scheduler():
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()
    return True


start_scheduler()

# ================= UI =================
st.set_page_config(
    page_title="Operations Dashboard - MG Apparel",
    layout="wide"
)

col1, col2 = st.columns([1, 8])

with col1:
    st.image(
        "https://mgapparel.com/images/brand/logo-full.png",
        width=80
    )

with col2:
    st.markdown(
        "<h1 style='margin: 0; padding-top: 12px;'>Operations Dashboard</h1>",
        unsafe_allow_html=True
    )

# ── DRILL-DOWN DETAIL PAGE ───────────────────────────────────────────────
# If this tab was opened via a KPI's "?view=..." link, render only the
# relevant source data and stop — don't build the rest of the dashboard.
_view = st.query_params.get("view", None)
if _view:
    render_detail_page(_view)
    st.stop()

st_autorefresh(
    interval=REFRESH_INTERVAL_SECONDS * 1000,
    key="refresh"
)

month_options = get_month_options()
default_index = 0

filter1, filter2, filter3, filter_spacer = st.columns([2, 2, 1, 4])

with filter1:
    selected_month = st.selectbox(
        "Month Filter",
        month_options,
        index=default_index
    )

with filter2:
    selected_unit = st.selectbox(
        "Unit",
        ["Both", "Unit 1", "Unit 2"]
    )

with filter3:
    st.markdown("""
        <div style="height:28px;"></div>
        <a href="https://mgaproduction.mgdashboard.tech/" target="_blank" class="dept-wise-btn">Dept Wise</a>
    """, unsafe_allow_html=True)

cts_df = shared_state["cts_df"]
oql_df = shared_state["oql_df"]
supply_df = shared_state["supply_df"]

filtered_cts = cts_df
filtered_oql = oql_df
filtered_supply = supply_df

if selected_month != "All":
    selected_period = pd.Period(
        datetime.strptime(selected_month, "%b-%y"),
        freq="M"
    )

    if cts_df is not None:
        filtered_cts = cts_df[
            cts_df["last_ship_date"].dt.to_period("M") == selected_period
        ]

    if oql_df is not None:
        filtered_oql = oql_df[
            oql_df["audit_date"].dt.to_period("M") == selected_period
        ]

    if supply_df is not None:
        filtered_supply = supply_df[
            supply_df["dispatch_date"].dt.to_period("M") == selected_period
        ]

cts_value = calculate_cts(filtered_cts)
first_pass_ratio = calculate_first_pass_ratio(filtered_oql)
till_date_dispatch = calculate_till_date_dispatch(filtered_supply)

# ── Pre-compute all values needed across rows ──────────────────────────────
cts_color = get_cts_color(cts_value)
fpr_color  = get_fpr_color(first_pass_ratio)

dispatch_target = get_dispatch_target()
if dispatch_target is None:
    dispatch_color = "#808080"
elif till_date_dispatch >= dispatch_target:
    dispatch_color = "#1F6437"
else:
    dispatch_color = "#D64550"

b2, leftover, sample = calculate_b2_metrics(
    shared_state["b2_metrics"],
    selected_month
)

dhu_metrics = shared_state.get("dhu_metrics")
dhu1, dhu2, both = dhu_metrics if dhu_metrics else (0, 0, 0)

earned, plan, percent, variance = get_minutes_variance(selected_month, selected_unit)
donut_fill    = min(percent, 100)
percent_color = get_mv_percent_color(percent)
variance_color = get_variance_color(variance)

mtd_df = get_mtd_backlog(selected_unit)

otp_val   = shared_state["otp"]  or 0
otif_val  = shared_state["otif"] or 0
otp_color  = get_otp_color(otp_val)
otif_color = get_otif_color(otif_val)

wip_chart_df = calculate_wip(shared_state["wip_df"])
wip_targets  = load_wip_targets()

dept_df   = get_dept_efficiency(selected_month, selected_unit)
color_map = {}
targets_df = None
if shared_state["dept_efficiency"] and "targets" in shared_state["dept_efficiency"]:
    targets_df = shared_state["dept_efficiency"]["targets"]
if not dept_df.empty:
    for _, row in dept_df.iterrows():
        color_map[row["Department"]] = get_target_efficiency_color(
            row["Department"], row["Efficiency"], selected_unit, selected_month, targets_df
        )

# ── Shared style constants ──────────────────────────────────────────────────
HDR  = "font-size:14px; font-weight:700; color:#31333F;"          # section label
VAL  = "font-size:16px; font-weight:700;"                          # KPI value base
CELL = "padding:4px 0; text-align:center;"                         # metric cell
CARD = "border:1px solid #e6e9ef; border-radius:8px; padding:10px 14px; height:100%;"

# ── Global CSS injected once ─────────────────────────────────────────────────
st.markdown("""
<style>
.kpi-card { border:1px solid #e6e9ef; border-radius:8px; padding:10px 14px; }
.kpi-hdr  { font-size:14px; font-weight:700; color:#31333F; margin-bottom:6px; }
.kpi-hdr-link {
    font-size:14px; font-weight:700; color:#31333F; margin-bottom:6px;
    text-decoration:none; display:inline-block; cursor:pointer;
}
.kpi-hdr-link:hover { color:#0d6efd; text-decoration:underline; }
.kpi-val  { font-size:16px; font-weight:700; }
.mtd-table { width:100%; border-collapse:collapse; font-family:sans-serif; font-size:11px; }
.mtd-table th { background:#f0f2f6; color:#31333F; font-weight:700;
                padding:5px 8px; text-align:left; border-bottom:2px solid #e6e9ef; font-size:11px; }
.mtd-table td { padding:5px 8px; border-bottom:1px solid #e6e9ef; color:#31333F; font-size:11px; }
.mtd-table tr:hover { background:#f8f9fa; }
/* remove default plotly top padding inside st columns */
div[data-testid="stPlotlyChart"] { margin-top:0 !important; padding-top:0 !important; }
.dept-wise-btn {
    display:flex;
    align-items:center;
    justify-content:center;
    background:#f0f2f6;
    color:#31333F !important;
    font-weight:500;
    font-size:14px;
    border:1px solid #e6e9ef;
    border-radius:8px;
    padding:0 16px;
    height:44px;
    text-decoration:none !important;
    white-space:nowrap;
}
.dept-wise-btn:hover {
    background:#e2e5ea;
    text-decoration:none !important;
    color:#31333F !important;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# ROW 1 ── MTD Backlog  |  Minutes & Variance  |  Dept Wise Efficiency
# ═══════════════════════════════════════════════════════════════════════════
row1_col1, row1_col2, row1_col3 = st.columns([1, 1, 1], gap="small")

# ── ROW 1 COL 1 : MTD Backlog ──────────────────────────────────────────────
with row1_col1:
    st.markdown(
        '<a href="?view=mtd_backlog" target="_blank" class="kpi-hdr-link">MTD Backlog</a>',
        unsafe_allow_html=True
    )
    if not mtd_df.empty:
        html_table = mtd_df.to_html(index=False, escape=False).replace('\n', ' ')
        html_table = (html_table
            .replace('border="1" class="dataframe"', 'class="mtd-table"')
            .replace('class="dataframe"', 'class="mtd-table"'))
        st.markdown(html_table, unsafe_allow_html=True)

# ── ROW 1 COL 2 : Minutes & Variance ──────────────────────────────────────
with row1_col2:
    st.markdown(
        '<a href="?view=minutes_variance" target="_blank" class="kpi-hdr-link">Minutes &amp; Variance</a>',
        unsafe_allow_html=True
    )

    mv1, mv2, mv3, mv4 = st.columns([1, 1.2, 1, 1], gap="small")

    with mv1:
        st.markdown(f"""
            <div style="{CELL} text-align:left; padding-top:30px;">
                <div style="{HDR}">Earned</div>
                <div style="{VAL} color:#31333F;">{format_number(earned)}</div>
            </div>
        """, unsafe_allow_html=True)

    with mv2:
        fig_mv = go.Figure(go.Pie(
            values=[donut_fill, 100 - donut_fill],
            hole=0.70, textinfo="none",
            marker=dict(colors=[percent_color, "#d9d9d9"])
        ))
        fig_mv.update_layout(
            height=130, showlegend=False,
            annotations=[dict(text=f"<b>{percent:.0f}%</b>", x=0.5, y=0.5,
                              font=dict(size=16, color=percent_color), showarrow=False)],
            margin=dict(t=4, b=4, l=4, r=4)
        )
        st.plotly_chart(fig_mv, width="stretch")

    with mv3:
        st.markdown(f"""
            <div style="{CELL} text-align:left; padding-top:30px;">
                <div style="{HDR}">Plan Available</div>
                <div style="{VAL} color:#31333F;">{format_number(plan)}</div>
            </div>
        """, unsafe_allow_html=True)

    with mv4:
        st.markdown(f"""
            <div style="{CELL} text-align:left; padding-top:30px;">
                <div style="{HDR}">Variance</div>
                <div style="{VAL} color:{variance_color};">{format_number(variance)}</div>
            </div>
        """, unsafe_allow_html=True)

# ── ROW 1 COL 3 : Dept Wise Efficiency ────────────────────────────────────
with row1_col3:
    st.markdown(
        '<a href="?view=dept_efficiency" target="_blank" class="kpi-hdr-link">Dept Wise Efficiency</a>',
        unsafe_allow_html=True
    )
    if not dept_df.empty:
        fig_dept = px.bar(
            dept_df, x="Efficiency", y="Department", orientation="h",
            text="Efficiency", color="Department", color_discrete_map=color_map,
            category_orders={"Department": ["CUTTING", "STITCHING", "WASHING", "FINISHING"]}
        )
        fig_dept.update_traces(
            texttemplate="<b>%{text:.2f}%</b>",
            textposition="outside",
            textfont=dict(size=10)
        )
        fig_dept.update_layout(
            height=180, showlegend=False,
            xaxis=dict(visible=False, range=[0, dept_df["Efficiency"].max() * 1.25]),
            yaxis=dict(title="", tickfont=dict(size=10, family="Arial Black")),
            margin=dict(t=4, b=4, l=0, r=40)
        )
        st.plotly_chart(fig_dept, width="stretch")

st.markdown("<hr style='margin:6px 0; border:none; border-top:1px solid #e6e9ef;'>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# ROW 2 ── Till Date Dispatch  |  CTS  |  B2% + DHU
# ═══════════════════════════════════════════════════════════════════════════
row2_col1, row2_col2, row2_col3 = st.columns([1, 1, 1], gap="small")

# ── ROW 2 COL 1 : Till Date Dispatch ──────────────────────────────────────
with row2_col1:
    st.markdown(
        '<a href="?view=till_date_dispatch" target="_blank" class="kpi-hdr-link">Till Date Dispatch</a>',
        unsafe_allow_html=True
    )
    st.markdown(f"""
        <div style="{VAL} font-size:36px; color:{dispatch_color};">{format_number(till_date_dispatch)}</div>
    """, unsafe_allow_html=True)

# ── ROW 2 COL 2 : CTS ─────────────────────────────────────────────────────
with row2_col2:
    st.markdown(
        '<a href="?view=cts" target="_blank" class="kpi-hdr-link">CTS %</a>',
        unsafe_allow_html=True
    )
    st.markdown(f"""
        <div style="{VAL} font-size:36px; color:{cts_color};">{cts_value:.2f}%</div>
    """, unsafe_allow_html=True)

# ── ROW 2 COL 3 : B2% + DHU ───────────────────────────────────────────────
with row2_col3:
    st.markdown(
        '<a href="?view=b2_dhu" target="_blank" class="kpi-hdr-link">B2%</a>',
        unsafe_allow_html=True
    )
    st.markdown(f"""
        <div style="display:flex; gap:8px; margin-bottom:10px;">
            <div style="flex:1; {CELL}">
                <div style="{HDR}">B2</div>
                <div style="{VAL} color:{cts_color};">{b2:.2f}%</div>
            </div>
            <div style="flex:1; {CELL}">
                <div style="{HDR}">Leftover</div>
                <div style="{VAL} color:{cts_color};">{leftover:.2f}%</div>
            </div>
            <div style="flex:1; {CELL}">
                <div style="{HDR}">Sample</div>
                <div style="{VAL} color:{cts_color};">{sample:.2f}%</div>
            </div>
        </div>
        <div class="kpi-hdr" style="margin-top:4px;">DHU</div>
        <div style="display:flex; gap:8px;">
            <div style="flex:1; {CELL}">
                <div style="{HDR}">Unit 1</div>
                <div style="{VAL} color:{get_dhu_color(dhu1)};">{dhu1:.2f}%</div>
            </div>
            <div style="flex:1; {CELL}">
                <div style="{HDR}">Unit 2</div>
                <div style="{VAL} color:{get_dhu_color(dhu2)};">{dhu2:.2f}%</div>
            </div>
            <div style="flex:1; {CELL}">
                <div style="{HDR}">Both</div>
                <div style="{VAL} color:{get_dhu_color(both)};">{both:.2f}%</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<hr style='margin:6px 0; border:none; border-top:1px solid #e6e9ef;'>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════
# ROW 3 ── OTP + Dispatch OTIF  |  WIP  |  First Pass Ratio
# ═══════════════════════════════════════════════════════════════════════════
row3_col1, row3_col2, row3_col3 = st.columns([1, 1, 1], gap="small")

# ── ROW 3 COL 1 : OTP + Dispatch OTIF gauges ──────────────────────────────
with row3_col1:
    st.markdown(
        '<a href="https://metis-mg.com/apparel/dashboards/tna" target="_blank" class="kpi-hdr-link">OTP / Dispatch OTIF</a>',
        unsafe_allow_html=True
    )
    g1, g2 = st.columns(2, gap="small")

    with g1:
        fig_otp = go.Figure(go.Indicator(
            mode="gauge+number", value=otp_val,
            number={"suffix": "%", "font": {"size": 20, "color": otp_color}},
            title={"text": "<b>OTP</b>", "font": {"size": 15}},
            gauge={"axis": {"range": [0, 100], "tickfont": {"size": 9}},
                   "bar": {"color": otp_color},
                   "bgcolor": "white",
                   "borderwidth": 1}
        ))
        fig_otp.update_layout(height=160, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_otp, width="stretch")

    with g2:
        fig_otif = go.Figure(go.Indicator(
            mode="gauge+number", value=otif_val,
            number={"suffix": "%", "font": {"size": 20, "color": otif_color}},
            title={"text": "<b>Dispatch OTIF</b>", "font": {"size": 15}},
            gauge={"axis": {"range": [0, 100], "tickfont": {"size": 9}},
                   "bar": {"color": otif_color},
                   "bgcolor": "white",
                   "borderwidth": 1}
        ))
        fig_otif.update_layout(height=160, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_otif, width="stretch")

# ── ROW 3 COL 2 : WIP ─────────────────────────────────────────────────────
with row3_col2:
    st.markdown(
        '<a href="?view=wip" target="_blank" class="kpi-hdr-link">WIP</a>',
        unsafe_allow_html=True
    )
    if not wip_chart_df.empty:
        wip_chart_df["Color"] = wip_chart_df.apply(
            lambda row: get_wip_color(row["Value"], wip_targets.get(row["Process"])), axis=1
        )
        fig_wip = px.bar(
            wip_chart_df, x="Process", y="Value", text="Value", color="Process",
            color_discrete_map={r["Process"]: r["Color"] for _, r in wip_chart_df.iterrows()}
        )
        fig_wip.update_traces(
            texttemplate="<b>%{text:,.0f}</b>",
            textposition="outside",
            textfont=dict(size=10)
        )
        fig_wip.update_layout(
            height=220, showlegend=False,
            xaxis=dict(title="", tickfont=dict(size=10, family="Arial Black")),
            yaxis=dict(title="", tickfont=dict(size=10), range=[0, wip_chart_df["Value"].max() * 1.25]),
            margin=dict(t=20, b=10, l=0, r=10)
        )
        st.plotly_chart(fig_wip, width="stretch")

# ── ROW 3 COL 3 : First Pass Ratio ────────────────────────────────────────
with row3_col3:
    st.markdown(
        '<a href="?view=first_pass_ratio" target="_blank" class="kpi-hdr-link">First Pass Ratio</a>',
        unsafe_allow_html=True
    )
    st.markdown(f"""
        <div style="{VAL} font-size:36px; color:{fpr_color};">{first_pass_ratio:.2f}%</div>
    """, unsafe_allow_html=True)
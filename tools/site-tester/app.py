"""
Website Health & Load Tester
============================

A GUI tool to make sure YOUR OWN website doesn't break when it goes live:

  • Load test   — fire many concurrent visitors at each URL and measure how it
                  holds up (status codes, latency p50/p95/max, errors, req/s).
  • Page health — open each page in a real headless browser and catch the
                  things that actually break for users: JavaScript errors,
                  broken images, failed network requests, slow loads — plus a
                  screenshot so you can eyeball it.

Run it:
    pip install -r requirements.txt
    streamlit run site_tester.py

Or upload it as a panel project dashboard (it's a normal Streamlit app).

Targets you enter can be saved to targets.txt; tick "Auto-run" and it runs
itself as soon as the dashboard opens.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

TARGETS_FILE = Path(__file__).with_name("targets.txt")

st.set_page_config(page_title="Site Health & Load Tester", page_icon="🩺",
                   layout="wide")


# ---------------------------------------------------------------------------
# Load test (HTTP level — fast, no browser, the right way to measure capacity)
# ---------------------------------------------------------------------------
async def _hit(client, url, sem, out):
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.get(url, follow_redirects=True)
            out.append((url, r.status_code, (time.perf_counter() - t0) * 1000, None))
        except Exception as exc:  # noqa: BLE001 — record any failure
            out.append((url, None, (time.perf_counter() - t0) * 1000,
                        type(exc).__name__))


async def run_load(urls, concurrency, per_url, timeout, verify):
    sem = asyncio.Semaphore(concurrency)
    out: list[tuple] = []
    limits = httpx.Limits(max_connections=concurrency,
                          max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, verify=verify,
                                 limits=limits,
                                 headers={"User-Agent": "SiteTester/1.0"}) as client:
        tasks = [_hit(client, u, sem, out) for u in urls for _ in range(per_url)]
        t0 = time.perf_counter()
        await asyncio.gather(*tasks)
        wall = time.perf_counter() - t0
    return out, wall


def summarize(urls, results, wall):
    rows = []
    for url in urls:
        sub = [r for r in results if r[0] == url]
        lat = sorted(r[2] for r in sub)
        ok = [r for r in sub if r[1] and 200 <= r[1] < 400]
        errs = len(sub) - len(ok)

        def pct(p):
            if not lat:
                return 0.0
            return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1)

        rows.append({
            "URL": url,
            "Requests": len(sub),
            "OK": len(ok),
            "Errors": errs,
            "Avg ms": round(statistics.mean(lat), 1) if lat else 0,
            "p95 ms": pct(0.95),
            "Max ms": round(max(lat), 1) if lat else 0,
        })
    df = pd.DataFrame(rows)
    rps = round(len(results) / wall, 1) if wall else 0
    return df, rps, sum(r["Errors"] for r in rows)


# ---------------------------------------------------------------------------
# Page health (real headless browser — catches what users actually see break)
# ---------------------------------------------------------------------------
def check_page(url, screenshot=True, wait=2.0, timeout=40):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1366,900"):
        opts.add_argument(arg)
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    res = {"url": url, "ok": False}
    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(timeout)
        t0 = time.perf_counter()
        driver.get(url)
        time.sleep(wait)  # let late JS / images settle
        res["load_ms"] = round((time.perf_counter() - t0) * 1000)
        res["title"] = driver.title or "(no title)"

        # JavaScript console errors
        try:
            logs = driver.get_log("browser")
            res["console_errors"] = [l["message"] for l in logs
                                     if l.get("level") == "SEVERE"]
        except Exception:
            res["console_errors"] = []

        # Broken images (loaded but 0×0 / failed)
        try:
            res["broken_images"] = driver.execute_script(
                "return Array.from(document.images)"
                ".filter(i => !i.complete || i.naturalWidth === 0)"
                ".map(i => i.currentSrc || i.src);") or []
        except Exception:
            res["broken_images"] = []

        if screenshot:
            res["png"] = driver.get_screenshot_as_png()

        res["ok"] = not res["console_errors"] and not res["broken_images"]
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return res


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🩺 Website Health & Load Tester")
st.caption("Test **your own** site before real users hit it — find breakage and "
           "see how it holds up under load.")

default_urls = TARGETS_FILE.read_text(encoding="utf-8") if TARGETS_FILE.exists() else ""

with st.sidebar:
    st.header("Targets")
    urls_text = st.text_area("URLs (one per line)", value=default_urls, height=150,
                             placeholder="https://yoursite.com\nhttps://yoursite.com/shop")
    if st.button("💾 Save targets"):
        TARGETS_FILE.write_text(urls_text, encoding="utf-8")
        st.success("Saved to targets.txt")

    st.header("Load test")
    do_load = st.checkbox("Run load test", value=True)
    concurrency = st.slider("Concurrent visitors", 1, 200, 20,
                            help="How many requests hit the site at the same time "
                                 "(your old 'number of tabs').")
    per_url = st.slider("Visits per URL", 1, 1000, 50)
    timeout = st.number_input("Request timeout (s)", 1, 120, 15)
    verify = st.checkbox("Verify SSL", value=True,
                         help="Uncheck for a staging server with a self-signed cert.")

    st.header("Page health")
    do_browser = st.checkbox("Run browser render check", value=True)
    do_shots = st.checkbox("Capture screenshots", value=True)

    st.header("Automation")
    autorun = st.checkbox("Auto-run on open (if targets saved)", value=False)

urls = [u.strip() for u in urls_text.splitlines() if u.strip()]

run = st.button("▶ Run tests", type="primary")
if autorun and urls and not st.session_state.get("auto_done"):
    st.session_state["auto_done"] = True
    run = True

if run:
    if not urls:
        st.error("Add at least one URL in the sidebar.")
        st.stop()

    # --- Load test ---
    if do_load:
        st.subheader("⚡ Load test")
        st.write(f"Sending **{concurrency}** concurrent visitors · "
                 f"**{per_url}** visits each · **{len(urls)}** URL(s) = "
                 f"**{per_url * len(urls)}** total requests.")
        with st.spinner("Load testing…"):
            results, wall = asyncio.run(
                run_load(urls, concurrency, per_url, timeout, verify))
        df, rps, total_errors = summarize(urls, results, wall)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total requests", len(results))
        c2.metric("Throughput", f"{rps} req/s")
        c3.metric("Failed", total_errors)
        st.dataframe(df, use_container_width=True, hide_index=True)

        if total_errors:
            st.error(f"❌ {total_errors} request(s) failed under {concurrency} "
                     "concurrent visitors — your site drops/errors at this load. "
                     "Lower the concurrency to find where it starts to break.")
        else:
            st.success("✅ No failed requests at this load.")
        slow = df[df["p95 ms"] > 1000]
        if not slow.empty:
            st.warning("🐢 Some pages are slow (p95 over 1s): "
                       + ", ".join(slow["URL"]))

    # --- Page health ---
    if do_browser:
        st.subheader("🔍 Page health (real browser)")
        progress = st.progress(0.0)
        for i, url in enumerate(urls, 1):
            with st.spinner(f"Rendering {url} …"):
                res = check_page(url, screenshot=do_shots)
            progress.progress(i / len(urls))

            ok = res.get("ok")
            with st.expander(f"{'✅' if ok else '⚠️'}  {url}", expanded=not ok):
                if "error" in res:
                    st.error(f"Could not load: {res['error']}")
                else:
                    a, b = st.columns(2)
                    a.metric("Load time", f"{res.get('load_ms', 0)} ms")
                    b.write(f"**Title:** {res.get('title', '')}")
                    if res.get("console_errors"):
                        st.error("JavaScript errors:")
                        for e in res["console_errors"][:20]:
                            st.code(e, language="text")
                    if res.get("broken_images"):
                        st.warning("Broken images:")
                        for img in res["broken_images"][:20]:
                            st.write(f"• {img}")
                    if not res.get("console_errors") and not res.get("broken_images"):
                        st.success("No JS errors, no broken images.")
                if res.get("png"):
                    st.image(res["png"], caption="Rendered page",
                             use_container_width=True)
        progress.empty()

    st.toast("Done", icon="✅")
else:
    st.info("Add your URLs in the sidebar and press **Run tests**. "
            "Tip: save targets + tick *Auto-run* to have it run on open.")

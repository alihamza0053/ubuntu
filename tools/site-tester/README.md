# Website Health & Load Tester

A GUI tool to make sure **your own** website doesn't break when real users hit
it. Two checks in one dashboard:

| Check | What it answers | How |
|---|---|---|
| **Load test** | "Does it stay up and fast under many visitors at once?" | Fires N concurrent requests at each URL, measures status codes, latency (avg / p95 / max), errors and throughput (req/s). |
| **Page health** | "Does the page actually render correctly for a person?" | Opens each URL in a real headless Chrome and reports JavaScript errors, broken images, load time, and a screenshot. |

This is the proper replacement for "open the link in lots of tabs and scroll/click
randomly" — it gives you **measurable answers** (where it starts to fail, which
pages are slow, what's broken) instead of just generating traffic.

## How your idea maps to this tool
| Your idea | Here it is |
|---|---|
| How many tabs of the link | **Concurrent visitors** (load) + **Visits per URL** |
| Open incognito / normal | Not needed — each load request is a fresh, cookie-less session by design |
| Random scroll on each tab | **Page health** loads & settles each page, then checks it really rendered |
| Random click on each tab | Replaced by real checks: JS errors, broken images, failed loads |
| Run automatically if data added | Save targets + tick **Auto-run on open** |

sudo bash /opt/serverhub-src/deploy/dashboard-venv.sh url-script httpx selenium


## Run it locally
```bash
pip install -r requirements.txt
streamlit run site_tester.py
```
Open http://localhost:8501, paste your URLs, press **Run tests**.
(The Page-health check needs Google Chrome installed locally.)

## Run it on the panel (recommended — Chrome is already there)
1. In the panel, create a project (e.g. `sitetest`).
2. Upload `site_tester.py` into the project's **dashboard** folder and
   `requirements.txt` alongside it.
3. Start the dashboard from the panel — it runs as a normal Streamlit app on
   its assigned port, and you can assign a domain to it like any other.

## Reading the results
- **Errors > 0** in the load test → your site drops/errors at that concurrency.
  Lower "Concurrent visitors" until errors hit 0 to find your safe ceiling.
- **p95 over 1s** → those pages are slow under load; optimise them.
- **JS errors / broken images** in Page health → real breakage a visitor sees;
  the screenshot shows you exactly what.

## Be a good neighbour
Only point this at sites you own or are authorised to test. High concurrency is
real load — start small (10–20) and increase. On shared hosting, heavy load can
trip abuse limits, so test a staging copy when you can.

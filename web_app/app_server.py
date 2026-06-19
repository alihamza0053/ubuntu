import os
import sys
import json
import time
import random
import threading
import platform
import subprocess
import tempfile
import signal
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Selenium -------------------------------------------------------------
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# --- App Directories ------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if os.environ.get("IS_DOCKER") == "true" or PARENT_DIR == "/":
    CONFIG_FILE = os.path.join(BASE_DIR, "browser_config.json")
    HISTORY_FILE = os.path.join(BASE_DIR, "browser_history.json")
else:
    CONFIG_FILE = os.path.join(PARENT_DIR, "browser_config.json")
    HISTORY_FILE = os.path.join(PARENT_DIR, "browser_history.json")


STATIC_DIR = os.path.join(BASE_DIR, "static")
SCREENSHOTS_DIR = os.path.join(STATIC_DIR, "screenshots")

# Ensure directories exist
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# --- Default Config -------------------------------------------------------
DEFAULT_CONFIG = {
    "links": [
        "https://southcore.digital/quantum-computing-qubits-status-2026/",
        "https://southcore.digital/quantum-sensing-next-gen-metrology/",
        "https://southcore.digital/zero-trust-architecture-microsegmentation/",
        "https://southcore.digital/fully-homomorphic-encryption-data-privacy/",
        "https://southcore.digital/securing-software-supply-chain-dependencies/",
        "https://southcore.digital/self-sovereign-identity-decentralized-id/",
        "https://southcore.digital/ai-vs-ai-autonomous-cyber-threats-defense/",
        "https://southcore.digital/serverless-databases-autoscaling-cloud/",
        "https://southcore.digital/edge-computing-6g-smart-cities/",
        "https://southcore.digital/webassembly-on-server-wasm-docker-alternative/"
    ],
    "num_tabs": 1,
    "incognito": True,
    "randomize_order": False,
    "random_scroll": True,
    "random_click": True,
    "delay_after_scroll": 2.0,
    "auto_close": True,
    "close_after_seconds": 5,
    "capture_screenshots": True,
    "use_selenium": True,
    "screenshots_dir": SCREENSHOTS_DIR,
    "action_delay": 2.0,
}

# --- State Management ----------------------------------------------------
class RunStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.status = "idle"  # idle, running
        self.total_tabs = 0
        self.completed_tabs = 0
        self.current_url = ""
        self.logs: List[str] = []
        self.session_id = ""
        self.stop_requested = False
        self.active_drivers: List[Any] = []

    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line, flush=True)
        with self.lock:
            self.logs.append(log_line)

    def update_progress(self, completed: int, total: int, current_url: str):
        with self.lock:
            self.completed_tabs = completed
            self.total_tabs = total
            self.current_url = current_url

    def request_stop(self):
        with self.lock:
            self.stop_requested = True
            for driver in self.active_drivers:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.active_drivers.clear()

    def add_driver(self, driver):
        with self.lock:
            self.active_drivers.append(driver)

    def remove_driver(self, driver):
        with self.lock:
            if driver in self.active_drivers:
                self.active_drivers.remove(driver)

runner_state = RunStatus()

# --- Config and History Helpers ------------------------------------------
def load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            # Override screenshots_dir to web app screenshots folder for sanity
            merged["screenshots_dir"] = SCREENSHOTS_DIR
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(config: Dict[str, Any]):
    # Keep screenshots_dir within static screenshots
    config["screenshots_dir"] = SCREENSHOTS_DIR
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_history() -> List[Dict[str, Any]]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history: List[Dict[str, Any]]):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def add_to_history(results: Dict[str, Any]):
    history = load_history()
    history.insert(0, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": results["session_id"],
        "total_links": results["total_links"],
        "total_tabs": results["total_tabs"],
        "successful_tabs": results["successful_tabs"],
        "failed_tabs": results["failed_tabs"],
        "scrolls_performed": results["scrolls_performed"],
        "clicks_performed": results["clicks_performed"],
        "tabs_closed": results["tabs_closed"],
        "screenshots_count": results["screenshots_count"],
        "duration": round(results["duration"], 2),
    })
    save_history(history[:50])  # keep last 50 runs

# --- Selenium Browser Support ---------------------------------------------
def get_chrome_path():
    system = platform.system()
    if system == "Windows":
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         r"Google\Chrome\Application\chrome.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    for path in candidates:
        if path and os.path.exists(path):
            return path

    finder = "where" if system == "Windows" else "which"
    for browser in ["google-chrome", "google-chrome-stable", "chrome",
                    "chromium-browser", "chromium"]:
        try:
            r = subprocess.run([finder, browser], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0].strip()
        except Exception:
            pass
    return None

def build_chrome_driver(incognito=False, headless=True):
    chrome_path = get_chrome_path()
    if not chrome_path:
        raise RuntimeError("Chrome or Chromium browser binary not found on this system.")

    opts = Options()
    opts.binary_location = chrome_path
    if incognito:
        opts.add_argument("--incognito")
    if headless:
        opts.add_argument("--headless=new")
    
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    # Try common server paths
    for cd in ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver",
               "/usr/lib/chromium-browser/chromedriver"]:
        if os.path.exists(cd):
            return webdriver.Chrome(service=Service(executable_path=cd), options=opts)
    
    # Let selenium auto-provision if not found in custom paths
    return webdriver.Chrome(options=opts)

# --- Automation Actions ----------------------------------------------------
def scroll_once(driver, delta):
    try:
        ActionChains(driver).scroll_by_amount(0, delta).perform()
    except Exception:
        pass
    try:
        driver.execute_script(
            "var d=arguments[0];"
            "['wheel','mousewheel','scroll'].forEach(function(t){"
            "window.dispatchEvent(new Event(t,{bubbles:true}));"
            "document.dispatchEvent(new WheelEvent('wheel',{deltaY:d,bubbles:true}));});",
            delta)
    except Exception:
        pass
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", delta)
    except Exception:
        pass

def perform_scrolls(driver) -> int:
    scrolls = 0
    try:
        for _ in range(random.randint(3, 6)):
            if runner_state.stop_requested:
                break
            scroll_once(driver, random.randint(200, 700))
            scrolls += 1
            time.sleep(random.uniform(0.4, 1.0))
        if random.random() < 0.5 and not runner_state.stop_requested:
            scroll_once(driver, -random.randint(400, 900))
            scrolls += 1
            time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass
    return scrolls

def perform_clicks(driver) -> int:
    clicks = 0
    try:
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        
        target = random.randint(1, 3)
        for _ in range(target):
            if runner_state.stop_requested:
                break
            js_find_coords = """
            const getSafeCoordinate = () => {
                const width = window.innerWidth;
                const height = window.innerHeight;
                for (let i = 0; i < 50; i++) {
                    const x = Math.floor(Math.random() * (width * 0.8) + (width * 0.1));
                    const y = Math.floor(Math.random() * (height * 0.8) + (height * 0.1));
                    const el = document.elementFromPoint(x, y);
                    if (!el) continue;
                    
                    let current = el;
                    let isInteractive = false;
                    while (current && current !== document.body && current !== document.documentElement) {
                        const tag = current.tagName.toUpperCase();
                        const role = current.getAttribute('role');
                        const cursor = window.getComputedStyle(current).cursor;
                        if (['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'IFRAME', 'AUDIO', 'VIDEO'].includes(tag) ||
                            role === 'button' || role === 'link' || cursor === 'pointer') {
                            isInteractive = true;
                            break;
                        }
                        current = current.parentElement;
                    }
                    if (!isInteractive) {
                        return { x, y };
                    }
                }
                return { x: Math.floor(width * 0.2), y: Math.floor(height * 0.2) };
            };
            return getSafeCoordinate();
            """
            coords = driver.execute_script(js_find_coords)
            if coords and 'x' in coords and 'y' in coords:
                x, y = coords['x'], coords['y']
                action = ActionBuilder(driver)
                action.pointer_action.move_to_location(x, y)
                action.pointer_action.click()
                action.perform()
                clicks += 1
                time.sleep(random.uniform(0.5, 1.2))
    except Exception:
        pass
    return clicks

# --- Core Run Process -----------------------------------------------------
def run_automation_worker(config: Dict[str, Any]):
    runner_state.add_log(f"Automation worker started. incognito={config['incognito']}, selenium={config['use_selenium']}")
    start_time = time.time()
    
    links = list(config.get("links", []))
    if config.get("randomize_order", False):
        random.shuffle(links)
        runner_state.add_log("Randomized link ordering.")

    num_tabs = int(config.get("num_tabs", 1))
    total_tabs = len(links) * num_tabs
    session_id = runner_state.session_id
    session_folder = os.path.join(SCREENSHOTS_DIR, session_id)
    os.makedirs(session_folder, exist_ok=True)

    results = {
        "session_id": session_id,
        "total_links": len(links),
        "total_tabs": total_tabs,
        "successful_tabs": 0,
        "failed_tabs": 0,
        "scrolls_performed": 0,
        "clicks_performed": 0,
        "tabs_closed": bool(config.get("auto_close", True)),
        "screenshots_count": 0,
        "duration": 0.0
    }

    if not SELENIUM_AVAILABLE:
        runner_state.add_log("ERROR: Selenium is not installed on the server. Worker aborting.")
        with runner_state.lock:
            runner_state.status = "idle"
        return

    completed = 0
    for link in links:
        if runner_state.stop_requested:
            runner_state.add_log("Stop requested by user. Aborting remaining tabs.")
            break

        for tab in range(num_tabs):
            if runner_state.stop_requested:
                break
            
            completed += 1
            runner_state.update_progress(completed, total_tabs, link)
            runner_state.add_log(f"Processing Tab {completed}/{total_tabs}: {link}")

            shot_name = f"tab{tab+1}_{datetime.now().strftime('%H%M%S_%f')}.png"
            shot_path = os.path.join(session_folder, shot_name)

            driver = None
            try:
                # Always runs in headless mode inside standard web deployments unless specified
                driver = build_chrome_driver(
                    incognito=config.get("incognito", False),
                    headless=True # Keep headless on web deployment
                )
                runner_state.add_driver(driver)
                driver.set_page_load_timeout(30)
                
                # Navigate
                driver.get(link)
                
                # Wait body loaded
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )
                except Exception:
                    pass
                
                # Delay before scrolling/clicking
                action_delay = float(config.get("action_delay", 2.0))
                time.sleep(max(0.0, action_delay))

                # Scroll
                scrolls = 0
                if config.get("random_scroll", True) and not runner_state.stop_requested:
                    scrolls = perform_scrolls(driver)
                    results["scrolls_performed"] += scrolls

                # Click
                clicks = 0
                if config.get("random_click", True) and not runner_state.stop_requested:
                    if scrolls > 0:
                        time.sleep(float(config.get("delay_after_scroll", 2.0)))
                    clicks = perform_clicks(driver)
                    results["clicks_performed"] += clicks
                    
                    # Refocus latest handle if tab opened
                    try:
                        if driver.window_handles:
                            driver.switch_to.window(driver.window_handles[-1])
                    except Exception:
                        pass

                # Capture Screenshot
                shot_saved = False
                if config.get("capture_screenshots", True) and not runner_state.stop_requested:
                    try:
                        driver.switch_to.alert.dismiss()
                    except Exception:
                        pass
                    driver.save_screenshot(shot_path)
                    shot_saved = os.path.exists(shot_path)
                    if shot_saved:
                        results["screenshots_count"] += 1

                # Auto close delay
                if config.get("auto_close", True) and not runner_state.stop_requested:
                    close_after = int(config.get("close_after_seconds", 5))
                    runner_state.add_log(f"  Holding tab open for {close_after}s...")
                    time.sleep(close_after)

                results["successful_tabs"] += 1
                runner_state.add_log(f"  OK | scrolls={scrolls}, clicks={clicks}, screenshot={shot_saved}")

            except Exception as e:
                results["failed_tabs"] += 1
                runner_state.add_log(f"  FAILED | error: {str(e)}")
            finally:
                if driver:
                    runner_state.remove_driver(driver)
                    try:
                        driver.quit()
                    except Exception:
                        pass

            time.sleep(0.5)

    results["duration"] = time.time() - start_time
    runner_state.add_log(f"Job finished in {results['duration']:.1f}s | Success={results['successful_tabs']}, Failed={results['failed_tabs']}")
    
    if not runner_state.stop_requested:
        add_to_history(results)

    with runner_state.lock:
        runner_state.status = "idle"
        runner_state.active_drivers.clear()

# --- API Definitions ------------------------------------------------------
app = FastAPI(title="Browser Automation Dashboard")

# Enable CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConfigModel(BaseModel):
    links: List[str]
    num_tabs: int
    incognito: bool
    randomize_order: bool
    random_scroll: bool
    random_click: bool
    delay_after_scroll: float
    auto_close: bool
    close_after_seconds: int
    capture_screenshots: bool
    use_selenium: bool
    action_delay: float

@app.get("/api/config")
def get_config():
    return load_config()

@app.post("/api/config")
def update_config(config: ConfigModel):
    cfg_dict = config.dict()
    save_config(cfg_dict)
    return {"status": "success", "message": "Config saved successfully"}

@app.get("/api/history")
def get_history():
    return load_history()

@app.get("/api/status")
def get_status():
    with runner_state.lock:
        return {
            "status": runner_state.status,
            "total_tabs": runner_state.total_tabs,
            "completed_tabs": runner_state.completed_tabs,
            "current_url": runner_state.current_url,
            "session_id": runner_state.session_id,
            "logs": runner_state.logs[-100:]  # Send last 100 logs
        }

@app.post("/api/run")
def trigger_run(background_tasks: BackgroundTasks):
    with runner_state.lock:
        if runner_state.status == "running":
            raise HTTPException(status_code=400, detail="Automation is already running")
        
        runner_state.reset()
        runner_state.status = "running"
        runner_state.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
    config = load_config()
    background_tasks.add_task(run_automation_worker, config)
    return {"status": "success", "session_id": runner_state.session_id}

@app.post("/api/stop")
def stop_run():
    if runner_state.status != "running":
        return {"status": "info", "message": "Automation is not running"}
    runner_state.request_stop()
    runner_state.add_log("Cancel request received. Stopping Chrome drivers...")
    return {"status": "success", "message": "Stop request submitted"}

@app.get("/api/screenshots")
def get_screenshots():
    """List all captured sessions and screenshots."""
    if not os.path.exists(SCREENSHOTS_DIR):
        return []
    
    sessions = []
    try:
        # List subdirectories (each directory is a session)
        for sdir in sorted(os.listdir(SCREENSHOTS_DIR), reverse=True):
            sdir_path = os.path.join(SCREENSHOTS_DIR, sdir)
            if os.path.isdir(sdir_path):
                files = []
                for fname in sorted(os.listdir(sdir_path)):
                    if fname.endswith(".png"):
                        # Relative URL path for frontend
                        files.append(f"/screenshots/{sdir}/{fname}")
                if files:
                    sessions.append({
                        "session_id": sdir,
                        "screenshots": files
                    })
    except Exception as e:
        print(f"Error reading screenshots directory: {e}")
    
    return sessions

# Serve static frontend files
# Note: we also mount screenshots directory inside static files so they are accessible
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # If run directly, launch uvicorn
    print("Starting server on http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)

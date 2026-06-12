"""
P2P Custom — Oracle FSCM Analytics report downloader (server-ready).

Runs headless on the ServerHub Ubuntu VPS. Tested to run from:
  - the panel Terminal page, or
  - a project's Scripts tab (Run Now / scheduled).

See SCRIPTS_GUIDE.md for setup, scheduling and troubleshooting.
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
import time
import os
import shutil

# -------------------------------
# Download directory
# -------------------------------
# Must be writable by the panel's `serverhub` user. The project's data/ folder
# is the right place (it also shows up in the project's "Data Files" tab).
# Override with the DOWNLOAD_DIR env var if you like.
download_dir = os.getenv(
    "DOWNLOAD_DIR",
    "/srv/projects/p2p_custom/data/nazir_manzoor",
)
os.makedirs(download_dir, exist_ok=True)

# -------------------------------
# Credentials (prefer environment variables over hard-coding)
# Set these in the shell/panel before running, e.g.:
#   export ORACLE_USER="HOD.ERP"
#   export ORACLE_PASS="********"
# -------------------------------
ORACLE_USER = os.getenv("ORACLE_USER", "HOD.ERP")
ORACLE_PASS = os.getenv("ORACLE_PASS", "UKMST@123")


# -------------------------------
# Locate the Chromium/Chrome binary and chromedriver on the server
# -------------------------------
def find_first(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


CHROME_BINARY = find_first([
    shutil.which("google-chrome"),
    shutil.which("chromium-browser"),
    shutil.which("chromium"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
])
CHROMEDRIVER = find_first([
    shutil.which("chromedriver"),
    "/usr/bin/chromedriver",
    "/usr/lib/chromium-browser/chromedriver",
])


# -------------------------------
# Clean old downloads
# -------------------------------
def clean_download_folder(download_path):
    target_file = "P2P Custom.xlsx"
    for file in os.listdir(download_path):
        if file == target_file or file.endswith(".crdownload"):
            try:
                os.remove(os.path.join(download_path, file))
                print(f"Deleted: {file}", flush=True)
            except Exception as e:
                print(f"Could not delete {file}: {e}", flush=True)


# -------------------------------
# Wait for download completion
# -------------------------------
def wait_for_new_excel(download_path, timeout=2000):
    before_files = set(os.listdir(download_path))
    seconds = 0
    while seconds < timeout:
        after_files = set(os.listdir(download_path))
        new_files = [
            f for f in after_files - before_files
            if f.endswith((".xlsx", ".xls")) and not f.endswith(".crdownload")
        ]
        if new_files:
            return new_files[0]
        time.sleep(2)
        seconds += 2
    raise TimeoutError("Excel file did not download")


# -------------------------------
# Chrome setup (HEADLESS — required on a server with no display)
# -------------------------------
options = Options()
options.add_argument("--headless=new")           # run without a display
options.add_argument("--no-sandbox")             # required for a service user
options.add_argument("--disable-dev-shm-usage")  # avoid /dev/shm crashes
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")  # so elements render & click

if CHROME_BINARY:
    options.binary_location = CHROME_BINARY

prefs = {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
    # CRITICAL for Oracle Analytics
    "profile.default_content_settings.popups": 0,
    "profile.default_content_setting_values.automatic_downloads": 1,
}
options.add_experimental_option("prefs", prefs)

print(f"Chrome binary : {CHROME_BINARY or 'auto (Selenium Manager)'}", flush=True)
print(f"Chromedriver  : {CHROMEDRIVER or 'auto (Selenium Manager)'}", flush=True)
print(f"Download dir  : {download_dir}", flush=True)

# Build the driver. Use the apt chromedriver if found, else let Selenium
# Manager (Selenium 4.6+) download a matching one automatically.
if CHROMEDRIVER:
    driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=options)
else:
    driver = webdriver.Chrome(options=options)

# Headless Chrome blocks downloads unless we explicitly allow them.
driver.execute_cdp_cmd("Page.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": download_dir,
})

wait = WebDriverWait(driver, 100)
actions = ActionChains(driver)

# Everything runs inside try/finally so the browser is ALWAYS closed —
# otherwise crashed runs leave zombie Chrome processes eating server RAM.
try:
    # -------------------------------
    # Step 1: Open Oracle FSCM URL
    # -------------------------------
    driver.get(
        "https://fa-exeu-saasfaprod1.fa.ocs.oraclecloud.com/analytics/saw.dll?catalog#%7B%22location%22%3A%22%2Fshared%22%7D"
    )

    # -------------------------------
    # Step 2: Login
    # -------------------------------
    username = wait.until(
        EC.presence_of_element_located((By.ID, "idcs-signin-basic-signin-form-username"))
    )
    password = driver.find_element(By.ID, "idcs-signin-basic-signin-form-password|input")
    login_button = driver.find_element(By.ID, "idcs-signin-basic-signin-form-submit")

    username.send_keys(ORACLE_USER)
    time.sleep(1)
    password.send_keys(ORACLE_PASS)
    time.sleep(1)
    login_button.click()

    print("Logged in successfully.", flush=True)
    time.sleep(15)

    # -------------------------------
    # Step 3: Open Analytics Catalog
    # -------------------------------
    driver.get(
        "https://fa-exeu-saasfaprod1.fa.ocs.oraclecloud.com/analytics/saw.dll?catalog#%7B%22location%22%3A%22%2Fshared%22%7D"
    )
    print("Navigated to Analytics Catalog.", flush=True)
    time.sleep(6)
    clean_download_folder(download_dir)

    # -------------------------------
    # Step 4: Click Custom folder
    # -------------------------------
    custom_folder = wait.until(
        EC.presence_of_element_located((
            By.XPATH,
            '//*[@id="idCatalogItemsAccordion"]/div[1]/div[2]/table/tbody/tr[2]/td/div'
        ))
    )
    driver.execute_script("arguments[0].scrollIntoView(true);", custom_folder)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", custom_folder)
    print("Clicked Custom folder", flush=True)
    time.sleep(3)

    # -------------------------------
    # Step 5: Click Expand on Custom
    # -------------------------------
    expand_custom = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            '//*[@id="idCatalogItemsAccordion"]/div[1]/div[2]/table/tbody/tr[2]/td/div/table/tbody/tr[2]/td/table/tbody/tr/td[1]/a'
        ))
    )
    driver.execute_script("arguments[0].click();", expand_custom)
    print("Expanded Custom folder", flush=True)
    time.sleep(4)

    # -------------------------------
    # Step 6: Click Nasir Manzoor folder (row)
    # -------------------------------
    nasir_row = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//*[@id=\"idCatalogItemsAccordion\"]/div[1]/div[2]/table/tbody/tr[25]/td/div"
        ))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nasir_row)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", nasir_row)
    print("Clicked Nasir Manzoor folder", flush=True)
    time.sleep(3)

    # -------------------------------
    # Step 7: Click Expand for Nasir Manzoor
    # -------------------------------
    nasir_expand = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//*[@id=\"idCatalogItemsAccordion\"]/div[1]/div[2]/table/tbody/tr[25]/td/div/table/tbody/tr[2]/td/table/tbody/tr/td[1]/a"
        ))
    )
    driver.execute_script("arguments[0].click();", nasir_expand)
    print("Expanded Nasir Manzoor folder", flush=True)
    time.sleep(4)

    # -------------------------------
    # Step 9: Click Open for P2P Custom
    # -------------------------------
    open_link = wait.until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//*[@id=\"idCatalogItemsAccordion\"]/div[1]/div[2]/table/tbody/tr[19]/td/div/table/tbody/tr[2]/td/table/tbody/tr/td[1]/a"
        ))
    )
    driver.execute_script("arguments[0].click();", open_link)
    print("Opened P2P Custom", flush=True)
    time.sleep(10)

    # -------------------------------
    # Step 10: Wait for report to finish loading
    # -------------------------------
    print("Waiting for report to finish loading...", flush=True)
    export_btn = WebDriverWait(driver, 1800).until(
        EC.element_to_be_clickable((
            By.XPATH,
            "//*[@id='o:portalgo~r:reportLinks']//a[normalize-space()='Export']"
        ))
    )
    print("Report loaded successfully", flush=True)

    # -------------------------------
    # Step 11: Export -> Data -> Excel
    # -------------------------------
    driver.execute_script("arguments[0].click();", export_btn)
    time.sleep(2)

    data_menu = wait.until(
        EC.visibility_of_element_located((By.XPATH, "//td[normalize-space()='Data']"))
    )
    actions.move_to_element(data_menu).perform()
    print("Hovered on Data", flush=True)
    time.sleep(2)

    excel_menu = wait.until(
        EC.presence_of_element_located((By.XPATH, "//td[normalize-space()='Excel']"))
    )
    driver.execute_script("arguments[0].click();", excel_menu)
    print("Clicked Excel export", flush=True)

    # -------------------------------
    # Step 12: Wait for download
    # -------------------------------
    time.sleep(5)
    downloaded_file = wait_for_new_excel(download_dir)
    print(f"Excel downloaded successfully: {downloaded_file}", flush=True)

finally:
    # Always close the browser, even on error/timeout.
    driver.quit()
    print("Browser closed.", flush=True)

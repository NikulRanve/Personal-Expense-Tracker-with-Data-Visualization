"""
scripts/capture_screenshots.py — High-Fidelity CDP Screenshot Generator
======================================================================
Uses Chrome DevTools Protocol to accurately wait for Streamlit WebSocket
rendering and Plotly charts to render completely before taking screenshots.
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from database import initialise_database, seed_categories
from import_service import import_transactions, preview_import
from budget_manager import set_budget

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
IMAGES_DIR = PROJECT_ROOT / "images"
DEMO_DB = PROJECT_ROOT / "data" / "screenshot_temp.db"
DEMO_CSV = PROJECT_ROOT / "data" / "sample" / "demo_transactions.csv"
STREAMLIT_PORT = 8599
CDP_PORT = 9222


def setup_demo_data():
    if DEMO_DB.exists():
        try:
            DEMO_DB.unlink()
        except Exception:
            pass
    initialise_database(DEMO_DB)
    seed_categories(DEMO_DB)
    # Import 38 synthetic transactions
    res = preview_import(DEMO_CSV, db_path=DEMO_DB)
    import_transactions(res, filename="demo_transactions.csv", db_path=DEMO_DB)
    # Set budgets for 2026-11
    set_budget("Food", "2026-11", 12000.0, db_path=DEMO_DB)
    set_budget("Shopping", "2026-11", 8000.0, db_path=DEMO_DB)
    set_budget("Transportation", "2026-11", 5000.0, db_path=DEMO_DB)
    set_budget("Utilities", "2026-11", 4000.0, db_path=DEMO_DB)
    print("Demo DB ready.")


def wait_for_url(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


async def capture_cdp():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    setup_demo_data()

    # 1. Start Streamlit
    env = os.environ.copy()
    home = PROJECT_ROOT / ".home"
    (home / ".streamlit").mkdir(parents=True, exist_ok=True)
    (home / ".streamlit" / "credentials.toml").write_text('[general]\nemail = ""\n')
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["EXPENSE_TRACKER_DB"] = str(DEMO_DB)
    env["STREAMLIT_CREDENTIALS_FILE"] = str(home / ".streamlit" / "credentials.toml")

    streamlit_cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        f"--server.port={STREAMLIT_PORT}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]

    print("Launching Streamlit...")
    st_log = open(PROJECT_ROOT / "scripts" / "server.log", "w", encoding="utf-8")
    st_proc = subprocess.Popen(streamlit_cmd, env=env, cwd=str(PROJECT_ROOT), stdout=st_log, stderr=st_log)

    # 2. Start Headless Chrome with Remote Debugging
    chrome_profile = PROJECT_ROOT / ".home" / "chrome_profile"
    chrome_profile.mkdir(parents=True, exist_ok=True)

    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={chrome_profile}",
        "--window-size=1440,920",
        "--hide-scrollbars",
        "about:blank",
    ]

    print("Launching Chrome CDP...")
    chrome_proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        if not wait_for_url(f"http://127.0.0.1:{STREAMLIT_PORT}/_stcore/health", timeout=25):
            print("Streamlit failed to initialize.")
            return

        if not wait_for_url(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=15):
            print("Chrome CDP failed to initialize.")
            return

        print("Both servers online. Connecting to Chrome page...")
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json") as r:
            targets = json.loads(r.read().decode())
            page_target = [t for t in targets if t.get("type") == "page"][0]
            ws_url = page_target["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as ws:
            pages = [
                ("Dashboard", "01_dashboard.png", 5.0),  # Plotly graphs need ~4-5s
                ("Add Transaction", "02_add_transaction.png", 2.0),
                ("Transactions", "03_transactions.png", 3.0),
                ("Import CSV", "04_import_csv.png", 2.0),
                ("Import History", "05_import_history.png", 2.0),
                ("Budgets", "06_budgets.png", 3.0),
                ("Reports", "07_reports.png", 3.0),
            ]

            msg_id = 0
            for page_name, filename, wait_secs in pages:
                encoded = urllib.parse.quote(page_name)
                url = f"http://127.0.0.1:{STREAMLIT_PORT}/?page={encoded}"
                print(f"Navigating to {page_name} ({url})...")

                msg_id += 1
                await ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Page.navigate",
                    "params": {"url": url}
                }))

                # Wait for render & charts
                await asyncio.sleep(wait_secs)

                # Capture screenshot
                msg_id += 1
                await ws.send(json.dumps({
                    "id": msg_id,
                    "method": "Page.captureScreenshot",
                    "params": {"format": "png"}
                }))

                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    if data.get("id") == msg_id and "result" in data:
                        b64_data = data["result"]["data"]
                        target_file = IMAGES_DIR / filename
                        target_file.write_bytes(base64.b64decode(b64_data))
                        print(f"  Captured {filename} ({target_file.stat().st_size} bytes)")
                        break

        print("All 7 screenshots captured successfully via CDP!")

    finally:
        st_proc.terminate()
        chrome_proc.terminate()
        try:
            st_proc.wait(timeout=5)
        except Exception:
            st_proc.kill()
        try:
            chrome_proc.wait(timeout=5)
        except Exception:
            chrome_proc.kill()
        try:
            st_log.close()
        except Exception:
            pass
        if DEMO_DB.exists():
            try:
                DEMO_DB.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(capture_cdp())

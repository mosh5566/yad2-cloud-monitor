"""
Yad2 Cloud Monitor - Selenium + proxy edition (runs on GitHub Actions).
Uses a real headless Chrome through rotating proxies - the only reliable way
past yad2's Radware bot protection from a datacenter IP.
Each run scans for ~5 min, then the workflow chains the next run.
"""
import os
import sys
import io
import time
import json
import re
import random
import logging
import shutil
import requests
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("yad2")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ===== Config =====
GREEN_API_URL = "https://7103.api.greenapi.com"
ID_INSTANCE = os.environ.get("ID_INSTANCE", "7103103506")
API_TOKEN = os.environ.get("API_TOKEN", "")
PHONE_TO_NOTIFY = os.environ.get("PHONE_TO_NOTIFY", "972526940950")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

YAD2_BASE_PARAMS = "manufacturer=19&model=10236&year=2016-2020&hand=0-3"
YAD2_URL = f"https://www.yad2.co.il/vehicles/cars?{YAD2_BASE_PARAMS}&Order=1"

STATE_FILE = "state.json"
PROXY_FILE = "proxies.txt"
SCAN_INTERVAL = 8
RUN_DURATION = 5 * 60 + 10
CHROMEDRIVER = os.environ.get("CHROMEDRIVER_PATH", "chromedriver")
CHROME_BIN = os.environ.get("CHROME_BIN", "")

_proxy_idx = 0


def load_proxies():
    try:
        with open(PROXY_FILE, encoding="utf-8") as f:
            ps = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        random.shuffle(ps)
        return ps
    except OSError:
        return []


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"max_order_id": 0, "known_ids": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def create_driver(proxy=None):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if CHROME_BIN:
        opts.binary_location = CHROME_BIN
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    service = Service(CHROMEDRIVER)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(25)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def fetch_listings(driver):
    try:
        cache_buster = int(time.time() * 1000)
        driver.get(f"{YAD2_URL}&_t={cache_buster}")
        time.sleep(2)
        html = driver.page_source
        if "captcha" in html.lower() or "ShieldSquare" in html:
            return "BLOCKED"
        if len(html) < 5000:
            return "BLOCKED"
        return parse_page(html)
    except Exception as e:
        log.error(f"[ERR] fetch: {str(e)[:120]}")
        return "PROXY_DEAD"


def parse_page(html):
    items = []
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        extract_items(json.loads(m.group(1)), items)
    except json.JSONDecodeError:
        return None
    return items if items else None


def extract_items(data, items):
    if isinstance(data, dict):
        if data.get("token") and data.get("manufacturer"):
            token = str(data["token"])
            mfr = data.get("manufacturer", {})
            model = data.get("model", {})
            sub = data.get("subModel", {})
            hand = data.get("hand", {})
            address_obj = data.get("address") or {}
            address = address_obj.get("area") or {} if isinstance(address_obj, dict) else {}
            dates = data.get("vehicleDates", {})
            price = data.get("price", "")
            meta = data.get("metaData") or {}
            cover = meta.get("coverImage", "") if isinstance(meta, dict) else ""
            ts_match = re.search(r"_(\d{14})\.", cover or "")
            img_ts = ts_match.group(1) if ts_match else ""
            items.append({
                "id": token,
                "title": f"{mfr.get('text','')} {model.get('text','')}".strip(),
                "subtitle": sub.get("text", "") if isinstance(sub, dict) else "",
                "price": f"{price:,}" if isinstance(price, (int, float)) else str(price),
                "year": str(dates.get("yearOfProduction", "")),
                "hand": hand.get("text", "") if isinstance(hand, dict) else str(hand),
                "city": address.get("text", "") if isinstance(address, dict) else "",
                "link": f"https://www.yad2.co.il/item/{token}",
                "orderId": data.get("orderId", 0),
                "imgTs": img_ts,
            })
        else:
            for v in data.values():
                if isinstance(v, (dict, list)):
                    extract_items(v, items)
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, (dict, list)):
                extract_items(v, items)


def fmt_listing_time(img_ts):
    if not img_ts or len(img_ts) < 14:
        return ""
    return f"{img_ts[6:8]}/{img_ts[4:6]}/{img_ts[0:4]} {img_ts[8:10]}:{img_ts[10:12]}:{img_ts[12:14]}"


def send_whatsapp(message):
    if not API_TOKEN:
        return False
    url = f"{GREEN_API_URL}/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"
    try:
        r = requests.post(url, json={"chatId": f"{PHONE_TO_NOTIFY}@c.us", "message": message}, timeout=10)
        r.raise_for_status()
        log.info("[OK] WhatsApp sent")
        return True
    except Exception as e:
        log.error(f"[ERR] WhatsApp: {str(e)[:80]}")
        return False


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID, "text": message,
            "parse_mode": "Markdown", "disable_web_page_preview": False,
        }, timeout=10)
        r.raise_for_status()
        log.info("[OK] Telegram sent")
        return True
    except Exception as e:
        log.error(f"[ERR] Telegram: {str(e)[:80]}")
        return False


def notify(message):
    send_telegram(message)
    send_whatsapp(message)


def format_msg(listing):
    parts = ["🚗 *מודעה חדשה ביד 2!*", ""]
    if listing.get("title"): parts.append(f"📌 {listing['title']}")
    if listing.get("subtitle"): parts.append(f"📋 {listing['subtitle']}")
    if listing.get("price"): parts.append(f"💰 {listing['price']} ₪")
    if listing.get("year"): parts.append(f"📅 שנתון: {listing['year']}")
    if listing.get("hand"): parts.append(f"✋ יד: {listing['hand']}")
    if listing.get("city"): parts.append(f"📍 {listing['city']}")
    t = fmt_listing_time(listing.get("imgTs", ""))
    if t:
        parts.append(f"🕐 עלתה: {t}")
    parts.append(f"\n🔗 {listing.get('link','')}")
    return "\n".join(parts)


def main():
    log.info("=" * 40)
    log.info("Yad2 Cloud Monitor (Selenium + proxies)")
    log.info("=" * 40)

    state = load_state()
    known_ids = set(state.get("known_ids", []))
    known_max_order = state.get("max_order_id", 0)
    first_run = (known_max_order == 0)
    proxies = load_proxies()
    log.info(f"[STATE] {len(known_ids)} known | maxOrderId={known_max_order} | proxies={len(proxies)}")

    if not proxies:
        log.error("[FATAL] No proxies.txt - run proxy_updater first")
        return 0

    global _proxy_idx
    driver = None
    deadline = time.time() + RUN_DURATION
    scans = ok = blocked = 0

    def new_driver():
        nonlocal driver
        if driver:
            try: driver.quit()
            except Exception: pass
        proxy = proxies[_proxy_idx % len(proxies)]
        return create_driver(proxy=proxy), proxy

    try:
        driver, cur_proxy = new_driver()
        log.info(f"[PROXY] {cur_proxy}")

        while time.time() < deadline:
            scans += 1
            result = fetch_listings(driver)

            if result in ("BLOCKED", "PROXY_DEAD", None):
                blocked += 1
                _proxy_idx += 1
                try:
                    driver, cur_proxy = new_driver()
                    log.info(f"[ROTATE] -> {cur_proxy}")
                except Exception as e:
                    log.error(f"[ERR] driver: {str(e)[:80]}")
                continue

            ok += 1
            current_ids = {it["id"] for it in result}
            max_order = max((it.get("orderId", 0) for it in result), default=0)

            if first_run:
                log.info(f"[INIT] {len(result)} listings | maxOrderId={max_order}")
                notify(
                    "🟢 *מערכת מעקב יד 2 פעילה!*\n\n"
                    "🔍 טויוטה פריוס 2016-2020\n✋ יד 1-3\n"
                    f"📊 מודעות: {len(current_ids)}\n"
                    "⏰ מעקב מיידי - תוך שניות\n☁️ רץ בענן 24/7"
                )
                known_ids = current_ids
                known_max_order = max_order
                first_run = False
                save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})
            else:
                new_listings = [it for it in result
                                if it["id"] not in known_ids and it.get("orderId", 0) > known_max_order]
                if new_listings:
                    log.info(f"[NEW] {len(new_listings)} new")
                    for lst in sorted(new_listings, key=lambda x: x.get("orderId", 0), reverse=True):
                        log.info(f"[SEND] {lst['orderId']} | {lst['title']} {lst['price']} | {lst.get('imgTs','')}")
                        notify(format_msg(lst))
                    known_ids |= current_ids
                    if max_order > known_max_order:
                        known_max_order = max_order
                    save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})

            time.sleep(SCAN_INTERVAL)
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass

    log.info(f"[DONE] scans={scans} ok={ok} blocked={blocked} | maxOrderId={known_max_order}")
    save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})
    return 0


if __name__ == "__main__":
    sys.exit(main())

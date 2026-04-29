"""
Yad2 Cloud Monitor - GitHub Actions edition
Each run scans yad2 repeatedly (every 10s) for ~4.5 minutes, then exits.
GitHub Actions schedules a new run every 10 minutes -> near-continuous coverage.
"""
import os
import sys
import io
import time
import json
import re
import logging
import requests
import cloudscraper
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("yad2")

GREEN_API_URL = "https://7103.api.greenapi.com"
ID_INSTANCE = os.environ.get("ID_INSTANCE", "7103103506")
API_TOKEN = os.environ.get("API_TOKEN", "")
PHONE_TO_NOTIFY = os.environ.get("PHONE_TO_NOTIFY", "972526940950")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

YAD2_BASE_PARAMS = "manufacturer=19&model=10236&year=2016-2022&price=-1-65000&hand=0-3"
YAD2_URL = f"https://www.yad2.co.il/vehicles/cars?{YAD2_BASE_PARAMS}&Order=5"

STATE_FILE = "state.json"
SCAN_INTERVAL = 10           # seconds between scans inside one run
RUN_DURATION = 4 * 60 + 30   # ~4.5 min, leaves time for setup/commit
MAX_FETCH_RETRIES = 3


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"max_order_id": 0, "known_ids": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_listings(scraper):
    try:
        cache_buster = int(time.time() * 1000)
        r = scraper.get(f"{YAD2_URL}&_t={cache_buster}", timeout=20)
        html = r.text
        if r.status_code != 200 or len(html) < 5000:
            return None
        if "captcha" in html.lower() or "ShieldSquare" in html:
            return "BLOCKED"
        return parse_page(html)
    except Exception as e:
        log.error(f"[ERR] fetch: {e}")
        return None


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
            })
        else:
            for v in data.values():
                if isinstance(v, (dict, list)):
                    extract_items(v, items)
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, (dict, list)):
                extract_items(v, items)


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
        log.error(f"[ERR] WhatsApp: {e}")
        return False


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }, timeout=10)
        r.raise_for_status()
        log.info("[OK] Telegram sent")
        return True
    except Exception as e:
        log.error(f"[ERR] Telegram: {e}")
        return False


def notify(message):
    """Send through both channels - whichever works delivers."""
    send_whatsapp(message)
    send_telegram(message)


def format_msg(listing):
    parts = ["🚗 *מודעה חדשה ביד 2!* (☁️ ענן)", ""]
    if listing.get("title"): parts.append(f"📌 {listing['title']}")
    if listing.get("subtitle"): parts.append(f"📋 {listing['subtitle']}")
    if listing.get("price"): parts.append(f"💰 {listing['price']}")
    if listing.get("year"): parts.append(f"📅 {listing['year']}")
    if listing.get("hand"): parts.append(f"✋ יד: {listing['hand']}")
    if listing.get("city"): parts.append(f"📍 {listing['city']}")
    parts.append(f"\n🔗 {listing.get('link','')}")
    return "\n".join(parts)


def make_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def main():
    log.info("=" * 40)
    log.info("Yad2 Cloud Monitor (GitHub Actions, 10s loop)")
    log.info("=" * 40)

    state = load_state()
    known_ids = set(state.get("known_ids", []))
    known_max_order = state.get("max_order_id", 0)
    first_run = (known_max_order == 0)
    log.info(f"[STATE] {len(known_ids)} known | maxOrderId={known_max_order}")

    scraper = make_scraper()
    deadline = time.time() + RUN_DURATION
    scans = 0
    successes = 0
    blocked = 0
    captcha_streak = 0

    while time.time() < deadline:
        scans += 1
        listings = fetch_listings(scraper)

        if listings == "BLOCKED":
            blocked += 1
            captcha_streak += 1
            scraper = make_scraper()
            time.sleep(SCAN_INTERVAL)
            continue

        if not listings:
            captcha_streak += 1
            if captcha_streak >= 3:
                scraper = make_scraper()
                captcha_streak = 0
            time.sleep(SCAN_INTERVAL)
            continue

        captcha_streak = 0
        successes += 1
        current_ids = {item["id"] for item in listings}
        max_order = max((item.get("orderId", 0) for item in listings), default=0)

        if first_run:
            log.info(f"[INIT] Got {len(listings)} listings | maxOrderId={max_order}")
            notify(
                "🟢 *מערכת מעקב יד 2 ענן פעילה!*\n\n"
                "🔍 טויוטה פריוס 2016-2022\n"
                "💰 עד 65,000 ₪ | יד 1-3\n"
                f"📊 מודעות: {len(current_ids)}\n"
                "⏰ בודק כל 10 שניות\n"
                "☁️ רץ ב-GitHub Actions"
            )
            known_ids = current_ids
            known_max_order = max_order
            first_run = False
            save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})
        else:
            new_listings = [
                item for item in listings
                if item["id"] not in known_ids and item.get("orderId", 0) > known_max_order
            ]
            if new_listings:
                log.info(f"[NEW] {len(new_listings)} new (orderId > {known_max_order})")
                for listing in sorted(new_listings, key=lambda x: x.get("orderId", 0), reverse=True):
                    log.info(f"[SEND] orderId={listing['orderId']} | {listing['title']} - {listing['price']}")
                    notify(format_msg(listing))
                known_ids |= current_ids
                if max_order > known_max_order:
                    known_max_order = max_order
                save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})

        time.sleep(SCAN_INTERVAL)

    log.info(f"[DONE] scans={scans} ok={successes} blocked={blocked} | maxOrderId={known_max_order}")
    # Always persist - in case max_order rose without a NEW being sent
    save_state({"known_ids": list(known_ids), "max_order_id": known_max_order})
    return 0


if __name__ == "__main__":
    sys.exit(main())

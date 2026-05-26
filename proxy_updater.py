"""Fetch fresh public proxies, keep ones that are alive, write proxies.txt.
Runs hourly in the cloud (proxy_update.yml) and commits the result.
"""
import sys, time, concurrent.futures, requests

OUT_FILE = "proxies.txt"
TEST_URL = "https://httpbin.org/ip"
MAX_WORKING = 120
PER_TIMEOUT = 5
WORKERS = 120

SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
]


def fetch_all():
    seen = set()
    for url in SOURCES:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            socks = "socks5" in url
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "://" not in line:
                    line = ("socks5://" if socks else "http://") + line
                host = line.split("://", 1)[1]
                if ":" in host:
                    seen.add(line)
        except Exception as e:
            print(f"[ERR] {url}: {e}")
    return list(seen)


def test(proxy):
    try:
        r = requests.get(TEST_URL, proxies={"http": proxy, "https": proxy},
                         timeout=PER_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and "origin" in r.text:
            return proxy
    except Exception:
        pass
    return None


def main():
    proxies = fetch_all()
    print(f"[INFO] {len(proxies)} candidate proxies")
    if not proxies:
        return 1
    working = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(test, p) for p in proxies]
        for f in concurrent.futures.as_completed(futures):
            r = f.result()
            if r:
                working.append(r)
                if len(working) >= MAX_WORKING:
                    break
    print(f"[DONE] {len(working)} working proxies")
    if not working:
        return 1
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# updated {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        for p in working:
            f.write(p + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

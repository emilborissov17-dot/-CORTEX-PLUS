import os
from urllib.parse import urlparse
import requests

# Къде да пазим HTML файловете
OUTPUT_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++\knowledge\fresco"

# Разрешени домейни
ALLOWED_DOMAINS = {
    "wikipedia.org",
    "wiktionary.org",
    "wikibooks.org",
    "wikidata.org",
    "wikiquote.org",
    "wikimedia.org",
    "arxiv.org",
    "archive.org",
    "doi.org",
    "mit.edu",
    "stanford.edu",
    "harvard.edu",
    "ox.ac.uk",
    "cam.ac.uk",
    "nasa.gov",
    "esa.int",
    "noaa.gov",
    "who.int",
    "ipcc.ch",
    "thevenusproject.com",
    "designing-the-future.org",
    "venusproject.org",
    "thevenusproject.fandom.com",
    "khanacademy.org",
    "coursera.org",
    "edx.org",
    "youtube.com",
    "sciencedirect.com",
    "phys.org",
    "github.com",
    "zenodo.org",
}

# Файлът със списъка от URL-и
URLS_FILE = r"C:\Users\emilb\Desktop\AGI\CORTEX++\config\fresco_urls.txt"


def domain_allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for allowed in ALLOWED_DOMAINS:
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.replace(":", "_")
    path = parsed.path.replace("/", "_")
    if not path:
        path = "_"
    name = f"{host}{path}"
    if len(name) > 150:
        name = name[:150]
    return name + ".html"


def make_headers(url: str) -> dict:
    # По-човешки header-и, за да минават 403 блокировките
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36 "
            "CortexFrescoDownloader/1.0 (contact: example@example.com)"
        ),
        "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive",
        "Referer": url,
    }


def download_url(url: str):
    url = url.strip()
    if not url:
        return

    if not domain_allowed(url):
        print(f"[SKIP] НЕДОПУСТИМ ДОМЕЙН: {url}")
        return

    print(f"[GET] {url}")

    try:
        headers = make_headers(url)
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] {url} -> {e}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = safe_filename_from_url(url)
    full_path = os.path.join(OUTPUT_DIR, filename)

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"[OK] {url} -> {full_path}")
    except Exception as e:
        print(f"[ERROR SAVE] {url} -> {e}")


def main():
    if not os.path.exists(URLS_FILE):
        print(f"Не намерих файла с линкове: {URLS_FILE}")
        return

    with open(URLS_FILE, "r", encoding="utf-8") as f:
        urls = f.readlines()

    if not urls:
        print("Няма линкове във файла.")
        return

    print(f"Намерени {len(urls)} линка. Започвам сваляне...")
    for url in urls:
        download_url(url)


if __name__ == "__main__":
    main()

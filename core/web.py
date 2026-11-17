"""Web helpers: search, readable page text, Wikipedia summary, live crypto prices, and weather."""
import ipaddress
import re
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

import config
from core.logger import log

try:
    from ddgs import DDGS                      # the current package name
except ImportError:
    try:
        from duckduckgo_search import DDGS     # older name
    except ImportError:
        DDGS = None

try:
    from curl_cffi import requests as cffi_requests   # looks like a real Chrome, so fewer sites block it
except ImportError:
    cffi_requests = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
WIKI_HEADERS = {"User-Agent": "InfinityAgent/1.0 (personal project)"}

BAD_DOMAINS = ("pinterest.", "facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
               "youtube.com", "youtu.be", "quora.com", "linkedin.com")
GOOD_HINTS = ("wikipedia.org", "britannica.com", ".gov", ".edu", "nature.com", "who.int", "reuters.com",
              "bbc.", "ieee.org", "sciencedirect.com", "nih.gov", "mit.edu", "stanford.edu", "apnews.com",
              "coinbase.com", "coingecko.com")
SKIP_EXT = (".pdf", ".zip", ".exe", ".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".docx", ".xlsx")

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "heavy rain showers",
    82: "violent rain showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

_CRYPTO_MAP = {
    "bitcoin": ("BTC", "bitcoin"),
    "btc": ("BTC", "bitcoin"),
    "ethereum": ("ETH", "ethereum"),
    "eth": ("ETH", "ethereum"),
    "solana": ("SOL", "solana"),
    "sol": ("SOL", "solana"),
    "dogecoin": ("DOGE", "dogecoin"),
    "doge": ("DOGE", "dogecoin"),
}


def _try_crypto_spot(query: str):
    """If the search query asks for a cryptocurrency price, fetch live spot price in USD."""
    low = query.lower()
    matched = None
    for key, (sym, cg_id) in _CRYPTO_MAP.items():
        if re.search(rf"\b{key}\b", low):
            matched = (sym, cg_id)
            break
    if not matched:
        return []
    sym, cg_id = matched
    try:
        r = requests.get(
            f"https://api.coinbase.com/v2/prices/{sym}-USD/spot",
            headers=HEADERS,
            timeout=6,
        )
        if r.ok:
            amt = float(r.json()["data"]["amount"])
            return [{
                "title": f"Live {cg_id.title()} ({sym}) Price in USD - Coinbase Spot",
                "url": f"https://www.coinbase.com/price/{cg_id}",
                "snippet": f"The current live price of {cg_id.title()} ({sym}) is ${amt:,.2f} USD (as of {time.strftime('%Y-%m-%d %H:%M')}).",
            }]
    except Exception:
        pass
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd"},
            headers=HEADERS,
            timeout=6,
        )
        if r.ok:
            amt = float(r.json()[cg_id]["usd"])
            return [{
                "title": f"Live {cg_id.title()} ({sym}) Price in USD - CoinGecko",
                "url": f"https://www.coingecko.com/en/coins/{cg_id}",
                "snippet": f"The current live price of {cg_id.title()} ({sym}) is ${amt:,.2f} USD (as of {time.strftime('%Y-%m-%d %H:%M')}).",
            }]
    except Exception:
        pass
    return []


def _ddg_html_fallback(query: str, n: int = 6):
    """Fallback HTML scraper for DuckDuckGo when the ddgs library fails or returns empty."""
    out = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=config.WEB_TIMEOUT,
        )
        if not resp.ok:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        for res in soup.select(".result"):
            a = res.select_one(".result__a")
            snip = res.select_one(".result__snippet")
            if not a:
                continue
            href = a.get("href", "")
            if "uddg=" in href:
                qs = parse_qs(urlparse(href).query)
                href = unquote(qs.get("uddg", [href])[0])
            if href.startswith("http"):
                out.append({
                    "title": a.get_text(" ", strip=True),
                    "url": href,
                    "snippet": snip.get_text(" ", strip=True) if snip else "",
                })
            if len(out) >= n:
                break
    except Exception as e:
        log(f"_ddg_html_fallback failed: {e}")
    return out


# ---------------- search ----------------
def search(query, n=6):
    """DuckDuckGo results as [{'title', 'url', 'snippet'}], augmented with live spot prices and HTML fallback."""
    live_items = _try_crypto_spot(str(query))
    last = "unknown error"
    if DDGS is not None:
        for attempt in range(1, config.WEB_RETRIES + 1):
            try:
                try:
                    with DDGS(timeout=config.WEB_TIMEOUT) as ddgs:
                        raw = list(ddgs.text(query, max_results=n))
                except TypeError:
                    with DDGS() as ddgs:
                        raw = list(ddgs.text(query, max_results=n))
                ddg_items = [
                    {"title": r.get("title") or "", "url": r.get("href") or "", "snippet": r.get("body") or ""}
                    for r in raw if r.get("href")
                ]
                if ddg_items:
                    return live_items + ddg_items
            except Exception as e:      # noqa: BLE001
                last = str(e)
                log(f"web.search attempt {attempt}/{config.WEB_RETRIES} failed: {e}")
                time.sleep(0.8)

    html_items = _ddg_html_fallback(str(query), n=n)
    if html_items or live_items:
        return live_items + html_items
    raise RuntimeError(f"Web search failed: {last}")


def rank(results):
    """Remove duplicates and low-quality sites, put trustworthy sites first."""
    seen, scored = set(), []
    for i, r in enumerate(results):
        parsed = urlparse(r["url"])
        host = (parsed.hostname or "").lower()
        key = (host, parsed.path.rstrip("/"))
        if key in seen or any(b in host for b in BAD_DOMAINS) or parsed.path.lower().endswith(SKIP_EXT):
            continue
        seen.add(key)
        score = -i + (3 if any(g in host for g in GOOD_HINTS) else 0)
        scored.append((score, r))
    scored.sort(key=lambda item: -item[0])
    return [r for _, r in scored]


# ---------------- pages ----------------
def safe_url(url):
    """Only public http(s) pages: never localhost or private network addresses."""
    p = urlparse(str(url).strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return True


def _get(url):
    last = "unknown error"
    for attempt in range(1, config.WEB_RETRIES + 1):
        try:
            if cffi_requests is not None:
                resp = cffi_requests.get(url, headers=HEADERS, impersonate="chrome",
                                         allow_redirects=True, timeout=config.WEB_TIMEOUT)
            else:
                resp = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=config.WEB_TIMEOUT)
            resp.raise_for_status()
            kind = (resp.headers.get("content-type") or "").lower()
            if kind and "html" not in kind and "text" not in kind:
                raise ValueError(f"not a text page ({kind.split(';')[0]})")
            return resp.text
        except Exception as e:      # noqa: BLE001
            last = str(e)
            log(f"web.fetch {url} attempt {attempt}/{config.WEB_RETRIES} failed: {e}")
            time.sleep(0.7)
    raise RuntimeError(f"Could not open {url}: {last}")


def extract_text(html, max_chars):
    """The readable text of an HTML page (main article if there is one)."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg", "aside", "iframe"]):
        el.decompose()
    candidates = []
    for node in (soup.find("article"), soup.find("main"), soup.body, soup):
        if node is not None:
            text = re.sub(r"\s+", " ", node.get_text(separator=" ")).strip()
            candidates.append(text)
            if len(text) >= 600:
                break
    text = max(candidates, key=len) if candidates else ""
    for cand in candidates:
        if len(cand) >= 600:
            text = cand
            break
    return text[:max_chars]


def fetch_text(url, max_chars=None):
    """Readable text of a public web page. Raises ValueError / RuntimeError with a clear reason."""
    max_chars = max_chars or config.RESEARCH_CHARS_PER_SOURCE
    if not safe_url(url):
        raise ValueError("That address is not allowed (only public http/https pages can be opened).")
    if urlparse(url).path.lower().endswith(SKIP_EXT):
        raise ValueError("That link is a file, not a web page.")
    return extract_text(_get(url), max_chars)


# ---------------- wikipedia and weather ----------------
def wiki_summary(topic):
    """{'title', 'url', 'text'} for the best Wikipedia match, or None."""
    r = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": topic, "srlimit": 1, "format": "json"},
        headers=WIKI_HEADERS, timeout=config.WEB_TIMEOUT,
    )
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    if not hits:
        return None
    title = hits[0]["title"]
    slug = quote(title.replace(" ", "_"))
    s = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                     headers=WIKI_HEADERS, timeout=config.WEB_TIMEOUT)
    s.raise_for_status()
    data = s.json()
    url = (data.get("content_urls") or {}).get("desktop", {}).get("page") or f"https://en.wikipedia.org/wiki/{slug}"
    return {"title": data.get("title", title), "url": url, "text": data.get("extract", "")}


def weather(city):
    """One line of current weather for a city (Open-Meteo, no key needed)."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"}, timeout=config.WEB_TIMEOUT,
    ).json()
    if not geo.get("results"):
        short_city = str(city).split(",")[0].strip()
        if short_city and short_city != city:
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": short_city, "count": 1, "language": "en", "format": "json"}, timeout=config.WEB_TIMEOUT,
            ).json()
    if not geo.get("results"):
        raise ValueError(f"City not found: {city}")
    place = geo["results"][0]
    data = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": place["latitude"], "longitude": place["longitude"], "current_weather": "true"},
        timeout=config.WEB_TIMEOUT,
    ).json()["current_weather"]
    desc = WEATHER_CODES.get(data.get("weathercode"), f"weather code {data.get('weathercode')}")
    name = ", ".join(x for x in (place.get("name"), place.get("admin1"), place.get("country")) if x)
    return (f"{name}: {data['temperature']}°C, {desc}, wind {data['windspeed']} km/h "
            f"({'day' if data.get('is_day') else 'night'}, as of {data.get('time', 'now')})")
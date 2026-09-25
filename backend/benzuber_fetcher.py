import urllib.request
import ssl
import json
import re
import time
import gzip
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from backend.config import NN_LAT_MIN, NN_LAT_MAX, NN_LON_MIN, NN_LON_MAX, get_msk_iso

URL_BENZUBER_MAP = "https://app.benzuber.ru/map?zoom=14&price_mode=1"
URL_BENZUBER_STATION = "https://app.benzuber.ru/map?station_id={sid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8,application/json",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://app.benzuber.ru/",
    "Connection": "keep-alive"
}

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def parse_price(val_str):
    try:
        clean = re.sub(r"[^\d\.,]", "", val_str).replace(",", ".")
        return float(clean)
    except Exception:
        return 0.0

def decompress_if_needed(raw_bytes):
    if len(raw_bytes) >= 2 and raw_bytes[:2] == b'\x1f\x8b':
        try:
            return gzip.decompress(raw_bytes)
        except Exception:
            pass
    return raw_bytes

def decode_benzuber_html(raw_bytes):
    raw_bytes = decompress_if_needed(raw_bytes)
    try:
        s = raw_bytes.decode("windows-1251")
        # Fix double-encoded UTF-8 inside windows-1251
        return s.encode("windows-1251").decode("utf-8")
    except Exception:
        try:
            return raw_bytes.decode("utf-8")
        except Exception:
            return raw_bytes.decode("windows-1251", errors="replace")

def fetch_single_benzuber_station(feature):
    sid = feature.get("id")
    coords = feature.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        return None
    lat, lon = float(coords[0]), float(coords[1])
    
    ctx = get_ssl_context()
    req = urllib.request.Request(URL_BENZUBER_STATION.format(sid=sid), headers=HEADERS)
    
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                html = decode_benzuber_html(resp.read())
                
            brand_m = re.search(r'<div class="brand">([^<]+)</div>', html)
            addr_m = re.search(r'<div class="address">([^<]+)</div>', html)
            name_m = re.search(r'<h1>([^<]+)</h1>', html)
            
            brand = brand_m.group(1).strip() if brand_m else "АЗС"
            address = addr_m.group(1).strip() if addr_m else ""
            name = name_m.group(1).strip() if name_m else f"АЗС {brand} №{sid}"
            
            # Skip Lukoil because we query official Licard API directly
            if "лукойл" in brand.lower() or "lukoil" in brand.lower():
                return None
            
            # Parse fuel items
            # Example pattern in Benzuber HTML:
            # <div class="status red" title="Топливо временно недоступно"></div> ...
            fuel_blocks = re.findall(
                r'<div class="item">.*?<div class="status ([^"]*)"[^>]*title="([^"]*)"[^>]*></div>\s*<div class="name">\s*([^<]+)(?:<br /><span>([^<]+)</span>)?\s*</div>\s*<div class="price">([^<]+)</div>',
                html,
                re.DOTALL
            )
            
            fuels_dict = {
                "92": None,
                "95": None,
                "100": None,
                "dt": None,
                "lpg": None
            }
            
            has_active = False
            for status_cls, status_title, fname, limit_note, raw_price in fuel_blocks:
                p = parse_price(raw_price)
                st_cls_low = status_cls.lower()
                st_title_low = status_title.lower()
                
                # Check for unavailable / stop of sales indicators
                is_disabled = (
                    "unavailable" in st_cls_low
                    or "red" in st_cls_low
                    or "остановк" in st_title_low
                    or "недоступн" in st_title_low
                    or p <= 0
                )
                is_available = not is_disabled
                if is_available:
                    has_active = True
                
                fn_clean = fname.strip()
                fn_low = fn_clean.lower()
                clean_limit = limit_note.strip() if limit_note else None
                fuel_info = {
                    "name": fn_clean,
                    "price": p,
                    "available": is_available,
                    "raw_status": status_title.strip() if status_title else ("available" if is_available else "unavailable"),
                    "limit": clean_limit
                }
                
                if "100" in fn_low or "98" in fn_low:
                    if not fuels_dict["100"] or is_available:
                        fuels_dict["100"] = fuel_info
                elif "95" in fn_low:
                    if not fuels_dict["95"] or is_available:
                        fuels_dict["95"] = fuel_info
                elif "92" in fn_low:
                    if not fuels_dict["92"] or is_available:
                        fuels_dict["92"] = fuel_info
                elif "дизель" in fn_low or "дт" in fn_low:
                    if not fuels_dict["dt"] or is_available:
                        fuels_dict["dt"] = fuel_info
                elif any(g in fn_low for g in ["пропан", "газ", "метан", "lpg", "cng"]):
                    if not fuels_dict["lpg"] or is_available:
                        fuels_dict["lpg"] = fuel_info
            
            # Map canonical brand names for prettier display
            canonical_brand = brand
            b_low = brand.lower()
            if "татнефть" in b_low or "tatneft" in b_low:
                canonical_brand = "Татнефть"
            elif "газпром" in b_low or "gpn" in b_low:
                canonical_brand = "Газпромнефть"
            elif "сфера" in b_low:
                canonical_brand = "СфераОйл"
            elif "esco" in b_low:
                canonical_brand = "ESCO"
            elif "nikoil" in b_low or "никойл" in b_low:
                canonical_brand = "NikOil"
            elif "корунд" in b_low:
                canonical_brand = "Корунд Ойл"
            elif "тебойл" in b_low or "teboil" in b_low:
                canonical_brand = "Teboil"
            elif "опти" in b_low:
                canonical_brand = "ОПТИ"
                
            return {
                "id": f"benzuber_{sid}",
                "source": "benzuber_api",
                "source_name": "API Benzuber (партнер АЗС)",
                "source_url": f"https://app.benzuber.ru/map?station_id={sid}",
                "network": canonical_brand,
                "brand": canonical_brand,
                "name": name,
                "address": address,
                "coords": [lat, lon],
                "fuels": fuels_dict,
                "status": "active" if has_active else "empty",
                "updated_at": get_msk_iso()
            }
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            return None

def fetch_benzuber_stations_nn():
    """
    1. Fetches full station catalog from Benzuber.
    2. Filters stations in Nizhny Novgorod area (excluding Lukoil).
    3. Multi-threaded fetch of real-time prices and availability.
    """
    ctx = get_ssl_context()
    req = urllib.request.Request(URL_BENZUBER_MAP, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = decompress_if_needed(resp.read())
            data = json.loads(raw.decode("utf-8"))
            features = data.get("features", [])
    except Exception as e:
        print(f"[!] Benzuber API: Failed to fetch map features ({type(e).__name__}): {e}")
        return []
        
    nn_targets = []
    for f in features:
        coords = f.get("geometry", {}).get("coordinates", [])
        if len(coords) == 2:
            lat, lon = float(coords[0]), float(coords[1])
            if NN_LAT_MIN <= lat <= NN_LAT_MAX and NN_LON_MIN <= lon <= NN_LON_MAX:
                nn_targets.append(f)
                
    print(f"[*] Benzuber: Found {len(nn_targets)} stations in Nizhny Novgorod area. Polling details...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for res in executor.map(fetch_single_benzuber_station, nn_targets):
            if res:
                results.append(res)
                
    print(f"[OK] Benzuber: Processed {len(results)} other-brand stations.")
    return results

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    stations = fetch_benzuber_stations_nn()
    for s in stations[:10]:
        print(s["brand"], "|", s["name"], "|", s["address"], "|", s["fuels"])

import urllib.request
import ssl
import json
import uuid
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from backend.config import NN_LAT_MIN, NN_LAT_MAX, NN_LON_MIN, NN_LON_MAX

URL_STATION_LIST = "https://azs.lukoil.ru/api/v14/common/station/list"
URL_FUEL_LIST = "https://azs.lukoil.ru/api/v14/common/station/fuel/list"
API_TOKEN = "mcHySTn5vmPvMLWrYMfG3xgC9rV2moJ6"

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def get_headers():
    return {
        "X-Api-Token": API_TOKEN,
        "User-Agent": "LicardB2C/Android/4.5.0.0/Android 12",
        "device_id": str(uuid.uuid4()),
        "Content-Type": "application/json"
    }

def fetch_lukoil_station_fuels(station_item):
    """
    Fetches real-time fuel prices and pump sensor availability for a single Lukoil station.
    Retries once on transient network/HTTP blips.
    """
    sid = station_item["id"]
    ctx = get_ssl_context()
    payload = json.dumps({"stationId": str(sid)}).encode("utf-8")
    
    for attempt in range(2):
        headers = get_headers()
        req = urllib.request.Request(URL_FUEL_LIST, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                fuels_raw = data.get("result", {}).get("fuels", [])
                
                fuels_dict = {
                    "92": None,
                    "95": None,
                    "100": None,
                    "dt": None,
                    "lpg": None
                }
                
                if not fuels_raw:
                    return {
                        "id": f"lukoil_{sid}",
                        "source": "lukoil_api",
                        "source_name": "API Ликард / Лукойл (v14)",
                        "source_url": None,
                        "network": "Лукойл",
                        "brand": "Лукойл",
                        "name": station_item.get("name") or f"АЗС Лукойл №{sid}",
                        "address": station_item.get("address", ""),
                        "coords": [station_item["lat"], station_item["lon"]],
                        "fuels": fuels_dict,
                        "status": "closed",
                        "updated_at": datetime.now().isoformat()
                    }
                
                has_any_active = False
                for f in fuels_raw:
                    fname = f.get("name", "")
                    fprice = float(f.get("price", 0.0))
                    favail = f.get("fuelAvailability", "").lower()
                    
                    # Available if status is 'available' or 'low' and price > 0
                    is_available = (favail in ("available", "low", "") and fprice > 0)
                    if is_available:
                        has_any_active = True
                    
                    fn_low = fname.lower()
                    fuel_info = {
                        "name": fname,
                        "price": fprice,
                        "available": is_available,
                        "raw_status": favail
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
                    elif "газ" in fn_low or "пропан" in fn_low or "lpg" in fn_low:
                        if not fuels_dict["lpg"] or is_available:
                            fuels_dict["lpg"] = fuel_info
                
                return {
                    "id": f"lukoil_{sid}",
                    "source": "lukoil_api",
                    "source_name": "API Ликард / Лукойл (v14)",
                    "source_url": None,
                    "network": "Лукойл",
                    "brand": "Лукойл",
                    "name": station_item.get("name") or f"АЗС Лукойл №{sid}",
                    "address": station_item.get("address", ""),
                    "coords": [station_item["lat"], station_item["lon"]],
                    "fuels": fuels_dict,
                    "status": "active" if has_any_active else "empty",
                    "updated_at": datetime.now().isoformat()
                }
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            # Fallback on total failure
            return {
                "id": f"lukoil_{sid}",
                "source": "lukoil_api",
                "source_name": "API Ликард / Лукойл (v14)",
                "source_url": None,
                "network": "Лукойл",
                "brand": "Лукойл",
                "name": station_item.get("name") or f"АЗС Лукойл №{sid}",
                "address": station_item.get("address", ""),
                "coords": [station_item["lat"], station_item["lon"]],
                "fuels": {"92": None, "95": None, "100": None, "dt": None, "lpg": None},
                "status": "error",
                "updated_at": datetime.now().isoformat()
            }

def fetch_lukoil_stations_nn():
    """
    1. Fetches all Lukoil stations list in Russia.
    2. Filters stations belonging to Nizhny Novgorod area.
    3. Concurrently queries real-time fuel telemetry for each station.
    """
    ctx = get_ssl_context()
    headers = get_headers()
    req = urllib.request.Request(URL_STATION_LIST, data=b"{}", headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_stations = data.get("result", {}).get("stations", [])
    except Exception as e:
        print(f"[!] Lukoil API: Failed to fetch station catalog: {e}")
        return []

    nn_targets = []
    for s in raw_stations:
        loc = s.get("location") or {}
        lat = float(loc.get("latitude") or 0.0)
        lon = float(loc.get("longitude") or 0.0)
        addr = s.get("address") or ""
        
        # Check if coordinates fall inside the NN bounding box
        in_bbox = (NN_LAT_MIN <= lat <= NN_LAT_MAX and NN_LON_MIN <= lon <= NN_LON_MAX)
        # Exclude other regions if street name happens to contain 'Дзержинск'
        is_wrong_region = any(reg in addr for reg in ["Перм", "Киров", "Челябинск", "Татарстан", "Чуваш", "Владимир"])
        
        if in_bbox and not is_wrong_region:
            nn_targets.append({
                "id": s.get("id"),
                "name": s.get("name", ""),
                "address": addr,
                "lat": lat,
                "lon": lon
            })

    print(f"[*] Lukoil: Found {len(nn_targets)} stations in Nizhny Novgorod area. Polling fuels...")
    
    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_lukoil_station_fuels, item) for item in nn_targets]
        for fut in futures:
            res = fut.result()
            if res:
                results.append(res)
                
    print(f"[OK] Lukoil: Processed {len(results)} stations.")
    return results

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    stations = fetch_lukoil_stations_nn()
    for s in stations[:5]:
        print(s["name"], s["address"], s["fuels"])

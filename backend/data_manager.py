import os
import json
import time
import threading
from datetime import datetime
from pathlib import Path

from backend.config import CACHE_FILE, DATA_DIR, REFRESH_INTERVAL_SECONDS, get_msk_iso
from backend.lukoil_fetcher import fetch_lukoil_stations_nn
from backend.benzuber_fetcher import fetch_benzuber_stations_nn

SEED_FILE = DATA_DIR / "nn_fuel_seed.json"

class FuelDataManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._stations = []
        self._last_updated = None
        self._is_updating = False
        self._last_manual_refresh = 0
        
        # Ensure data directory exists
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Load cached data if present
        self._load_from_disk()

    def start_background_scheduler(self):
        """Starts 12-hour background updater if not already started"""
        if not hasattr(self, "_bg_started") or not self._bg_started:
            self._bg_started = True
            self._bg_thread = threading.Thread(target=self._background_scheduler, daemon=True)
            self._bg_thread.start()
            print("[*] 12-hour background updater service started.")
        
    def _load_from_disk(self):
        loaded = False
        if CACHE_FILE.exists():
            try:
                if CACHE_FILE.stat().st_size > 0:
                    with open(CACHE_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        st = data.get("stations", [])
                        if len(st) >= 50:
                            self._stations = st
                            self._last_updated = data.get("updated_at")
                            loaded = True
                            print(f"[*] Loaded {len(self._stations)} stations from primary disk cache (Updated: {self._last_updated})")
            except Exception as e:
                print(f"[!] Failed to read primary disk cache: {e}")
                
        # If cache was missing or incomplete (< 50 stations), fallback to seed file
        if not loaded and SEED_FILE.exists():
            try:
                with open(SEED_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._stations = data.get("stations", [])
                    self._last_updated = data.get("updated_at") or get_msk_iso()
                    print(f"[*] Restored {len(self._stations)} stations from SEED backup file!")
                    # Save into cache file
                    self._save_to_disk()
            except Exception as e:
                print(f"[!] Failed to read seed backup file: {e}")
                
    def _save_to_disk(self):
        try:
            tmp_file = CACHE_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": self._last_updated,
                    "count": len(self._stations),
                    "stations": self._stations
                }, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp_file.replace(CACHE_FILE)
            print(f"[*] Cache saved to disk ({len(self._stations)} stations)")
        except Exception as e:
            print(f"[!] Failed to save disk cache: {e}")

    def update_all(self):
        """
        Runs full multi-source refresh across Lukoil and Benzuber.
        Thread-safe and preserves cached data if one source is temporarily unreachable.
        """
        with self._lock:
            if self._is_updating:
                return False, "Обновление уже выполняется"
            self._is_updating = True

        print(f"\n[{get_msk_iso()}] Starting full fuel data refresh for Nizhny Novgorod...")
        try:
            # 1. Fetch Lukoil stations
            lukoil_stations = fetch_lukoil_stations_nn()
            
            # 2. Fetch Benzuber stations (Tatneft, Gazpromneft, local brands)
            benzuber_stations = fetch_benzuber_stations_nn()
            
            # Fail-safe preservation: if an API returned 0 stations, retain previous ones from memory
            if not lukoil_stations:
                old_lukoil = [s for s in self._stations if s.get("source") == "lukoil_api" or "лукойл" in s.get("brand", "").lower()]
                if old_lukoil:
                    print(f"[!] Lukoil API returned 0 stations. Preserving {len(old_lukoil)} cached Lukoil stations.")
                    lukoil_stations = old_lukoil
                    
            if not benzuber_stations:
                old_benzuber = [s for s in self._stations if s.get("source") == "benzuber_api" or "лукойл" not in s.get("brand", "").lower()]
                if old_benzuber:
                    print(f"[!] Benzuber API returned 0 stations. Preserving {len(old_benzuber)} cached Benzuber stations.")
                    benzuber_stations = old_benzuber

            # 3. Merge and deduplicate
            merged = []
            seen_coords = set()
            
            # Lukoil takes precedence for accuracy
            for s in lukoil_stations:
                c = tuple(s.get("coords", [0, 0]))
                seen_coords.add((round(c[0], 4), round(c[1], 4)))
                merged.append(s)
                
            for s in benzuber_stations:
                c = tuple(s.get("coords", [0, 0]))
                c_round = (round(c[0], 4), round(c[1], 4))
                # Skip if already added
                if c_round not in seen_coords:
                    seen_coords.add(c_round)
                    merged.append(s)
                    
            # Sort by brand and name
            merged.sort(key=lambda x: (x.get("brand", ""), x.get("name", "")))
            
            with self._lock:
                self._stations = merged
                self._last_updated = get_msk_iso()
                self._is_updating = False
                
            self._save_to_disk()
            print(f"[OK] Full refresh complete! Total stations in database: {len(merged)}")
            return True, f"Успешно обновлено: {len(merged)} АЗС"
        except Exception as e:
            with self._lock:
                self._is_updating = False
            print(f"[!] Full refresh failed: {e}")
            return False, f"Ошибка обновления: {e}"

    def force_refresh(self):
        """Manual refresh with 10s cooldown"""
        if self._is_updating:
            return False, "Обновление уже выполняется прямо сейчас"
        now = time.time()
        if now - self._last_manual_refresh < 10:
            rem = int(10 - (now - self._last_manual_refresh))
            return False, f"Слишком частые запросы. Подождите {rem} сек."
            
        self._last_manual_refresh = now
        threading.Thread(target=self.update_all, daemon=True).start()
        return True, "Фоновое обновление запущено"

    def _background_scheduler(self):
        # Initial run if cache is empty or older than 12 hours
        if not self._stations:
            print("[*] Initial launch: cache is empty, triggering first data fetch...")
            self.update_all()
            
        while True:
            time.sleep(REFRESH_INTERVAL_SECONDS)
            print("[*] 12-hour timer triggered: updating fuel database in background...")
            self.update_all()

    def get_stations(self, fuel_type=None, brand=None, only_available=False, search=None):
        with self._lock:
            res = list(self._stations)
            
        if brand and brand.lower() != "all":
            b_low = brand.lower()
            res = [s for s in res if b_low in s.get("brand", "").lower()]
            
        if fuel_type and fuel_type.lower() != "all":
            ft = fuel_type.lower()
            if only_available:
                res = [s for s in res if s.get("fuels", {}).get(ft) and s["fuels"][ft].get("available")]
            else:
                res = [s for s in res if s.get("fuels", {}).get(ft)]
        elif only_available:
            res = [s for s in res if any(f and f.get("available") for f in s.get("fuels", {}).values())]
            
        if search:
            q = search.lower().strip()
            res = [
                s for s in res 
                if q in s.get("name", "").lower() 
                or q in s.get("address", "").lower()
                or q in s.get("brand", "").lower()
            ]
            
        return {
            "updated_at": self._last_updated,
            "is_updating": self._is_updating,
            "total_count": len(self._stations),
            "filtered_count": len(res),
            "stations": res
        }

# Global singleton
manager = FuelDataManager()

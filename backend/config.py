from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "nn_fuel_cache.json"
STATIC_DIR = BASE_DIR / "frontend" / "static"

# Geographic bounding box for Nizhny Novgorod metropolitan area
# (includes city center, Avtozavod, Sormovo, Kstovo, Bor, Dzerzhinsk borders)
NN_LAT_MIN = 56.10
NN_LAT_MAX = 56.48
NN_LON_MIN = 43.60
NN_LON_MAX = 44.30

# Center coordinates for Nizhny Novgorod (Minin and Pozharsky Square)
NN_CENTER = [56.3269, 44.0059]

# Background auto-refresh interval in seconds (12 hours)
REFRESH_INTERVAL_SECONDS = 12 * 3600

# Server configuration (local binding for Nginx reverse proxy)
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080

# Production domain
DOMAIN = "gdeflex.orkproxy.nx.kg"

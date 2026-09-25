import os
import sys
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import STATIC_DIR
from backend.data_manager import manager

app = FastAPI(
    title="Мониторинг АЗС Нижний Новгород",
    description="Онлайн карта и каталог актуальных цен и наличия топлива на АЗС Нижнего Новгорода",
    version="1.0.0"
)

# Enable CORS for local testing and mobile web apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.on_event("startup")
async def on_startup():
    manager.start_background_scheduler()

@app.get("/")
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(index_path)

@app.get("/api/stations")
async def get_stations(
    fuel: str = Query(None, description="Тип топлива: 92, 95, 100, dt, lpg или all"),
    brand: str = Query(None, description="Бренд АЗС: Лукойл, Татнефть, Газпромнефть и т.д."),
    available_only: bool = Query(False, description="Только доступное в наличии"),
    search: str = Query(None, description="Текстовый поиск по адресу, названию или бренду")
):
    """
    Возвращает список всех АЗС с ценами и координатами с учетом фильтрации.
    """
    data = manager.get_stations(
        fuel_type=fuel,
        brand=brand,
        only_available=available_only,
        search=search
    )
    return JSONResponse(content=data)

@app.post("/api/refresh")
async def trigger_refresh():
    """
    Принудительное внеочередное обновление цен и статусов топлива с защитой от спама.
    """
    success, message = manager.force_refresh()
    return JSONResponse(
        content={
            "success": success,
            "message": message,
            "is_updating": manager._is_updating,
            "last_updated": manager._last_updated
        },
        status_code=200 if success else 429
    )

@app.get("/api/stats")
async def get_stats():
    """
    Сводная статистика по ценам, доступности и брендам в Нижнем Новгороде.
    """
    stations = manager._stations
    brands_count = {}
    
    price_stats = {
        "92": [],
        "95": [],
        "100": [],
        "dt": [],
        "lpg": []
    }
    
    for s in stations:
        b = s.get("brand", "Прочие")
        brands_count[b] = brands_count.get(b, 0) + 1
        
        fuels = s.get("fuels", {})
        for ft in ["92", "95", "100", "dt", "lpg"]:
            f_info = fuels.get(ft)
            if f_info and f_info.get("available") and f_info.get("price", 0) > 0:
                price_stats[ft].append(f_info["price"])
                
    def calc_stat(arr):
        if not arr:
            return {"min": 0, "max": 0, "avg": 0, "count": 0}
        return {
            "min": round(min(arr), 2),
            "max": round(max(arr), 2),
            "avg": round(sum(arr) / len(arr), 2),
            "count": len(arr)
        }
        
    return JSONResponse(content={
        "total_stations": len(stations),
        "updated_at": manager._last_updated,
        "brands": brands_count,
        "prices": {k: calc_stat(v) for k, v in price_stats.items()}
    })

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "fuel_nn", "time": manager._last_updated}

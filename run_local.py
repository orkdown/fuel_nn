import uvicorn
import webbrowser
import threading
import time

def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  МОНИТОРИНГ ТОПЛИВА АЗС — НИЖНИЙ НОВГОРОД")
    print("  Локальный сервер: http://127.0.0.1:8000")
    print("=" * 60 + "\n")
    
    # Optionally open browser automatically
    # threading.Thread(target=open_browser, daemon=True).start()
    
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, log_level="info")

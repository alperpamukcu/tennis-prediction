@echo off
setlocal EnableExtensions

REM === Proje klasörüne geç ===
cd /d C:\Users\Alper\Desktop\tennis-prediction

REM === PYTHONPATH'i proje köküne ayarla (src.* importları için şart) ===
set PYTHONPATH=%CD%

REM === Venv yoksa oluştur ===
if not exist ".venv\Scripts\python.exe" (
  echo [Setup] Venv olusturuluyor...
  py -3.11 -m venv .venv
)

REM === Uvicorn kurulu değilse bağımlılıkları yükle ===
".venv\Scripts\python.exe" -c "import uvicorn" 2>nul
if errorlevel 1 (
  echo [Setup] Paketler yukleniyor...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo [Run] Backend http://127.0.0.1:8000 adresinde aciliyor...
echo (Hata olursa pencere kapanmayacak.)
echo.

REM === DİKKAT: src.api.app:app ===
".venv\Scripts\python.exe" -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --log-level info

echo.
echo [Bitti] Konsoldaki mesajlari kontrol et.
pause

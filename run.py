# run.py — güvenli giriş noktası
import os, sys

ROOT = os.path.abspath(os.path.dirname(__file__))
SRC  = os.path.join(ROOT, "src")

# src klasörünü import yolunun en başına koy
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Artık paketleri "api", "data", "model" diye doğrudan import edeceğiz:
from api.app import app  # FastAPI instance

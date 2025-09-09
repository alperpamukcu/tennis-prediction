from __future__ import annotations
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from pathlib import Path


# 1) Import your existing FastAPI app and mount it under /api
try:
from src.api.app import app as core_app # your current backend (ping, sports/raw, etc.)
except Exception as exc:
core_app = FastAPI(title="core-app-fallback")
@core_app.get("/ping")
def _ping():
return {"ok": True, "note": "core app failed to import", "error": str(exc)}


# 2) Our new wrapper app
main = FastAPI(title="Tennis Prediction — Composite App")


# CORS (safe defaults)
main.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)


# 3) Mount your existing app under /api (preserves all its routes)
main.mount("/api", core_app)


# 4) New lightweight API router (implied probabilities, health, metrics passthrough)
ui_api = APIRouter(prefix="/api")


@ui_api.get("/health")
async def health():
return {"status": "ok"}


# optional: expose DB metrics if available
try:
from src.data.db import metrics, ensure_db # provided earlier
@ui_api.get("/metrics")
async def _metrics():
ensure_db()
return metrics()
except Exception:
pass


@ui_api.get("/upcoming")
async def upcoming():
"""Return upcoming matches with odds + implied probabilities.
Structure: [{id, start_time, tournament, player_a, player_b, odds_a, odds_b, prob_a, prob_b}]
"""
from src.services.upcoming import get_upcoming_with_probs
return get_upcoming_with_probs()


main.include_router(ui_api)


# 5) Static UI (/ui → index.html)
BASE_DIR = Path(__file__).resolve().parents[1] # .../src
UI_DIR = BASE_DIR / "ui"


# Serve UI at /ui
main.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


# Redirect root → /ui
@main.get("/")
async def _root():
return RedirectResponse(url="/ui")
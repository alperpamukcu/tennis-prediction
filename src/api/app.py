from __future__ import annotations

import importlib
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# -----------------------------------------------------------------------------
# Model & DB (graceful degrade)
# -----------------------------------------------------------------------------
try:
    from src.model.elo_baseline import ELO, MODEL_VERSION as ELO_VERSION  # noqa: F401
except Exception:
    ELO, ELO_VERSION = None, "n/a"  # type: ignore

try:
    from src.data.db import (
        ensure_db,
        insert_prediction,
        insert_result,
        metrics,
        update_elo,
    )
except Exception as exc:
    def ensure_db() -> str:  # type: ignore
        return "disabled"

    def insert_prediction(*args, **kwargs) -> int:  # type: ignore
        return 0

    def insert_result(*args, **kwargs) -> int:  # type: ignore
        return 0

    def metrics() -> Dict[str, Any]:  # type: ignore
        return {"warning": f"db disabled: {exc}"}

    def update_elo(*args, **kwargs) -> Dict[str, Any]:  # type: ignore
        return {"warning": "elo update not available"}

# Hizmetler (graceful import)
try:
    from src.services.predictor import predict_upcoming as _predict_upcoming
except Exception:
    _predict_upcoming = None  # type: ignore

try:
    from src.services.ingest import ingest_once as _ingest_once
except Exception:
    _ingest_once = None  # type: ignore

# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
app = FastAPI(title="Tennis Prediction MVP", version="0.1.0")

# CORS (geliştirme için geniş; prod'da daralt)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _try_import_fetch_odds() -> Optional[Any]:
    """Kullanıcı modülü: src.data.fetch_odds"""
    try:
        return importlib.import_module("src.data.fetch_odds")
    except Exception:
        return None


def _resolve_callable(mod: Any, candidates: List[str]) -> Optional[Callable[..., Any]]:
    """Modül içinden ilk bulunan fonksiyonu döndür."""
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def implied_two_way(odds_a: float, odds_b: float) -> Dict[str, float]:
    """Basit 2-yönlü implied probability (overround normalize)."""
    ia = 1.0 / float(odds_a)
    ib = 1.0 / float(odds_b)
    s = ia + ib
    pa, pb = ia / s, ib / s
    return {"prob_a": round(pa, 4), "prob_b": round(pb, 4)}


def _sample_matches() -> List[Dict[str, Any]]:
    """UI için örnek veri (kaynak yoksa)."""
    now = datetime.utcnow()
    return [
        {
            "id": "m001",
            "start_time": (now + timedelta(hours=2)).isoformat() + "Z",
            "tournament": "ATP 250 — Chengdu",
            "player_a": "A. Karatsev",
            "player_b": "B. Nakashima",
            "odds_a": 1.80,
            "odds_b": 2.05,
        },
        {
            "id": "m002",
            "start_time": (now + timedelta(hours=5)).isoformat() + "Z",
            "tournament": "WTA — Osaka",
            "player_a": "N. Osaka",
            "player_b": "C. Garcia",
            "odds_a": 1.95,
            "odds_b": 1.90,
        },
    ]

# -----------------------------------------------------------------------------
# Lifecycle (scheduler dahil)
# -----------------------------------------------------------------------------
_sched: Optional[AsyncIOScheduler] = None

@app.on_event("startup")
def _startup() -> None:
    # DB hazırla
    try:
        ensure_db()
    except Exception:
        pass

    # Scheduler: her N dakikada bir ingest
    try:
        every = int(os.getenv("INGEST_EVERY_MIN", "10"))
        enable = os.getenv("INGEST_ENABLED", "true").lower() not in ("0", "false", "no")
        if enable and _ingest_once:
            global _sched
            _sched = AsyncIOScheduler()
            _sched.add_job(_ingest_once, "interval", minutes=every, id="ingest-job", coalesce=True, max_instances=1)
            _sched.start()
            # başlangıçta bir defa çalıştır
            _ingest_once()
    except Exception as exc:
        print("Scheduler not started:", exc)


@app.on_event("shutdown")
def _shutdown() -> None:
    try:
        if _sched:
            _sched.shutdown()
    except Exception:
        pass

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"app": "Tennis Prediction MVP", "docs": "/docs", "health": "/ping"}


@app.get("/ping")
def ping() -> Dict[str, Any]:
    return {"ok": True, "elo_version": ELO_VERSION, "time_utc": datetime.utcnow().isoformat() + "Z"}


@app.get("/metrics")
def get_metrics() -> Dict[str, Any]:
    try:
        return metrics()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/sports/raw")
def sports_raw() -> Any:
    """
    Raw spor/maç/odds verisini döndürür.
    src.data.fetch_odds içindeki yaygın fonksiyon adlarını otomatik dener.
    """
    mod = _try_import_fetch_odds()
    if mod is None:
        return {"source": "sample", "items": _sample_matches()}

    fn = _resolve_callable(
        mod,
        [
            "get_sports_raw",
            "get_raw_sports",
            "fetch_sports_raw",
            "list_sports_raw",
            "sports_raw",
            "get_sports",
            "get_raw",
        ],
    )
    if fn is None:
        return {"source": "sample", "items": _sample_matches()}

    try:
        data = fn()
        return {"source": fn.__name__, "items": data}
    except Exception as exc:
        return {"source": fn.__name__, "error": str(exc), "items": _sample_matches()}


@app.get("/upcoming")
def upcoming() -> List[Dict[str, Any]]:
    """
    Yaklaşan maçlar + implied prob (sadece odds'tan).
    fetch_odds içinde uygun fonksiyon yoksa örnek veri döner.
    """
    mod = _try_import_fetch_odds()
    rows: List[Dict[str, Any]] = []
    if mod:
        fn = _resolve_callable(mod, ["get_upcoming", "get_upcoming_odds", "fetch_upcoming", "upcoming"])
        if fn:
            try:
                rows = list(fn())
            except Exception:
                rows = _sample_matches()
        else:
            rows = _sample_matches()
    else:
        rows = _sample_matches()

    out: List[Dict[str, Any]] = []
    for r in rows:
        odds_a = float(r.get("odds_a", 2.0))
        odds_b = float(r.get("odds_b", 2.0))
        probs = implied_two_way(odds_a, odds_b)
        item = {
            "id": r.get("id") or f"m-{len(out)+1:03d}",
            "start_time": r.get("start_time") or (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z",
            "tournament": r.get("tournament") or "Unknown",
            "player_a": r.get("player_a") or "Player A",
            "player_b": r.get("player_b") or "Player B",
            "odds_a": odds_a,
            "odds_b": odds_b,
            **probs,
        }
        item["pick"] = "A" if item["prob_a"] >= item["prob_b"] else "B"
        out.append(item)
    return out


@app.post("/predict/log")
def predict_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Body: {match_id, player_a, player_b, odds_a, odds_b, model?}
    DB'ye implied prob ile bir prediction kaydı atar.
    """
    try:
        match_id = payload["match_id"]
        a = payload["player_a"]
        b = payload["player_b"]
        odds_a = float(payload["odds_a"])
        odds_b = float(payload["odds_b"])
    except Exception:
        raise HTTPException(status_code=400, detail="Required: match_id, player_a, player_b, odds_a, odds_b")

    probs = implied_two_way(odds_a, odds_b)
    model = str(payload.get("model", "implied"))
    version = ELO_VERSION

    try:
        rowid = insert_prediction(
            match_id=match_id,
            player_a=a,
            player_b=b,
            prob_a=probs["prob_a"],
            prob_b=probs["prob_b"],
            model=model,
            version=version,
        )
    except Exception:
        rowid = 0

    return {
        "ok": True,
        "id": rowid,
        "match_id": match_id,
        "players": [a, b],
        "odds": {"a": odds_a, "b": odds_b},
        "probs": probs,
        "pick": "A" if probs["prob_a"] >= probs["prob_b"] else "B",
        "model": model,
        "version": version,
    }


@app.get("/predict/upcoming")
def predict_upcoming_route(w: float = 0.5):
    """
    Model: ELO + implied blend
    ?w=0..1 (1=ELO'ya daha çok güven)
    """
    if not _predict_upcoming:
        raise HTTPException(status_code=500, detail="predictor not available")
    if not (0.0 <= w <= 1.0):
        raise HTTPException(status_code=400, detail="w must be in [0,1]")
    return _predict_upcoming(blend_w=w)


@app.post("/results")
def post_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Body (JSON):
    {
      "match_id": "m001",
      "winner": "A" | "B",
      "score": "6-4 6-4",
      "player_a": "...",
      "player_b": "...",
      "k": 32   # optional
    }
    DB'ye result kaydeder, ELO'yu günceller.
    """
    for key in ("match_id", "winner", "player_a", "player_b"):
        if key not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field: {key}")
    if payload["winner"] not in ("A", "B"):
        raise HTTPException(status_code=400, detail="winner must be 'A' or 'B'")

    try:
        rid = insert_result(
            match_id=payload["match_id"],
            winner=payload["winner"],
            score=payload.get("score"),
            player_a=payload["player_a"],
            player_b=payload["player_b"],
        )
    except Exception:
        rid = 0

    new_ratings: Dict[str, Any] = {}
    try:
        new_ratings = update_elo(
            payload["player_a"],
            payload["player_b"],
            payload["winner"],
            float(payload.get("k", 32.0)),
        )
    except Exception as exc:
        new_ratings = {"error": str(exc)}

    return {"ok": True, "result_id": rid, "ratings": new_ratings}


@app.post("/admin/ingest/once")
def admin_ingest_once():
    """Kullanıcı modülünden veriyi çekip DB'ye yazar (manuel tetik)."""
    if not _ingest_once:
        raise HTTPException(status_code=500, detail="ingest not available")
    return _ingest_once()
# --- Oyuncu sıralaması (model ELO) -------------------------------------------
try:
    from src.data.db import get_top_ratings
except Exception:
    get_top_ratings = None  # type: ignore

@app.get("/rankings/model")
def rankings_model(limit: int = 50):
    if not get_top_ratings:
        raise HTTPException(status_code=500, detail="ratings not available")
    try:
        return {"items": get_top_ratings(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

# --- Tenis ligleri (Odds API proxy) ------------------------------------------
try:
    from src.data.fetch_odds import get_tennis_sports
except Exception:
    get_tennis_sports = None  # type: ignore

@app.get("/sports/tennis")
def tennis_sports(all: bool = True):
    # graceful fallback
    if not get_tennis_sports:
        # basit örnek liste
        sample = [
            {"key": "tennis_atp_wimbledon", "title": "ATP Wimbledon", "active": False},
            {"key": "tennis_wta_indian_wells", "title": "WTA Indian Wells", "active": False},
        ]
        return {"items": sample, "source": "sample"}
    try:
        items = get_tennis_sports(all_=all)
        return {"items": items, "source": "the-odds-api"}
    except Exception as exc:
        # anahtar yoksa da UI çalışsın
        sample = [
            {"key": "tennis_atp_wimbledon", "title": "ATP Wimbledon", "active": False},
            {"key": "tennis_wta_indian_wells", "title": "WTA Indian Wells", "active": False},
        ]
        return {"items": sample, "source": f"fallback: {exc}"}
        # --- Resmi ATP/WTA sıralaması -------------------------------------------------
try:
    from src.data.rankings_official import get_official_rankings
except Exception:
    get_official_rankings = None  # type: ignore

@app.get("/rankings/official")
def rankings_official(tour: str = "ATP", limit: int = 50):
    if not get_official_rankings:
        raise HTTPException(status_code=500, detail="official rankings not available")
    t = tour.upper()
    if t not in ("ATP", "WTA"):
        raise HTTPException(status_code=400, detail="tour must be ATP or WTA")
    try:
        return {"items": get_official_rankings(tour=t, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


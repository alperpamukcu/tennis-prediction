from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import uuid
import datetime as dt

load_dotenv()

# Odds API yardımcıları
from src.data.fetch_odds import (
    get_upcoming_odds,
    get_tennis_sport_keys,
    find_first_nonempty_tennis,
    get_sports,
    OddsApiError,
    extract_players_from_event,  # oyuncu isimlerini event'ten çıkarır
)

# Elo baseline
from src.model.elo_baseline import ELO, MODEL_VERSION

# SQLite yardımcıları
from src.data.db import insert_prediction, insert_result, metrics, ensure_db


app = FastAPI(title="Tennis Prediction MVP", version="0.4.0")


# ---------- APP STARTUP ----------
@app.on_event("startup")
def _startup():
    """DB'yi hazırla ve (varsa) tarihsel CSV'lerden Elo'ları yükle."""
    ensure_db()
    try:
        # data_raw/ altında Sackmann CSV'leri varsa yükler; yoksa herkes 1500 Elo ile başlar
        ELO.load_from_csv_folder("data_raw")
    except Exception:
        # CSV yoksa veya dosya okunamadıysa sessizce geç
        pass


# ---------- HEALTH ----------
@app.get("/ping")
def ping():
    return {
        "status": "ok",
        "env": os.getenv("ENV"),
        "has_odds_key": bool(os.getenv("ODDS_API_KEY")),
    }


# ---------- SPORTS / ODDS ----------
@app.get("/sports")
def sports():
    """Aktif tenis anahtarlarını (sport_key) ve toplam spor sayısını döndürür."""
    try:
        data = get_sports()
        tennis_active = get_tennis_sport_keys(active_only=True)
        return {"tennis_keys_active": tennis_active, "all_sports_len": len(data)}
    except OddsApiError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), "body": e.body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sports/raw")
def sports_raw():
    """Tenis grubundaki ham sport objelerini (key/title/active) döndürür."""
    try:
        data = get_sports()
        tennis = [s for s in data if s.get("group") == "Tennis"]
        return {"tennis_raw": tennis}
    except OddsApiError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), "body": e.body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ÖNCE otomatik endpoint (dinamik route ile çakışmasın)
@app.get("/odds_auto")
def odds_auto(regions: str = Query(default="eu", pattern="^(eu|us|uk|au)$")):
    """
    Aktif tenis sport_key'lerini sırayla dener.
    Veri dönen ilk anahtarı ve ilk birkaç event'i döndürür.
    """
    try:
        info = find_first_nonempty_tennis(regions=regions)
        return info
    except OddsApiError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), "body": e.body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/odds/{sport_key}")
def odds(sport_key: str, regions: str = Query(default="eu", pattern="^(eu|us|uk|au)$")):
    """
    Belirtilen sport_key için yaklaşan maçların H2H odds verisini döndürür.
    Boş liste dönmesi normal olabilir (yaklaşan maç yoksa).
    """
    try:
        data, headers = get_upcoming_odds(sport_key, regions=regions)
        return {
            "sport_key": sport_key,
            "count": len(data) if isinstance(data, list) else 0,
            "data": data,
            "headers": {
                "requests-remaining": headers.get("x-requests-remaining"),
                "requests-used": headers.get("x-requests-used"),
            },
        }
    except OddsApiError as e:
        # 401/402/404 gibi durumlarda net hata ver
        raise HTTPException(status_code=e.status, detail={"message": str(e), "body": e.body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- PREDICT (SINGLE) ----------
class PredictIn(BaseModel):
    player_a: str
    player_b: str
    surface: str | None = None    # "Hard" | "Clay" | "Grass" | "Carpet" | None
    best_of: int = 3
    match_id: str | None = None


@app.post("/predict/match")
def predict_match(body: PredictIn):
    """
    İki oyuncu adı (+opsiyonel yüzey/best_of) alır, Elo ile kazanma olasılıklarını üretir,
    kaydı SQLite'a yazar ve sonucu döndürür.
    """
    # Elo olasılığı
    p_home = float(ELO.prob(body.player_a, body.player_b, body.surface))
    p_away = float(1.0 - p_home)

    # Kaba beklenen değerler (ileride iyileştirilecek)
    exp_sets = 2.0 + abs(0.5 - p_home)          # 2–3 set arası
    exp_games = 22.0 + (p_home - 0.5) * 8.0     # ~18–26 arası oynar

    mid = body.match_id or str(uuid.uuid4())
    row = {
        "match_id": mid,
        "ts": dt.datetime.utcnow().isoformat(),
        "player_a": body.player_a,
        "player_b": body.player_b,
        "surface": body.surface or "",
        "best_of": body.best_of,
        "p_home": p_home,
        "p_away": p_away,
        "exp_sets": float(exp_sets),
        "exp_games": float(exp_games),
        "model_version": MODEL_VERSION,
    }
    insert_prediction(row)

    return {
        "match_id": mid,
        "p_home": p_home,
        "p_away": p_away,
        "exp_sets": exp_sets,
        "exp_games": exp_games,
        "model_version": MODEL_VERSION,
    }


# ---------- PREDICT (BULK / UPCOMING) ----------
@app.post("/predict/upcoming")
def predict_upcoming(
    sport_key: str | None = None,
    regions: str = Query(default="eu", pattern="^(eu|us|uk|au)$"),
    best_of: int = 3
):
    """
    Belirtilen (veya otomatik bulunan) tennis sport_key için yaklaşan maçları alır,
    oyuncuları çıkarır, Elo ile tahmin eder ve SQLite'a kaydeder.
    """
    try:
        # Veri kaynağını bul
        if sport_key:
            events, _hdr = get_upcoming_odds(sport_key, regions=regions)
        else:
            auto = find_first_nonempty_tennis(regions=regions)
            if auto.get("sport_key"):
                sport_key = auto["sport_key"]
                events = auto["data"]
            else:
                return {
                    "sport_key": None,
                    "count": 0,
                    "saved": 0,
                    "note": "Aktif tenis anahtarlarında yaklaşan maç bulunamadı."
                }

        if not isinstance(events, list) or len(events) == 0:
            return {"sport_key": sport_key, "count": 0, "saved": 0, "note": "Bu anahtar için yaklaşan maç yok."}

        # Her event için oyuncuları al -> Elo -> DB'ye yaz
        saved = 0
        items = []
        for ev in events:
            a, b = extract_players_from_event(ev)
            if not a or not b:
                continue

            p_home = float(ELO.prob(a, b, None))  # yüzey bilgisi yoksa None
            p_away = 1.0 - p_home
            exp_sets = 2.0 + abs(0.5 - p_home)
            exp_games = 22.0 + (p_home - 0.5) * 8.0

            mid = ev.get("id") or f"{sport_key}:{ev.get('commence_time')}:{a}-{b}"

            row = {
                "match_id": mid,
                "ts": dt.datetime.utcnow().isoformat(),
                "player_a": a,
                "player_b": b,
                "surface": "",
                "best_of": best_of,
                "p_home": p_home,
                "p_away": p_away,
                "exp_sets": float(exp_sets),
                "exp_games": float(exp_games),
                "model_version": MODEL_VERSION,
            }
            try:
                insert_prediction(row)
                saved += 1
                items.append({"match_id": mid, "player_a": a, "player_b": b, "p_home": p_home})
            except Exception:
                # Aynı match_id daha önce eklendiyse atla
                continue

        return {"sport_key": sport_key, "count": len(events), "saved": saved, "items": items[:10]}
    except OddsApiError as e:
        raise HTTPException(status_code=e.status, detail={"message": str(e), "body": e.body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- RESULTS & METRICS ----------
class ResultIn(BaseModel):
    match_id: str
    winner: str            # player_a veya player_b adı
    sets_total: int | None = None
    games_total: int | None = None


@app.post("/results")
def add_result(body: ResultIn):
    row = {
        "match_id": body.match_id,
        "ts": dt.datetime.utcnow().isoformat(),
        "winner": body.winner,
        "sets_total": body.sets_total or 0,
        "games_total": body.games_total or 0,
    }
    insert_result(row)
    return {"ok": True}


@app.get("/metrics")
def get_metrics():
    """Son 200 eşleşme için basit metrikler (accuracy, brier)."""
    return metrics()

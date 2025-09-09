# src/services/predictor.py
from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

# --- DB kaynakları (graceful fallback) ---------------------------------------
try:
    from src.data.db import get_upcoming_with_latest_odds, get_ratings, BASE_RATING
except Exception:
    get_upcoming_with_latest_odds = None  # type: ignore

    def get_ratings(players):  # type: ignore
        return {p: 1500.0 for p in players}

    BASE_RATING = 1500.0  # type: ignore


# --- Helper'lar ---------------------------------------------------------------
def elo_expected(ra: float, rb: float) -> float:
    """ELO beklenen skor: P(A kazanır)."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def implied_two_way(odds_a: float, odds_b: float) -> Tuple[float, float]:
    """İki-yönlü implied olasılık, normalize."""
    ia = 1.0 / float(odds_a)
    ib = 1.0 / float(odds_b)
    s = ia + ib
    return ia / s, ib / s


def blend(p_elo: float, p_imp: float, w: float = 0.5) -> float:
    """Model karışımı: w*ELO + (1-w)*implied."""
    return max(0.0, min(1.0, w * p_elo + (1.0 - w) * p_imp))


def kelly_fraction(p: float, decimal_odds: float) -> float:
    """Kelly fraksiyonu (0..1 aralığına kırpılmış)."""
    b = max(0.000001, decimal_odds - 1.0)
    q = 1.0 - p
    k = (b * p - q) / b
    return max(0.0, min(1.0, k))


def _try_fetch_upcoming() -> List[Dict[str, Any]]:
    """Kullanıcı modülünden (src.data.fetch_odds) yaklaşan maçları almaya çalış."""
    try:
        mod = importlib.import_module("src.data.fetch_odds")
    except Exception:
        mod = None

    candidates = ["get_upcoming", "get_upcoming_odds", "fetch_upcoming", "upcoming"]
    if mod:
        for name in candidates:
            fn = getattr(mod, name, None)
            if callable(fn):
                try:
                    rows = list(fn())
                    return rows
                except Exception:
                    break

    # Fallback örnek veri
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


# --- Ana fonksiyon ------------------------------------------------------------
def predict_upcoming(blend_w: float = 0.5) -> List[Dict[str, Any]]:
    """
    Dönüş: [{ id, start_time, tournament, player_a, player_b,
              rating_a, rating_b, odds_a, odds_b,
              implied:{a,b}, elo:{a,b}, model:{a,b,w},
              pick, edge, kelly }]
    """
    # 1) DB'den en güncel oranlarla yaklaşan maçlar
    rows: List[Dict[str, Any]] = []
    if get_upcoming_with_latest_odds:
        try:
            rows = get_upcoming_with_latest_odds(hours_ahead=48)
        except Exception:
            rows = []

    # 2) DB boşsa kullanıcı modülünden çek
    if not rows:
        rows = _try_fetch_upcoming()

    # 3) Ratingleri toplu çek
    players: List[str] = []
    for r in rows:
        players.extend([r.get("player_a", "A"), r.get("player_b", "B")])
    rat_map = get_ratings(players)

    # 4) Skorla ve derle
    out: List[Dict[str, Any]] = []
    for r in rows:
        a = str(r.get("player_a") or "A")
        b = str(r.get("player_b") or "B")
        ra = float(rat_map.get(a, BASE_RATING))
        rb = float(rat_map.get(b, BASE_RATING))

        oa = float(r.get("odds_a") or 2.0)
        ob = float(r.get("odds_b") or 2.0)

        pa_imp, pb_imp = implied_two_way(oa, ob)
        pa_elo = elo_expected(ra, rb)
        pb_elo = 1.0 - pa_elo

        pa_model = blend(pa_elo, pa_imp, w=blend_w)
        pb_model = 1.0 - pa_model

        if pa_model >= pb_model:
            pick = "A"
            edge = pa_model - pa_imp
            kelly = kelly_fraction(pa_model, oa)
        else:
            pick = "B"
            edge = pb_model - pb_imp
            kelly = kelly_fraction(pb_model, ob)

        start_time = r.get("start_time") or (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z"

        out.append({
            "id": r.get("id") or f"m-{len(out)+1:03d}",
            "start_time": start_time,
            "tournament": r.get("tournament") or "Unknown",
            "player_a": a,
            "player_b": b,
            "rating_a": round(ra, 1),
            "rating_b": round(rb, 1),
            "odds_a": oa,
            "odds_b": ob,
            "implied": {"a": round(pa_imp, 4), "b": round(pb_imp, 4)},
            "elo": {"a": round(pa_elo, 4), "b": round(pb_elo, 4)},
            "model": {"a": round(pa_model, 4), "b": round(pb_model, 4), "w": blend_w},
            "pick": pick,
            "edge": round(edge, 4),
            "kelly": round(kelly, 4),
        })

    return out

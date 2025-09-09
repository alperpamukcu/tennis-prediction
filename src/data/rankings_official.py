# src/data/rankings_official.py
from __future__ import annotations
import os, requests
from typing import Any, Dict, List

RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY")  # zorunlu
RAPIDAPI_HOST = os.getenv("RAPIDAPI_TENNIS_HOST", "ultimate-tennis1.p.rapidapi.com")
RAPIDAPI_URL  = os.getenv("RAPIDAPI_TENNIS_URL",  f"https://{RAPIDAPI_HOST}/v1/rankings")

def _headers() -> Dict[str, str]:
    if not RAPIDAPI_KEY:
        raise RuntimeError("RAPIDAPI_KEY not set")
    return {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST,
    }

def _normalize(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for x in items:
        # Çoklu sağlayıcı uyumu: muhtemel alan adları
        rank   = x.get("rank") or x.get("position") or x.get("ranking") or x.get("place")
        name   = x.get("name") or x.get("player") or x.get("full_name") or x.get("player_name")
        country= x.get("country") or x.get("nationality") or x.get("country_code")
        points = x.get("points") or x.get("pts") or x.get("score")
        # Bazı JSON'larda iç içe gelebilir:
        if not name and isinstance(x.get("player"), dict):
            name = x["player"].get("name") or x["player"].get("full_name")
            country = country or x["player"].get("country") or x["player"].get("nationality")
        if not (rank and name):
            continue
        out.append({
            "rank": int(rank),
            "player": str(name),
            "country": (country or "").upper(),
            "points": float(points) if points is not None else None,
        })
    # Sıralı olduğundan emin ol
    out.sort(key=lambda r: r["rank"])
    return out

def get_official_rankings(tour: str = "ATP", limit: int = 50) -> List[Dict[str, Any]]:
    """
    tour: 'ATP' | 'WTA'
    Dönüş: [{rank, player, country, points}]
    """
    # RapidAPI isteği
    try:
        h = _headers()
        # Ultimate Tennis: /v1/rankings  (tour param’ı bazı sağlayıcılarda lowercase olabilir)
        params = {"tour": tour.upper()}
        resp = requests.get(RAPIDAPI_URL, headers=h, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # Bazı servisler "items" alanı döner, bazıları liste
        items = data.get("items") if isinstance(data, dict) else data
        items = items or []
        rows = _normalize(items)
        if not rows:
            raise RuntimeError("empty rankings")
        return rows[: int(limit)]
    except Exception:
        # Graceful fallback (örnek kısa liste)
        sample_atp = [
            {"rank": 1, "player": "J. Sinner",   "country": "ITA", "points": None},
            {"rank": 2, "player": "C. Alcaraz",  "country": "ESP", "points": None},
            {"rank": 3, "player": "N. Djokovic", "country": "SRB", "points": None},
        ]
        sample_wta = [
            {"rank": 1, "player": "I. Swiatek",  "country": "POL", "points": None},
            {"rank": 2, "player": "A. Sabalenka","country": "BLR", "points": None},
            {"rank": 3, "player": "C. Gauff",    "country": "USA", "points": None},
        ]
        return (sample_atp if tour.upper() == "ATP" else sample_wta)[: int(limit)]

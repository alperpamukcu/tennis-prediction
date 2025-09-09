# src/data/fetch_odds.py
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

import requests

# --- Config -------------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# Virgülle ayrılmış bölgeler: "eu,uk,us,au"
REGIONS = os.getenv("ODDS_REGIONS", "eu,uk,us")
# Sadece maç sonucu (H2H) kullanıyoruz
MARKETS = os.getenv("ODDS_MARKETS", "h2h")
ODDS_FORMAT = os.getenv("ODDS_FORMAT", "decimal")  # "decimal" | "american"
DATE_FORMAT = "iso"  # commence_time ISO gelsin
# İsteğe bağlı: belirli turnuvaları daraltmak için bir filtre (örn. "atp,wta,grand,slams")
SPORTS_FILTER = os.getenv("ODDS_SPORTS_FILTER", "").lower().strip()


# --- HTTP helper ---------------------------------------------------------------
def _get(path: str, params: Dict[str, Any] | None = None) -> Tuple[Any, Dict[str, str]]:
    if not API_KEY:
        raise RuntimeError(
            "ODDS_API_KEY tanımlı değil. The Odds API v4 anahtarını ortam değişkenine koy."
        )
    p = {"apiKey": API_KEY}
    if params:
        p.update(params)
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, params=p, timeout=20)
    resp.raise_for_status()
    return resp.json(), resp.headers


# --- Sports discovery ----------------------------------------------------------
def list_tennis_sport_keys() -> List[str]:
    """
    Aktif sporların listesinden tenis anahtarlarını seç.
    Örn: 'tennis_atp_wimbledon', 'tennis_wta_indian_wells', ...
    """
    data, _ = _get("/sports", params={})
    keys: List[str] = []
    for s in data:
        key = s.get("key", "")
        if not s.get("active"):
            continue
        if not key.startswith("tennis_"):
            continue
        if SPORTS_FILTER:
            # basit alt-string filtresi
            if not any(tok in key for tok in SPORTS_FILTER.split(",")):
                continue
        keys.append(key)
    return keys


# --- Odds normalizasyonu -------------------------------------------------------
def _extract_h2h_prices(event: Dict[str, Any]) -> Tuple[float | None, float | None, str | None]:
    """
    Bir etkinlikteki bookmaker/market yapısından home/away fiyatlarını çek.
    Tennis'te 'home_team' ve 'away_team' katılımcılardır.
    """
    home = event.get("home_team")
    away = event.get("away_team")
    if not home or not away:
        return None, None, None

    preferred = [
        "pinnacle", "betfair", "unibet", "williamhill", "bet365",
        "marathonbet", "10bet", "matchbook", "skybet", "caesars",
    ]

    books: List[Dict[str, Any]] = event.get("bookmakers") or []
    # Önce tercihli bookmaker'ları sırala
    books_sorted = sorted(
        books,
        key=lambda b: (preferred.index(b.get("key")) if b.get("key") in preferred else 999)
    )

    for bk in books_sorted:
        markets = bk.get("markets") or []
        for m in markets:
            if m.get("key") != "h2h":
                continue
            outcomes = m.get("outcomes") or []
            price_home, price_away = None, None
            for o in outcomes:
                name, price = o.get("name"), o.get("price")
                if name == home:
                    price_home = price
                elif name == away:
                    price_away = price
            if price_home and price_away:
                return float(price_home), float(price_away), (bk.get("title") or bk.get("key"))
    return None, None, None


# --- Public API (ingest bu fonksiyonu arar) -----------------------------------
def get_upcoming(limit_per_sport: int = 200) -> List[Dict[str, Any]]:
    """
    Tüm aktif tenis sport key'leri için H2H odds'larını çeker ve normalize eder.
    Dönüş: [{id, start_time, tournament, player_a, player_b, odds_a, odds_b, source, market, line}]
    """
    sports = list_tennis_sport_keys()
    out: List[Dict[str, Any]] = []

    for skey in sports:
        params = {
            "regions": REGIONS,
            "markets": MARKETS,
            "oddsFormat": ODDS_FORMAT,
            "dateFormat": DATE_FORMAT,
        }
        try:
            events, headers = _get(f"/sports/{skey}/odds", params=params)
        except requests.HTTPError as e:
            # sport o an kapalı olabilir; atla
            continue

        for ev in events[:limit_per_sport]:
            start_iso = ev.get("commence_time")
            home = ev.get("home_team")
            away = ev.get("away_team")
            if not (start_iso and home and away):
                continue

            oa, ob, src = _extract_h2h_prices(ev)
            if oa is None or ob is None:
                continue

            out.append({
                "id": ev.get("id"),
                "start_time": start_iso,  # ISO 8601 (Z)
                "tournament": ev.get("sport_title") or skey.replace("tennis_", "").replace("_", " ").title(),
                "player_a": home,
                "player_b": away,
                "odds_a": oa,
                "odds_b": ob,
                "source": src or "the-odds-api",
                "market": "h2h",
                "line": None,
            })

        # kibar throttle (ücretsiz plan için)
        time.sleep(0.25)

    return out


# Eski adları bekleyen kodlar için alternatif isim
def get_sports_raw() -> Dict[str, Any]:
    return {"items": get_upcoming()}
    # --- Tennis leagues (sports) listesi -----------------------------------------
def get_tennis_sports(all_: bool = True):
    """
    Dönüş: [{"key": "tennis_atp_wimbledon", "title": "ATP Wimbledon", "active": True/False}, ...]
    """
    params = {"all": "true"} if all_ else {}
    data, _ = _get("/sports", params=params)
    out = []
    for s in data:
        if s.get("group") == "Tennis" and str(s.get("key","")).startswith("tennis_"):
            out.append({
                "key": s.get("key"),
                "title": s.get("title") or s.get("description") or s.get("key"),
                "active": bool(s.get("active")),
            })
    return out


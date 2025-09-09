from dotenv import load_dotenv
import os
import requests
from typing import List, Tuple, Dict, Any

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

class OddsApiError(Exception):
    def __init__(self, status: int, message: str, body: str = "", headers: Dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = headers or {}

def _get(url: str, params: Dict[str, Any]) -> Tuple[Any, Dict[str, str]]:
    """GET: JSON + headers; hata durumunda anlamlı istisna fırlatır."""
    if not API_KEY:
        raise OddsApiError(500, "ODDS_API_KEY bulunamadı (.env dosyasını kontrol et).")
    params = {**params, "apiKey": API_KEY}
    r = requests.get(url, params=params, timeout=30)
    hdrs = {k.lower(): v for k, v in r.headers.items()}
    if r.status_code >= 400:
        # odds api genelde açıklayıcı bir metin döndürür
        raise OddsApiError(r.status_code, f"Odds API error {r.status_code}", r.text, hdrs)
    return r.json(), hdrs

def get_sports() -> List[Dict[str, Any]]:
    data, _ = _get(f"{BASE_URL}/sports", params={"all": "true"})
    return data

def get_tennis_sport_keys(active_only: bool = True) -> List[str]:
    sports = get_sports()
    keys = []
    for s in sports:
        if s.get("group") == "Tennis":
            if (not active_only) or s.get("active") is True:
                keys.append(s["key"])
    return keys

def get_upcoming_odds(sport_key: str, regions: str = "eu"):
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "regions": regions,           # eu/us/uk/au
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    return _get(url, params)

def find_first_nonempty_tennis(regions: str = "eu"):
    """
    Aktif tenis sport_key'lerini sırayla dener,
    404 gibi 'bulunamadı' hatalarını atlar; veri bulursa döner.
    401/402 gibi kritik hatalarda ise hemen fırlatır.
    """
    tried = []
    for key in get_tennis_sport_keys(active_only=True):
        tried.append(key)
        try:
            data, headers = get_upcoming_odds(key, regions=regions)
            if isinstance(data, list) and len(data) > 0:
                return {
                    "sport_key": key,
                    "count": len(data),
                    "data": data,
                    "headers": headers,
                    "tried": tried,
                }
        except OddsApiError as e:
            # 404 => bu key odds desteklemiyor/şu an kapalı; devam et
            if e.status == 404:
                continue
            # kota/izin vs. kritik hatalar: yukarı fırlat
            raise
    return {"sport_key": None, "count": 0, "data": [], "headers": {}, "tried": tried}


if __name__ == "__main__":
    info = find_first_nonempty_tennis()
    print(info)
def extract_players_from_event(event: Dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Odds API event objesinden oyuncu isimlerini çıkarır.
    Öncelik: home_team/away_team -> yoksa teams[0/1] -> yoksa None.
    """
    a = None
    b = None
    try:
        if isinstance(event, dict):
            # Bazı sporlarda home/away gelir; teniste de sıkça böyle döner
            a = event.get("home_team")
            b = event.get("away_team")
            if not a or not b:
                teams = event.get("teams")
                if isinstance(teams, list) and len(teams) >= 2:
                    a, b = teams[0], teams[1]
        # Normalize: None yerine str veya None bırak
        a = str(a) if a is not None else None
        b = str(b) if b is not None else None
    except Exception:
        pass
    return a, b

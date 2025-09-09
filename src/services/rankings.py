# src/services/rankings.py
from __future__ import annotations
import csv, io, json, os
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import requests

# -----------------------------------------------------------------------------#
# Generic fetch + parse (CSV or JSON list of dicts)
# -----------------------------------------------------------------------------#
def _http_get(url: str) -> Tuple[bytes, str]:
    headers = {}
    if os.getenv("RAPIDAPI_KEY") and os.getenv("RAPIDAPI_HOST"):
        headers = {
            "X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY", ""),
            "X-RapidAPI-Host": os.getenv("RAPIDAPI_HOST", ""),
        }
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "")

def _parse_csv_bytes(buf: bytes) -> List[Dict[str, Any]]:
    txt = buf.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(txt))
    rows: List[Dict[str, Any]] = []
    for row in reader:
        rows.append(_normalize_row(row))
    return rows

def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    # alan adı varyasyonları
    rank = row.get("rank") or row.get("Rank") or row.get("ranking") or row.get("position")
    name = row.get("player") or row.get("Player") or row.get("name") or row.get("Name") or row.get("player_name")
    country = row.get("country") or row.get("Country") or row.get("nat") or row.get("Nationality")
    points = row.get("points") or row.get("Points") or row.get("pts") or row.get("Pts")
    try:
        r = int(str(rank).strip())
    except Exception:
        r = 0
    try:
        pts = float(str(points).replace(",", "").strip()) if points is not None else None
    except Exception:
        pts = None
    return {
        "rank": r,
        "player": (name or "").strip(),
        "country": (country or "").strip(),
        "points": pts,
    }

def _parse_json_bytes(buf: bytes) -> List[Dict[str, Any]]:
    data = json.loads(buf.decode("utf-8", errors="ignore"))
    rows: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            data = data["items"]
        elif "data" in data and isinstance(data["data"], list):
            data = data["data"]
    if isinstance(data, list):
        for r in data:
            if isinstance(r, dict):
                rows.append(_normalize_row(r))
    return rows

def _load_from_url(url: str) -> List[Dict[str, Any]]:
    buf, ct = _http_get(url)
    if "csv" in ct or url.lower().endswith(".csv"):
        return _parse_csv_bytes(buf)
    return _parse_json_bytes(buf)

def _load_from_local(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        return _parse_csv_bytes(path.read_bytes())
    return _parse_json_bytes(path.read_bytes())

# -----------------------------------------------------------------------------#
# Public API: get_atp_rankings / get_wta_rankings
# -----------------------------------------------------------------------------#
def _fallback_sample(tour: str) -> List[Dict[str, Any]]:
    # minimum örnek (UI ayakta kalsın)
    if tour.lower() == "atp":
        base = [
            {"rank": 1, "player": "J. Sinner",   "country": "ITA", "points": 9870},
            {"rank": 2, "player": "C. Alcaraz",  "country": "ESP", "points": 9050},
            {"rank": 3, "player": "N. Djokovic", "country": "SRB", "points": 8800},
        ]
    else:
        base = [
            {"rank": 1, "player": "I. Swiatek",  "country": "POL", "points": 11025},
            {"rank": 2, "player": "A. Sabalenka","country": "BLR", "points": 8425},
            {"rank": 3, "player": "C. Gauff",    "country": "USA", "points": 7200},
        ]
    return base

def _load_generic(kind: str) -> List[Dict[str, Any]]:
    # 1) URL env
    url_env = os.getenv(f"{kind.upper()}_RANKINGS_URL")
    if url_env:
        try:
            rows = _load_from_url(url_env)
            rows = [r for r in rows if r.get("player")]
            rows.sort(key=lambda r: r.get("rank") or 9999)
            return rows
        except Exception:
            pass
    # 2) local file
    local = Path(__file__).resolve().parents[1] / "data" / f"{kind.lower()}_rankings.csv"
    rows = _load_from_local(local)
    if rows:
        rows = [r for r in rows if r.get("player")]
        rows.sort(key=lambda r: r.get("rank") or 9999)
        return rows
    # 3) fallback
    return _fallback_sample(kind)

def get_atp_rankings(limit: int = 50) -> List[Dict[str, Any]]:
    rows = _load_generic("atp")
    return rows[: int(limit)]

def get_wta_rankings(limit: int = 50) -> List[Dict[str, Any]]:
    rows = _load_generic("wta")
    return rows[: int(limit)]

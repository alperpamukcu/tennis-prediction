# src/services/ingest.py
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
import importlib, hashlib
from datetime import datetime, timezone

# DB helpers
from src.data.db import upsert_match, insert_odds

def _norm_name(x: Optional[str]) -> str:
    return (x or "").strip()

def _ensure_match_id(row: Dict[str, Any]) -> str:
    """
    Sağlanan satırda id yoksa oyuncular + zaman ile deterministik uid üret.
    """
    if row.get("id"):
        return str(row["id"])
    raw = f"{row.get('player_a')}|{row.get('player_b')}|{row.get('start_time')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def _normalize(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Çeşitli provider şemalarını şu şemaya indirger:
    {id, start_time(ISO Z), tournament, player_a, player_b, odds_a, odds_b, source?, market?, line?}
    """
    # -- time
    start = raw.get("start_time") or raw.get("commence_time") or raw.get("time") or raw.get("start")
    if not start:
        return None
    # ISO'ya çevir (mümkün olduğunca)
    if isinstance(start, (int, float)):  # epoch seconds
        start_iso = datetime.fromtimestamp(float(start), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        s = str(start)
        start_iso = s if s.endswith("Z") else (s + "Z" if "T" in s and "Z" not in s else s)

    # -- players
    a = raw.get("player_a") or raw.get("home") or raw.get("player1") or raw.get("a")
    b = raw.get("player_b") or raw.get("away") or raw.get("player2") or raw.get("b")
    if not a or not b:
        return None

    # -- odds (decimal)
    oa = raw.get("odds_a") or raw.get("price_a") or raw.get("home_odds")
    ob = raw.get("odds_b") or raw.get("price_b") or raw.get("away_odds")
    if oa is None or ob is None:
        return None

    out = {
        "id": _ensure_match_id(raw),
        "start_time": start_iso,
        "tournament": raw.get("tournament") or raw.get("league") or "Unknown",
        "player_a": _norm_name(a),
        "player_b": _norm_name(b),
        "odds_a": float(oa),
        "odds_b": float(ob),
        "source": raw.get("source") or raw.get("bookmaker") or "provider",
        "market": raw.get("market") or "h2h",
        "line": raw.get("line"),
    }
    return out

def _fetch_from_user_module() -> List[Dict[str, Any]]:
    """
    Kullanıcının mevcut modülü: src.data.fetch_odds
    get_upcoming / get_sports_raw / fetch_upcoming vb. fonksiyonları otomatik dener.
    """
    try:
        mod = importlib.import_module("src.data.fetch_odds")
    except Exception as exc:
        raise RuntimeError(f"src.data.fetch_odds import edilemedi: {exc}")

    for name in ["get_upcoming", "get_upcoming_odds", "fetch_upcoming", "get_sports_raw", "sports_raw", "get_raw"]:
        fn = getattr(mod, name, None)
        if callable(fn):
            data = fn()
            if isinstance(data, dict) and "items" in data:
                data = data["items"]
            if not isinstance(data, list):
                data = list(data)
            return data
    raise RuntimeError("fetch_odds içinde beklenen bir fonksiyon bulunamadı.")

def ingest_once() -> Dict[str, Any]:
    """
    1) kullanıcı modülünden veriyi al
    2) normalize et
    3) matches ve odds tablolarına yaz
    """
    raw_list = _fetch_from_user_module()
    ok, skipped = 0, 0
    for raw in raw_list:
        row = _normalize(raw)
        if not row:  # eksik alan
            skipped += 1
            continue
        # upsert match
        upsert_match({
            "match_id": row["id"],
            "start_time": row["start_time"],
            "tournament": row["tournament"],
            "player_a": row["player_a"],
            "player_b": row["player_b"],
        })
        # insert odds snapshot
        insert_odds({
            "match_id": row["id"],
            "source": row["source"],
            "market": row["market"],
            "line": row["line"],
            "odds_a": row["odds_a"],
            "odds_b": row["odds_b"],
        })
        ok += 1
    return {"ingested": ok, "skipped": skipped}

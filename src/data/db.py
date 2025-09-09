from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

# -----------------------------------------------------------------------------
# DB setup
# -----------------------------------------------------------------------------
_DB_PATH = os.getenv("DB_PATH")
if not _DB_PATH:
    _DB_PATH = str((Path(__file__).resolve().parents[2] / "tennis.sqlite3"))

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def ensure_db() -> str:
    conn = _get_conn()
    with conn:
        # Maçlar
        conn.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id   TEXT PRIMARY KEY,
            start_time TEXT,
            start_ts   INTEGER,
            tournament TEXT,
            player_a   TEXT,
            player_b   TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_start_ts ON matches(start_ts)")

        # Odds snapshot'ları
        conn.execute("""
        CREATE TABLE IF NOT EXISTS odds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id   TEXT,
            source     TEXT,
            market     TEXT,
            line       TEXT,
            odds_a     REAL,
            odds_b     REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_odds_match_id ON odds(match_id)")

        # Tahmin logları
        conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            match_id    TEXT,
            player_a    TEXT,
            player_b    TEXT,
            prob_a      REAL,
            prob_b      REAL,
            model       TEXT,
            version     TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_match_id ON predictions(match_id)")

        # Maç sonuçları
        conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            match_id    TEXT,
            winner      TEXT,
            score       TEXT,
            player_a    TEXT,
            player_b    TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_results_match_id ON results(match_id)")

        # ELO rating'leri
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            player     TEXT PRIMARY KEY,
            rating     REAL NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.close()
    return _DB_PATH

# -----------------------------------------------------------------------------
# Predictions / Results
# -----------------------------------------------------------------------------
def insert_prediction(*args, **kwargs) -> int:
    keys = ["match_id", "player_a", "player_b", "prob_a", "prob_b", "model", "version"]
    vals = dict(zip(keys, args)) if (args and not kwargs) else {k: kwargs.get(k) for k in keys}
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO predictions (match_id,player_a,player_b,prob_a,prob_b,model,version) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                vals.get("match_id"),
                vals.get("player_a"),
                vals.get("player_b"),
                vals.get("prob_a"),
                vals.get("prob_b"),
                vals.get("model"),
                vals.get("version"),
            ),
        )
        rowid = cur.lastrowid
    conn.close()
    return rowid

def insert_result(*args, **kwargs) -> int:
    keys = ["match_id", "winner", "score", "player_a", "player_b"]
    vals = dict(zip(keys, args)) if (args and not kwargs) else {k: kwargs.get(k) for k in keys}
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO results (match_id,winner,score,player_a,player_b) VALUES (?,?,?,?,?)",
            (
                vals.get("match_id"),
                vals.get("winner"),
                vals.get("score"),
                vals.get("player_a"),
                vals.get("player_b"),
            ),
        )
        rowid = cur.lastrowid
    conn.close()
    return rowid

def metrics() -> Dict[str, Any]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM predictions")
    pred_count, last_pred = cur.fetchone()
    cur.execute("SELECT COUNT(*), MAX(created_at) FROM results")
    res_count, last_res = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM ratings")
    rat_count = cur.fetchone()[0]
    conn.close()
    return {
        "db_path": _DB_PATH,
        "predictions": pred_count or 0,
        "results": res_count or 0,
        "ratings": rat_count or 0,
        "last_prediction_at": last_pred,
        "last_result_at": last_res,
    }

# -----------------------------------------------------------------------------
# ELO Ratings
# -----------------------------------------------------------------------------
BASE_RATING = 1500.0

def get_rating(player: str) -> float:
    conn = _get_conn()
    cur = conn.execute("SELECT rating FROM ratings WHERE player = ?", (player,))
    row = cur.fetchone()
    conn.close()
    return float(row[0]) if row else BASE_RATING

def get_ratings(players: Iterable[str]) -> Dict[str, float]:
    ps = list(dict.fromkeys([p for p in players if p]))
    if not ps:
        return {}
    qmarks = ",".join(["?"] * len(ps))
    conn = _get_conn()
    cur = conn.execute(f"SELECT player, rating FROM ratings WHERE player IN ({qmarks})", ps)
    found = {p: r for p, r in cur.fetchall()}
    conn.close()
    for p in ps:
        if p not in found:
            found[p] = BASE_RATING
    return found

def upsert_rating(player: str, rating: float) -> None:
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO ratings (player, rating) VALUES (?,?)
            ON CONFLICT(player) DO UPDATE SET
                rating = excluded.rating,
                updated_at = CURRENT_TIMESTAMP
            """,
            (player, float(rating)),
        )
    conn.close()

def elo_expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

def update_elo(a: str, b: str, winner: str, k: float = 32.0) -> Dict[str, float]:
    """A ve B için ELO güncelle; yeni rating'leri döndür ve DB'ye yaz."""
    ra, rb = get_rating(a), get_rating(b)
    ea = elo_expected(ra, rb)
    sa = 1.0 if winner == "A" else 0.0
    sb = 1.0 - sa
    new_ra = ra + k * (sa - ea)
    new_rb = rb + k * (sb - (1.0 - ea))
    upsert_rating(a, new_ra)
    upsert_rating(b, new_rb)
    return {"A": new_ra, "B": new_rb, "Ea": ea}

# -----------------------------------------------------------------------------
# Matches & Odds
# -----------------------------------------------------------------------------
def _to_epoch(ts_iso: str) -> int:
    """'YYYY-MM-DDTHH:MM:SSZ' benzeri ISO string → epoch seconds."""
    try:
        if ts_iso.endswith("Z"):
            dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(ts_iso)
        return int(dt.timestamp())
    except Exception:
        return int(datetime.now(tz=timezone.utc).timestamp())

def upsert_match(d: Dict[str, Any]) -> None:
    """d: {match_id, start_time, tournament, player_a, player_b}"""
    start_time = str(d.get("start_time"))
    start_ts = int(d.get("start_ts") or _to_epoch(start_time))
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO matches (match_id, start_time, start_ts, tournament, player_a, player_b)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                start_time = excluded.start_time,
                start_ts   = excluded.start_ts,
                tournament = excluded.tournament,
                player_a   = excluded.player_a,
                player_b   = excluded.player_b
            """,
            (
                str(d.get("match_id")),
                start_time,
                start_ts,
                d.get("tournament"),
                d.get("player_a"),
                d.get("player_b"),
            ),
        )
    conn.close()

def insert_odds(d: Dict[str, Any]) -> int:
    """d: {match_id, source, market, line, odds_a, odds_b}"""
    conn = _get_conn()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO odds (match_id, source, market, line, odds_a, odds_b)
            VALUES (?,?,?,?,?,?)
            """,
            (
                d.get("match_id"),
                d.get("source"),
                d.get("market"),
                d.get("line"),
                float(d.get("odds_a")),
                float(d.get("odds_b")),
            ),
        )
        rowid = cur.lastrowid
    conn.close()
    return rowid

def get_upcoming_with_latest_odds(hours_ahead: int = 48, limit: int = 200) -> List[Dict[str, Any]]:
    """Önümüzdeki X saat içindeki maçlar + her maç için en son eklenmiş odds."""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    up_to = now + hours_ahead * 3600
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        WITH last_odds AS (
          SELECT o.*
          FROM odds o
          JOIN (
            SELECT match_id, MAX(id) AS max_id
            FROM odds
            GROUP BY match_id
          ) x ON x.match_id = o.match_id AND x.max_id = o.id
        )
        SELECT m.match_id, m.start_time, m.start_ts, m.tournament, m.player_a, m.player_b,
               lo.source, lo.market, lo.line, lo.odds_a, lo.odds_b
        FROM matches m
        LEFT JOIN last_odds lo ON lo.match_id = m.match_id
        WHERE m.start_ts BETWEEN ? AND ?
        ORDER BY m.start_ts ASC
        LIMIT ?
        """,
        (now, up_to, limit),
    )
    rows = [
        {
            "id": r[0],
            "start_time": r[1],
            "start_ts": r[2],
            "tournament": r[3],
            "player_a": r[4],
            "player_b": r[5],
            "source": r[6],
            "market": r[7],
            "line": r[8],
            "odds_a": r[9],
            "odds_b": r[10],
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return rows
# --- Top ratings (model ELO sıralaması) --------------------------------------
def get_top_ratings(limit: int = 50) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.execute(
        "SELECT player, rating, updated_at FROM ratings ORDER BY rating DESC LIMIT ?",
        (int(limit),),
    )
    rows = [{"player": p, "rating": float(r), "updated_at": u} for (p, r, u) in cur.fetchall()]
    conn.close()
    return rows

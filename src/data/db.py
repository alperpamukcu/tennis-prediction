from __future__ import annotations
import sqlite3, pathlib, datetime
from typing import Optional, Tuple, List, Dict, Any

DB_PATH = pathlib.Path("data") / "app.sqlite"

def ensure_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS predictions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        ts TEXT,
        player_a TEXT,
        player_b TEXT,
        surface TEXT,
        best_of INTEGER,
        p_home REAL,
        p_away REAL,
        exp_sets REAL,
        exp_games REAL,
        model_version TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT UNIQUE,
        ts TEXT,
        winner TEXT,
        sets_total INTEGER,
        games_total INTEGER
    )
    """)
    con.commit()
    return con

CON: sqlite3.Connection = ensure_db()

def insert_prediction(row: Dict[str, Any]) -> int:
    cur = CON.cursor()
    cur.execute("""
        INSERT INTO predictions(match_id, ts, player_a, player_b, surface, best_of,
            p_home, p_away, exp_sets, exp_games, model_version)
        VALUES(:match_id, :ts, :player_a, :player_b, :surface, :best_of,
            :p_home, :p_away, :exp_sets, :exp_games, :model_version)
    """, row)
    CON.commit()
    return cur.lastrowid

def insert_result(row: Dict[str, Any]) -> int:
    cur = CON.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO results(match_id, ts, winner, sets_total, games_total)
        VALUES(:match_id, :ts, :winner, :sets_total, :games_total)
    """, row)
    CON.commit()
    return cur.lastrowid

def metrics() -> Dict[str, Any]:
    cur = CON.cursor()
    cur.execute("""
    SELECT p.match_id, p.player_a, p.player_b, p.p_home, p.p_away, r.winner
    FROM predictions p JOIN results r ON p.match_id = r.match_id
    ORDER BY r.ts DESC LIMIT 200
    """)
    rows = cur.fetchall()
    if not rows:
        return {"count": 0, "accuracy": None, "brier": None}
    correct = 0
    brier_sum = 0.0
    for match_id, a, b, p_home, p_away, winner in rows:
        pred_prob = p_home if winner == a else p_away
        pred_cls  = a if p_home >= 0.5 else b
        if pred_cls == winner:
            correct += 1
        # Brier (binary) - winner için 1 kabul ettik
        y = 1.0
        p = pred_prob
        brier_sum += (p - y) ** 2
    n = len(rows)
    return {"count": n, "accuracy": correct / n, "brier": brier_sum / n}

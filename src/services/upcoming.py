from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Dict


# If you already have real odds in src.data.fetch_odds, you can wire them here.
# This module provides a safe fallback dataset so the UI works out of the box.


@dataclass
class Match:
id: str
start_time: str # ISO string UTC
tournament: str
player_a: str
player_b: str
odds_a: float # decimal odds
odds_b: float # decimal odds




def _now_utc() -> datetime:
# naive UTC; FastAPI/JS will render in local
return datetime.utcnow()




def _sample() -> List[Match]:
t0 = _now_utc() + timedelta(hours=2)
t1 = _now_utc() + timedelta(hours=5)
t2 = _now_utc() + timedelta(hours=8)
return [
Match("m001", t0.isoformat() + "Z", "ATP 250 — Chengdu", "A. Karatsev", "B. Nakashima", 1.80, 2.05),
Match("m002", t1.isoformat() + "Z", "WTA — Osaka", "N. Osaka", "C. Garcia", 1.95, 1.90),
Match("m003", t2.isoformat() + "Z", "Challenger — Istanbul", "A. Ilkel", "D. Altmaier", 2.40, 1.55),
]




def _implied_probs(odds_a: float, odds_b: float) -> Dict[str, float]:
# Basic two‑way market normalization (no overround removal)
ia = 1.0 / float(odds_a)
ib = 1.0 / float(odds_b)
s = ia + ib
return {"prob_a": round(ia / s, 4), "prob_b": round(ib / s, 4)}




def get_upcoming_with_probs() -> List[Dict]:
"""Try to use your real odds fetcher if present; otherwise use sample."""
matches: List[Match]
try:
# Example wiring (adapt to your real function signatures):
# from src.data.fetch_odds import get_upcoming
# rows = get_upcoming() # your list of dicts
# matches = [Match(
# id=row["id"],
# start_time=row["start_time"],
# tournament=row["tournament"],
# player_a=row["player_a"],
# player_b=row["player_b"],
# odds_a=float(row["odds_a"]),
# odds_b=float(row["odds_b"]),
# ) for row in rows]
raise ImportError # force fallback until you wire real source
except Exception:
matches = _sample()


out: List[Dict] = []
for m in matches:
d = asdict(m)
d.update(_implied_probs(m.odds_a, m.odds_b))
d["pick"] = "A" if d["prob_a"] >= d["prob_b"] else "B"
out.append(d)
return out
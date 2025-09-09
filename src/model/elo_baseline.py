from __future__ import annotations
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Tuple

K = 32.0
START = 1500.0
MODEL_VERSION = "elo_v0"

SURFACES = ["Hard", "Clay", "Grass", "Carpet"]

class EloModel:
    def __init__(self):
        self.global_elo: Dict[str, float] = {}
        self.surface_elo: Dict[Tuple[str, str], float] = {}  # (name,surface)->elo

    def _get(self, name: str, surface: str | None = None) -> float:
        if surface and (name, surface) in self.surface_elo:
            return self.surface_elo[(name, surface)]
        return self.global_elo.get(name, START)

    def _set(self, name: str, new: float, surface: str | None = None):
        if surface:
            self.surface_elo[(name, surface)] = new
        else:
            self.global_elo[name] = new

    def prob(self, a: str, b: str, surface: str | None = None) -> float:
        ra = self._get(a, surface)
        rb = self._get(b, surface)
        return 1.0 / (1.0 + 10.0 ** (-(ra - rb) / 400.0))

    def update(self, winner: str, loser: str, surface: str | None = None):
        pa = self.prob(winner, loser, surface)
        ra = self._get(winner, surface)
        rb = self._get(loser, surface)
        ra_new = ra + K * (1 - pa)
        rb_new = rb + K * (0 - (1 - pa))
        self._set(winner, ra_new, surface)
        self._set(loser, rb_new, surface)

    def load_from_csv_folder(self, folder: str = "data_raw"):
        path = Path(folder)
        if not path.exists():
            return
        files = sorted(list(path.glob("*matches*.csv")))
        if not files:
            return
        for f in files:
            try:
                df = pd.read_csv(f)
            except Exception:
                continue
            req_cols = {"winner_name", "loser_name"}
            if not req_cols.issubset(set(df.columns)):
                continue
            surface_col = "surface" if "surface" in df.columns else None
            df = df[["winner_name", "loser_name", surface_col] if surface_col else ["winner_name", "loser_name"]]
            for row in df.itertuples(index=False):
                w = getattr(row, "winner_name")
                l = getattr(row, "loser_name")
                s = getattr(row, "surface") if surface_col else None
                s = s if s in SURFACES else None
                self.update(str(w), str(l), s)

# tekil model (app start’ta yüklenecek)
ELO = EloModel()

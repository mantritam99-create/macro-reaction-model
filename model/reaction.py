"""The three models, each a groupby over the event panel.

  reaction_matrix() -- "correlation with the respective market": for every
                       event_type x market x horizon, regress the move on the
                       standardized surprise. beta = move per 1-sigma surprise;
                       r2 = how much it explains; hit = sign agreement; n = sample.
                       A low-r2 cell is the honest signal that the event is noise
                       for that market -- it is not hidden.

  surprise_index()  -- "smaller reports cumulate": a time-decayed running sum of
                       standardized surprises per region. The Citi-ESI analog; the
                       regime variable that also flips the reaction matrix sign
                       (the late-cycle "good news is bad news" effect).

  diffusion()       -- breadth: rolling % of releases surprising to the upside.
                       The simple nowcast -- where small/timely prints forecast the
                       laggy headline ones.

OLS is plain numpy.lstsq -- no statsmodels dependency, matching the repo's
keep-it-light posture.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from config import CFG

_MIN = CFG["reaction"]["min_events"]
_HL = CFG["regime"]["surprise_index_halflife_d"]
_DIFF_W = CFG["regime"]["diffusion_window"]


def _ols(x: np.ndarray, y: np.ndarray):
    """Simple linear fit y = a + b*x. Returns dict or None if too few points."""
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    if len(x) < _MIN:
        return None
    A = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    hit = float((np.sign(x) == np.sign(y)).mean())
    return {"alpha": float(coef[0]), "beta": float(coef[1]),
            "r2": r2, "hit": hit, "n": int(len(x))}


def reaction_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (etype, mkt, h), g in panel.groupby(["event_type", "market", "horizon"]):
        fit = _ols(g["surprise_z"].to_numpy(float), g["ret"].to_numpy(float))
        if fit is None:
            continue
        prov = g["provider"]
        provider = ("csv" if (prov == "csv").all()
                    else "feed" if (prov == "feed").all()
                    else "proxy" if (prov == "proxy").all() else "mixed")
        counts = prov.value_counts()
        rows.append({"event_type": etype, "market": mkt, "horizon": h,
                     "beta_pct": fit["beta"] * 100,   # % move per +1 sigma surprise
                     "r2": fit["r2"], "hit": fit["hit"], "n": fit["n"],
                     "provider": provider,
                     "csv_n": int(counts.get("csv", 0)),
                     "feed_n": int(counts.get("feed", 0)),
                     "proxy_n": int(counts.get("proxy", 0))})
    out = pd.DataFrame(rows)
    return out.sort_values(["r2", "horizon"], ascending=[False, True]) if len(out) else out


def surprise_index(panel: pd.DataFrame) -> pd.DataFrame:
    """One decayed cumulative-surprise track per region (deduped to one row per
    release, so a multi-market panel doesn't double-count a single print)."""
    base = (panel.drop_duplicates(["event_type", "release_dt"])
                 .sort_values("release_dt"))
    out = {}
    for region, g in base.groupby("region"):
        s = pd.Series(g["surprise_z"].values,
                      index=pd.to_datetime(g["release_dt"])).sort_index()
        out[region] = s.ewm(halflife=pd.Timedelta(days=_HL), times=s.index).mean()
    return out  # dict: region -> Series


def diffusion(panel: pd.DataFrame) -> dict:
    """Rolling share of recent releases that surprised positive, per region (0..1).
    >0.5 = more upside surprises than down = 'good news' breadth."""
    base = (panel.drop_duplicates(["event_type", "release_dt"])
                 .sort_values("release_dt"))
    out = {}
    for region, g in base.groupby("region"):
        up = pd.Series((g["surprise_z"].values > 0).astype(float),
                       index=pd.to_datetime(g["release_dt"])).sort_index()
        out[region] = up.rolling(_DIFF_W, min_periods=max(3, _DIFF_W // 2)).mean()
    return out

"""The event panel: one row per economic release, the surprise it carried, and
how each market moved around it. Every model downstream is a groupby over this.

Also exposes:
  event_surprises(...) -- the per-event surprise series (reused by the dashboard
                          and the projection, not just the panel build)
  latest_status()      -- per-event: latest published print, its first-print
                          actual, release date, source URL, and whether you've
                          logged a consensus yet. This is what the dashboard's
                          alert/input panel renders.

CATALOG note: US series have rich first-print vintages on FRED. Several India
series (IIP, WPI, RBI repo) lack reliable vintages -> they belong in the manual
CSV, left out of the auto catalog for now. India CPI is included best-effort.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from config import CFG, DATA_DIR
from data import fetch_fred, fetch_market
from data import consensus as cons

_Z_LB = CFG["surprise"]["z_lookback"]
_Z_MIN = CFG["surprise"]["z_min_periods"]
_HORIZONS = CFG["reaction"]["horizons"]

# Price-like markets only, so a window "return" is always a clean pct move.
MARKETS = {
    "SPX": "^GSPC", "NDX": "^IXIC", "SOX": "^SOX", "DXY": "DX-Y.NYB",
    "NIFTY": "^NSEI", "BANK": "^NSEBANK", "INR": "INR=X",
}
_US_MKTS = ["SPX", "NDX", "SOX", "DXY", "NIFTY", "INR"]   # US prints get India too
_IN_MKTS = ["NIFTY", "BANK", "INR"]

# event_type, fred_id, region, transform, proxy_method, tier, markets
EVENT_CATALOG = [
    ("US_CPI",      "CPIAUCSL",        "US", "mom_pct", "rw_drift", 1, _US_MKTS),
    ("US_CORE_CPI", "CPILFESL",        "US", "mom_pct", "rw_drift", 1, _US_MKTS),
    ("US_PCE_CORE", "PCEPILFE",        "US", "mom_pct", "rw_drift", 1, _US_MKTS),
    ("US_NFP",      "PAYEMS",          "US", "diff",    "rw_drift", 1, _US_MKTS),
    ("US_UNRATE",   "UNRATE",          "US", "none",    "rw",       1, _US_MKTS),
    ("US_RETAIL",   "RSAFS",           "US", "mom_pct", "rw_drift", 2, _US_MKTS),
    ("US_CLAIMS",   "ICSA",            "US", "none",    "rw",       2, _US_MKTS),
    ("IN_CPI",      "INDCPIALLMINMEI", "IN", "yoy_pct", "seasonal", 1, _IN_MKTS),
]

# Human label, display unit, and the OFFICIAL release page for each event.
META = {
    "US_CPI":      ("US CPI (headline, MoM)",    "MoM %",       "https://www.bls.gov/cpi/"),
    "US_CORE_CPI": ("US Core CPI (MoM)",         "MoM %",       "https://www.bls.gov/cpi/"),
    "US_PCE_CORE": ("US Core PCE (MoM)",         "MoM %",       "https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    "US_NFP":      ("US Nonfarm Payrolls",       "change (000)","https://www.bls.gov/news.release/empsit.toc.htm"),
    "US_UNRATE":   ("US Unemployment Rate",      "%",           "https://www.bls.gov/cps/"),
    "US_RETAIL":   ("US Retail Sales (MoM)",     "MoM %",       "https://www.census.gov/retail/sales.html"),
    "US_CLAIMS":   ("US Initial Jobless Claims", "level",       "https://www.dol.gov/ui/data.pdf"),
    "IN_CPI":      ("India CPI (YoY)",           "YoY %",       "https://www.mospi.gov.in/"),
}


def _transform(s: pd.Series, how: str) -> pd.Series:
    if how == "none":    return s
    if how == "mom_pct": return s.pct_change() * 100
    if how == "yoy_pct": return (s / s.shift(12) - 1) * 100
    if how == "diff":    return s.diff()
    raise ValueError(how)


def _zscore(surprise_raw: pd.Series) -> pd.Series:
    """Standardize using only PAST surprises (shift(1)) -> no lookahead, and makes
    CPI vs NFP surprises comparable (each in units of its own history's sigma)."""
    mu = surprise_raw.shift(1).rolling(_Z_LB, min_periods=_Z_MIN).mean()
    sd = surprise_raw.shift(1).rolling(_Z_LB, min_periods=_Z_MIN).std()
    return (surprise_raw - mu) / sd


def event_surprises(etype, fid, how, pmethod) -> pd.DataFrame | None:
    """Per-period surprise frame for one event, indexed by reference period:
       actual (first-print, transformed), consensus, surprise_raw, surprise_z,
       released (publication date), provider ('csv'|'proxy')."""
    rel = fetch_fred.releases(fid)
    if rel is None or rel.empty:
        return None
    metric = _transform(rel["value"], how).dropna()
    if metric.empty:
        return None
    consensus, provider = cons.consensus_for(etype, metric,
                                             {"consensus": "csv", "proxy_method": pmethod})
    surprise_raw = (metric - consensus)
    z = _zscore(surprise_raw)
    df = pd.DataFrame({
        "actual": metric, "consensus": consensus,
        "surprise_raw": surprise_raw, "surprise_z": z,
        "released": rel["released"].reindex(metric.index), "provider": provider,
    })
    return df.sort_index()


def _window_return(px: pd.Series, release_dt, horizon: int):
    """Close-to-close pct move from the last close BEFORE the release to the close
    `horizon` trading days on/after it. NaN if the release sits outside price data."""
    if px is None or len(px) == 0:
        return np.nan
    px = px.sort_index()
    pos = px.index.searchsorted(release_dt)
    if pos <= 0 or pos >= len(px):
        return np.nan
    pre = px.iloc[pos - 1]
    end = min(pos - 1 + horizon, len(px) - 1)
    return px.iloc[end] / pre - 1.0


def build_panel() -> pd.DataFrame:
    """Assemble the full event panel: one row per (release, market, horizon)."""
    px = {k: fetch_market.history(t) for k, t in MARKETS.items()}
    rows = []
    for etype, fid, region, how, pmethod, tier, mkts in EVENT_CATALOG:
        es = event_surprises(etype, fid, how, pmethod)
        if es is None:
            print(f"  [events] {etype}: no FRED data, skipped")
            continue
        es = es.dropna(subset=["surprise_z", "released"])
        for period, r in es.iterrows():
            for mkt in mkts:
                for h in _HORIZONS:
                    ret = _window_return(px.get(mkt), r["released"], h)
                    if np.isnan(ret):
                        continue
                    rows.append({
                        "event_type": etype, "region": region, "tier": tier,
                        "period": period, "release_dt": r["released"],
                        "surprise_raw": r["surprise_raw"], "surprise_z": r["surprise_z"],
                        "provider": r["provider"], "market": mkt, "horizon": h, "ret": ret,
                    })
    panel = pd.DataFrame(rows)
    if not panel.empty:
        panel = panel.sort_values("release_dt").reset_index(drop=True)
        panel.to_csv(os.path.join(DATA_DIR, "event_panel.csv"), index=False)
    return panel


def latest_status() -> list[dict]:
    """One row per event for the dashboard's alert/input panel: the most recent
    published print, its first-print actual, release date, source URL, and whether
    a consensus has been logged. Newest releases first."""
    out = []
    for etype, fid, region, how, pmethod, tier, _ in EVENT_CATALOG:
        es = event_surprises(etype, fid, how, pmethod)
        label, unit, url = META[etype]
        if es is None or es.empty:
            out.append({"event_type": etype, "label": label, "unit": unit,
                        "url": url, "status": "no data"})
            continue
        last = es.dropna(subset=["actual"]).iloc[-1]
        period = es.dropna(subset=["actual"]).index[-1]
        logged = last["provider"] == "csv"
        out.append({
            "event_type": etype, "label": label, "unit": unit, "url": url,
            "region": region, "tier": tier,
            "period": period.strftime("%Y-%m-%d"),
            "period_label": period.strftime("%b %Y"),
            "actual": round(float(last["actual"]), 3),
            "released": last["released"].strftime("%Y-%m-%d") if pd.notna(last["released"]) else "-",
            "consensus": round(float(last["consensus"]), 3) if logged else None,
            "surprise_z": round(float(last["surprise_z"]), 2) if pd.notna(last["surprise_z"]) else None,
            "logged": logged,
        })
    out.sort(key=lambda d: d.get("released", ""), reverse=True)
    return out


if __name__ == "__main__":
    p = build_panel()
    print(f"\nevent panel: {len(p)} rows, "
          f"{p['event_type'].nunique() if len(p) else 0} event types")
    for s in latest_status():
        flag = "LOGGED" if s.get("logged") else "needs input"
        print(f"  {s['label']:28s} {s.get('period_label','-'):9s} "
              f"actual={s.get('actual','-')!s:>9}  [{flag}]")

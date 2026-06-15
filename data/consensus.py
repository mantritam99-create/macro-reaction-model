"""The consensus layer — the hardest input, made pluggable.

The whole model hinges on  surprise = actual - consensus.  FRED gives actuals
for free but NOT the market's consensus, so consensus comes from one of three
providers, swappable per event without touching anything downstream:

  PROXY  (default, free, runs today) -- a transparent walk-forward forecast built
         only from PRIOR first-prints. Honest and reproducible, but it is a
         *model's* expectation, not the street's. Good v1; label it as such.
  CSV    -- you log real street consensus monthly into consensus_log.csv
         (the india-dashboard manual-update pattern). Real expectations, free.
  FEED   -- stub for a real calendar API (Trading Economics / Investing.com /
         FXMacroData). Fill in fetch_feed() when you wire one up.

A "proxy" surprise and a "street" surprise are different objects — never mix them
in one reaction cell. The provider used is carried on every event row so the
report can flag it.
"""
import os
import numpy as np
import pandas as pd
from config import DATA_DIR


# ----------------------------------------------------------------- PROXY -----
def proxy(metric: pd.Series, method: str = "rw_drift", k: int = 6) -> pd.Series:
    """Walk-forward consensus from past first-prints only (no lookahead).

    metric : the *traded* transform of the series (e.g. CPI MoM%, payroll change).
    method : 'rw'        -> last value
             'rw_drift'  -> last value + recent average change   (default)
             'seasonal'  -> value 12 periods ago (for YoY-style series)
    Returns a forecast aligned to metric.index; the first few are NaN by design.
    """
    v = metric.sort_index()
    if method == "rw":
        f = v.shift(1)
    elif method == "rw_drift":
        f = v.shift(1) + v.diff().shift(1).rolling(k, min_periods=2).mean()
    elif method == "seasonal":
        f = v.shift(12)
    else:
        raise ValueError(f"unknown proxy method: {method}")
    return f.reindex(v.index)


# ------------------------------------------------------------------- CSV -----
_CSV = os.path.join(DATA_DIR, "consensus_log.csv")


def csv_consensus(event_type: str) -> pd.Series | None:
    """Street consensus you logged by hand. CSV columns: event_type, period,
    consensus. Returns a period-indexed Series for one event_type, or None if the
    file/rows are absent (caller then falls back to proxy)."""
    if not os.path.exists(_CSV):
        return None
    df = pd.read_csv(_CSV)
    df = df[df["event_type"] == event_type]
    if df.empty:
        return None
    s = pd.Series(df["consensus"].values,
                  index=pd.to_datetime(df["period"])).sort_index()
    return pd.to_numeric(s, errors="coerce").dropna()


# ------------------------------------------------------------------ FEED -----
def fetch_feed(event_type: str) -> pd.Series | None:
    """Stub: real historical street consensus from a calendar API.

    Implement against whatever source you settle on (Trading Economics has a
    clean actual/consensus history; Investing.com/FXMacroData are alternatives).
    Return a period-indexed Series of consensus values, or None.
    """
    return None


# --------------------------------------------------------------- dispatch ----
def consensus_for(event_type: str, metric: pd.Series, spec: dict):
    """Resolve consensus for one event, blended PER PERIOD.

    Manual (csv) or feed consensus is used where it exists; the proxy fills every
    period it doesn't. So the day you log one real consensus number, that print's
    surprise gets sharp while 25 years of history stay intact on the proxy.

    Returns (consensus_series, provider_series) — provider is per-period
    ('csv' | 'feed' | 'proxy') so the report can show exactly which prints are
    backed by real street numbers vs the proxy.
    """
    proxy_s = proxy(metric, spec.get("proxy_method", "rw_drift"))
    want = spec.get("consensus", "proxy")
    override = csv_consensus(event_type) if want == "csv" else \
        (fetch_feed(event_type) if want == "feed" else None)

    if override is None:
        return proxy_s, pd.Series("proxy", index=metric.index)

    override = override.reindex(metric.index)
    blended = override.combine_first(proxy_s)
    provider = pd.Series(np.where(override.notna(), want, "proxy"),
                         index=metric.index)
    return blended, provider


def log_consensus(event_type: str, period, consensus: float) -> None:
    """Upsert one street-consensus number into consensus_log.csv (the manual log).
    period is the release's reference period (e.g. the CPI month)."""
    period = pd.to_datetime(period).strftime("%Y-%m-%d")
    row = {"event_type": event_type, "period": period, "consensus": float(consensus)}
    if os.path.exists(_CSV):
        df = pd.read_csv(_CSV, dtype={"period": str})
        mask = (df["event_type"] == event_type) & (df["period"] == period)
        df = pd.concat([df[~mask], pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.sort_values(["event_type", "period"]).to_csv(_CSV, index=False)

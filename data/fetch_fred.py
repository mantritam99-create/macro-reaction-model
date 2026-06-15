"""FRED via the official API (api.stlouisfed.org). Requires a free key.

Two fetch modes:
  series()   -> latest/revised values (a normal date-indexed Series)
  releases() -> INITIAL-RELEASE values only (output_type=4), each tagged with the
                date it was first published. This is what the event study uses, so
                the backtest never sees a number that didn't exist on release day.

With no key configured every call returns None and the caller skips that series
(never crashes). The keyless fredgraph CSV subdomain is firewalled here, hence the
authenticated JSON API.
"""
import os, sys, time, json, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import cache_util as cache
from config import CFG, fred_key, has_fred

_HDR = {"User-Agent": "Mozilla/5.0"}
_START = CFG["fred"]["start"]
_MAX = CFG["cache"]["fred_max_age_h"]
_BASE = "https://api.stlouisfed.org/fred/series/observations"
_warned = False


def _warn_once():
    global _warned
    if not _warned:
        print("  [fred] no API key (config.yaml fred.api_key or $FRED_API_KEY) "
              "-> FRED series skipped")
        _warned = True


def series(series_id: str, start: str | None = None) -> pd.Series | None:
    """Latest/revised observations as a date-indexed Series."""
    if not has_fred():
        _warn_once(); return None
    key = f"fred_{series_id}"
    s = cache.get_series(key, _MAX)
    if s is not None:
        return s
    q = urllib.parse.urlencode({
        "series_id": series_id, "api_key": fred_key(), "file_type": "json",
        "observation_start": start or _START,
    })
    try:
        req = urllib.request.Request(f"{_BASE}?{q}", headers=_HDR)
        with urllib.request.urlopen(req, timeout=25) as r:
            obs = json.loads(r.read().decode("utf-8"))["observations"]
        idx = pd.to_datetime([o["date"] for o in obs])
        vals = pd.to_numeric(pd.Series([o["value"] for o in obs], index=idx),
                             errors="coerce").dropna()
        return cache.put_series(key, vals)
    except Exception as e:
        print(f"  [fred] {series_id} failed: {e.__class__.__name__}: {str(e)[:80]}")
        return cache.get_series(key, 1e9)


def releases(series_id: str, start: str | None = None) -> pd.DataFrame | None:
    """Initial-release (first-print) observations.

    Returns DataFrame indexed by reference `period` with columns:
        value     -> the number as first published (no later revisions)
        released  -> the date that first print became public (the release date)

    Uses output_type=4 over the full real-time range so each observation carries
    its original publication date. Series without a revision history on FRED
    (some non-US series) degrade gracefully to their single available vintage.
    """
    if not has_fred():
        _warn_once(); return None
    key = f"fredrel_{series_id}"
    cached = cache.get_json(key, _MAX)
    if cached is None:
        q = urllib.parse.urlencode({
            "series_id": series_id, "api_key": fred_key(), "file_type": "json",
            "observation_start": start or _START,
            "output_type": 4,                  # 4 = Initial Release Only
            "realtime_start": "1776-07-04",    # FRED min — span all vintages
            "realtime_end": "9999-12-31",      # FRED max
        })
        last_err = None
        for attempt in range(3):                 # retry: shared DNS here is flaky
            try:
                req = urllib.request.Request(f"{_BASE}?{q}", headers=_HDR)
                with urllib.request.urlopen(req, timeout=30) as r:
                    obs = json.loads(r.read().decode("utf-8"))["observations"]
                cached = [{"period": o["date"], "value": o["value"],
                           "released": o["realtime_start"]} for o in obs]
                cache.put_json(key, cached)
                break
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        else:
            print(f"  [fred] {series_id} releases failed after 3 tries: "
                  f"{last_err.__class__.__name__}: {str(last_err)[:80]}")
            cached = cache.get_json(key, 1e9)
            if cached is None:
                return None
    df = pd.DataFrame(cached)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["period"] = pd.to_datetime(df["period"])
    df["released"] = pd.to_datetime(df["released"])
    return df.dropna(subset=["value"]).set_index("period").sort_index()


if __name__ == "__main__":
    for sid in ["CPIAUCSL", "PAYEMS", "UNRATE"]:
        df = releases(sid)
        if df is None:
            print(f"{sid:12s} -> None"); continue
        last = df.iloc[-1]
        print(f"{sid:12s} n={len(df):4d}  last period {df.index[-1].date()} "
              f"= {last['value']}  (released {last['released'].date()})")

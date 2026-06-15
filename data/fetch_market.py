"""Market data via Yahoo's chart endpoint directly (keyless, ~0.4s).

Same source yfinance uses, minus the dependency. Cached per ticker; degrades to
the last cached pull (any age) if Yahoo is unreachable. (From recession-dashboard.)
"""
import os, sys, json, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import cache_util as cache
from config import CFG

_HDR = {"User-Agent": "Mozilla/5.0"}
_MAX = CFG["cache"]["market_max_age_h"]


def _get(url: str):
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def history(ticker: str, range_: str = "25y", interval: str = "1d") -> pd.Series | None:
    """Date-indexed close-price series. Cached; falls back to stale cache offline.

    NB: range='max' makes Yahoo silently downsample 1d -> monthly, which breaks
    event-day windows. An explicit multi-year range ('25y') keeps true daily bars.
    """
    key = f"mkt_{ticker}_{range_}_{interval}"
    s = cache.get_series(key, _MAX)
    if s is not None:
        return s
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?range={range_}&interval={interval}")
    try:
        d = _get(url)
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        s = pd.Series(closes, index=pd.to_datetime(ts, unit="s")).dropna()
        s.index = s.index.normalize()
        return cache.put_series(key, s)
    except Exception as e:
        stale = cache.get_series(key, 1e9)
        print(f"  [market] {ticker} fetch failed ({e.__class__.__name__}); "
              f"{'using stale cache' if stale is not None else 'no cache'}")
        return stale


if __name__ == "__main__":
    for t in ["^GSPC", "^SOX", "^NSEI", "INR=X"]:
        s = history(t)
        n = len(s) if s is not None else 0
        last = f"{s.iloc[-1]:.2f}" if n else "n/a"
        print(f"{t:10s} last={last:>10}  n={n}")

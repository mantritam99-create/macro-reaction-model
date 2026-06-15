"""Date-stamped cache. Never hit an API twice for data we already have today.

JSON for scalars/records, CSV for time series. Freshness is by file mtime so a
cached pull older than `max_age_h` hours is treated as stale and refetched.
(Lifted from recession-dashboard so the two repos share one cache discipline.)
"""
import os, json, time
import pandas as pd
from config import CACHE_DIR


def _path(key: str, ext: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.{ext}")


def _fresh(path: str, max_age_h: float) -> bool:
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_h * 3600


# ---- JSON (scalars, dicts, list-of-records) ----
def get_json(key: str, max_age_h: float):
    p = _path(key, "json")
    if _fresh(p, max_age_h):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def put_json(key: str, obj):
    with open(_path(key, "json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return obj


# ---- time series (pandas Series, date-indexed) ----
def get_series(key: str, max_age_h: float):
    p = _path(key, "csv")
    if _fresh(p, max_age_h):
        return pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0]
    return None


def put_series(key: str, s: pd.Series):
    s.to_frame(name="value").to_csv(_path(key, "csv"))
    return s

"""Free, automated consensus via the ForexFactory public calendar feed.

Why this exists: official agencies (BLS/BEA/MoSPI) never publish the consensus,
vendor APIs (FMP/TradingEconomics) cost money, and the Cleveland Fed nowcast is
free but JS-gated and inflation-only. The FF public JSON (nfs.faireconomy.media)
carries a `forecast` (= street consensus) field for every major event and is the
same data FF's calendar shows.

How it plugs in: this writes consensus rows into data/consensus_log.csv, which the
existing consensus layer already consumes (blended per-period over the proxy). So a
scheduled job calling update() keeps the model's surprises real, hands-off, free.

Honest limits:
  * Going-forward only (last/this/next week) -- not a deep history backfill. Real
    consensus therefore accumulates over time; older prints stay on the proxy.
  * Unofficial 3rd-party feed -- stable and widely used, but could change. If it
    breaks, the static pages show a degraded status and use the archived log.

Period bridge: FF gives a release DATE, the model keys consensus by reference
PERIOD. We resolve period by matching the FF event to the FRED first-print whose
publication date is nearest the FF date -- so FF (consensus) and FRED (actual) line
up on the same release with no hand-mapping.
"""
import os, sys, time, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from config import DATA_DIR
from data import fetch_fred

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
_FEEDS = ("thisweek",)   # faireconomy only publishes thisweek (last/next -> 404);
                         # a DAILY job captures each event on/after its release day
_URL = "https://nfs.faireconomy.media/ff_calendar_{}.json"
_CSV = os.path.join(DATA_DIR, "consensus_log.csv")

# event_type -> (fred_id for period resolution, FF title, FF country, scale)
# scale converts the parsed FF number into the model's transform units:
#   CPI/PCE/Retail are MoM% -> scale 1;  NFP is 'change (000)' and FF gives e.g.
#   '265K' -> parsed 265000 -> *0.001 = 265;  Claims is a level -> 225K -> 225000.
FF_MAP = {
    "US_CPI":      ("CPIAUCSL",        "CPI m/m",                   "USD", 1.0),
    "US_CORE_CPI": ("CPILFESL",        "Core CPI m/m",              "USD", 1.0),
    "US_PCE_CORE": ("PCEPILFE",        "Core PCE Price Index m/m",  "USD", 1.0),
    "US_NFP":      ("PAYEMS",          "Non-Farm Employment Change","USD", 0.001),
    "US_UNRATE":   ("UNRATE",          "Unemployment Rate",         "USD", 1.0),
    "US_RETAIL":   ("RSAFS",           "Retail Sales m/m",          "USD", 1.0),
    "US_CLAIMS":   ("ICSA",            "Unemployment Claims",       "USD", 1.0),
    "IN_CPI":      ("INDCPIALLMINMEI", "CPI y/y",                   "INR", 1.0),
}


def _num(raw):
    """Parse FF strings like '0.3%', '265K', '1.42M' into a float (K/M expanded)."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "")
    if s in ("", "-"):
        return None
    mult = 1.0
    if s and s[-1] in "KkMmBb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _fetch(feed):
    last = None
    for attempt in range(3):                 # feed rate-limits rapid hits
        try:
            req = urllib.request.Request(_URL.format(feed), headers=_UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise last


def _collect_forecasts():
    """Pull all feeds -> list of (event_type, ff_date, forecast_value)."""
    titles = {(t.lower(), c): (et, sc) for et, (_, t, c, sc) in FF_MAP.items()}
    seen, out, failures = set(), [], []
    for feed in _FEEDS:
        try:
            events = _fetch(feed)
        except Exception as e:
            print(f"  [ff] {feed} fetch failed: {e.__class__.__name__}")
            failures.append(feed)
            continue
        for ev in events:
            key = (str(ev.get("title", "")).lower(), ev.get("country", ""))
            if key not in titles:
                continue
            et, scale = titles[key]
            val = _num(ev.get("forecast"))
            if val is None:
                continue
            ff_date = pd.to_datetime(ev.get("date")).tz_localize(None).normalize()
            dedup = (et, ff_date)
            if dedup in seen:
                continue
            seen.add(dedup)
            out.append((et, ff_date, val * scale))
    if len(failures) == len(_FEEDS):
        raise RuntimeError("all ForexFactory feeds failed")
    return out


def update(max_gap_days: int = 5) -> pd.DataFrame:
    """Refresh consensus_log.csv from the FF feed. Returns the rows written/updated.
    Each FF forecast is keyed to the FRED first-print whose release date is nearest
    the FF event date (within max_gap_days)."""
    forecasts = _collect_forecasts()
    rows = []
    rel_cache = {}
    for et, ff_date, val in forecasts:
        fid = FF_MAP[et][0]
        if fid not in rel_cache:
            rel_cache[fid] = fetch_fred.releases(fid)
        rel = rel_cache[fid]
        if rel is None or rel.empty:
            continue
        gaps = (rel["released"] - ff_date).abs()
        i = gaps.values.argmin()
        if gaps.iloc[i].days > max_gap_days:
            continue  # forecast for a print FRED hasn't published yet -> next run
        period = rel.index[i]
        rows.append({"event_type": et, "period": period.strftime("%Y-%m-%d"),
                     "consensus": round(float(val), 4), "provider": "feed"})

    new = pd.DataFrame(rows)
    if new.empty:
        print("  [ff] no resolvable forecasts this run")
        return new
    if os.path.exists(_CSV):
        old = pd.read_csv(_CSV, dtype={"period": str})
        if "provider" not in old:
            old["provider"] = "csv"
        merged = pd.concat([old, new], ignore_index=True)
        merged = merged.drop_duplicates(["event_type", "period"], keep="last")
    else:
        merged = new
    merged.sort_values(["event_type", "period"]).to_csv(_CSV, index=False)
    return new


if __name__ == "__main__":
    written = update()
    if written.empty:
        print("nothing written")
    else:
        print(f"wrote/updated {len(written)} consensus rows:\n")
        print(written.sort_values(["event_type", "period"]).to_string(index=False))

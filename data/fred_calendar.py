"""The full FRED economic-release calendar (api.stlouisfed.org `releases/dates`).

FRED publishes a scheduled release date for *every* release it tracks. This pulls
that whole calendar over a forward window and tiers each entry by how much the
market watches it:

  tracked  -- the releases this repo's reaction model is actually fit on
              (CPI, Employment, PCE, Retail, Claims). Carries the official
              agency source link + the conventional release time (ET).
  major    -- other widely-watched US macro releases (PPI, GDP, FOMC, JOLTS,
              housing, sentiment, ...). Curated allowlist of release_ids.
  other    -- everything else FRED schedules (daily market series, regional Fed
              indexes, foreign aggregates). Hidden by default in the dashboard.

Future dates returned by `include_release_dates_with_no_data=true` are FRED's
*scheduled* dates — they can shift, especially beyond ~a month — so each entry
past today is flagged `scheduled=True` and rendered as such, never as fact.

No key -> returns [] and the caller renders an empty calendar (never crashes).
"""
import os, sys, json, time, datetime as dt, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cache_util as cache
from config import fred_key, has_fred

_HDR = {"User-Agent": "Mozilla/5.0"}
_BASE = "https://api.stlouisfed.org/fred/releases/dates"

# release_id -> label, official source, conventional ET time, modeled event types.
# Keyed by release_id (NOT event) because one release can carry several prints:
# release 10 = headline + core CPI; release 50 = payrolls + unemployment rate.
TRACKED = {
    10:  ("Consumer Price Index (CPI, headline + core)",   "https://www.bls.gov/cpi/",                                              "8:30 AM ET", ("US_CPI", "US_CORE_CPI")),
    50:  ("Employment Situation (Nonfarm Payrolls + U-rate)", "https://www.bls.gov/news.release/empsit.toc.htm",                    "8:30 AM ET", ("US_NFP", "US_UNRATE")),
    54:  ("Personal Income & Outlays (Core PCE price index)", "https://www.bea.gov/data/personal-consumption-expenditures-price-index", "8:30 AM ET", ("US_PCE_CORE",)),
    9:   ("Advance Retail Sales",                           "https://www.census.gov/retail/sales.html",                             "8:30 AM ET", ("US_RETAIL",)),
    180: ("Unemployment Insurance Weekly Claims",           "https://www.dol.gov/ui/data.pdf",                                       "8:30 AM ET", ("US_CLAIMS",)),
}

# The heaviest market movers — bolded in the agenda for visual hierarchy.
KEY = frozenset({
    53, 386,                         # GDP, GDPNow
    46, 188,                         # PPI, import/export prices
    192, 194, 11,                    # JOLTS, ADP payrolls, Employment Cost Index
    91,                              # UMich consumer sentiment
    27, 148, 97, 291, 199, 171,      # housing starts, permits, new+existing sales, Case-Shiller, FHFA HPI
    95, 25, 290,                     # durable goods/factory orders, business inventories, wholesale trade
    51, 49,                          # trade balance, international transactions
    14, 229,                         # consumer credit, construction spending
    219, 321, 351, 436,             # Chicago Fed NAI, Empire State, Philly Fed, monthly retail trade
})

# The full "is the economy moving?" set: essentially every cyclical US economic
# indicator FRED schedules. Verified by name against the 329-release master list.
# Superset of KEY (+ the 5 TRACKED above). Deliberately EXCLUDED -> left in
# `other` (hidden behind the All filter): foreign / international data, pure
# financial-market quotes & administrative rate series (already stripped by the
# daily-padding filter), and granular demographic / academic / one-off datasets.
MAJOR = KEY | frozenset({
    # output, activity, productivity, nowcasts
    331, 435, 13, 288, 47, 107, 490, 349, 280, 320,
    465, 488, 400, 373, 242, 261, 456,
    # inflation & prices
    313, 315, 323, 364, 500, 605, 345, 454, 365, 212,
    # labor market
    362, 332, 337, 341, 476, 637, 428, 469, 334, 371, 738, 769,
    # consumer & spending
    179, 92, 494, 477, 254, 736, 89, 479, 505, 737,
    # housing (beyond the KEY set)
    236, 296, 503, 462, 463, 471, 190, 228,
    # business & regional Fed surveys (US ISM is proprietary; these are the proxies)
    322, 352, 374, 376, 377, 372, 333, 292, 1132, 740, 459, 443, 468,
    # money, credit & financial conditions
    21, 63, 193, 191, 571, 231, 187, 198, 302, 221, 409, 482,
    # external & fiscal
    359, 363, 383,
    # uncertainty indices
    279, 670, 705,
})


def _fred_release_url(rid: int) -> str:
    """Canonical FRED release page — always valid for any release_id."""
    return f"https://fred.stlouisfed.org/release?rid={rid}"


def classify(rid: int) -> str:
    if rid in TRACKED:
        return "tracked"
    if rid in MAJOR:
        return "major"
    return "other"


def _fetch_raw(start: str, end: str, max_age_h: int = 12) -> list[dict]:
    """All scheduled release dates with [start, end], future ones included."""
    if not has_fred():
        return []
    key = f"calendar_{start}_{end}"
    cached = cache.get_json(key, max_age_h)
    if cached is not None:
        return cached
    # `releases/dates` caps limit at 1000; a multi-week window can exceed that,
    # so page through with offset until a short page comes back.
    rows, offset, LIMIT = [], 0, 1000
    try:
        while True:
            q = urllib.parse.urlencode({
                "api_key": fred_key(), "file_type": "json",
                "realtime_start": start, "realtime_end": end,
                "include_release_dates_with_no_data": "true",
                "sort_order": "asc", "limit": LIMIT, "offset": offset,
            })
            page = None
            for attempt in range(3):                 # shared sandbox network is flaky
                try:
                    req = urllib.request.Request(f"{_BASE}?{q}", headers=_HDR)
                    with urllib.request.urlopen(req, timeout=30) as r:
                        page = json.loads(r.read().decode("utf-8")).get("release_dates", [])
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1.5 * (attempt + 1))
            rows.extend(page)
            if len(page) < LIMIT:
                break
            offset += LIMIT
        cache.put_json(key, rows)
        return rows
    except Exception as e:
        print(f"  [calendar] fetch failed: {e.__class__.__name__}: {str(e)[:80]}")
        return cache.get_json(key, 1e9) or []


def _continuous_release_ids(rows: list[dict]) -> set[int]:
    """Release_ids that publish on a *run* of consecutive calendar days.

    `include_release_dates_with_no_data=true` pads any release lacking a real
    scheduled future date onto every day in the window — daily market series
    (H.15 rates, CBOE, Treasury) and, awkwardly, the FOMC Press Release (FRED
    carries no scheduled meeting dates for it). Genuine economic releases never
    land on 3 consecutive days, so a >=3-day run is a reliable "drop this" flag."""
    by_rid: dict[int, set] = {}
    for d in rows:
        by_rid.setdefault(d["release_id"], set()).add(
            dt.date.fromisoformat(d["date"]))
    cont = set()
    for rid, days in by_rid.items():
        run = 1
        for day in sorted(days):
            run = run + 1 if (day - dt.timedelta(days=1)) in days else 1
            if run >= 3:
                cont.add(rid)
                break
    return cont


def upcoming(days_back: int = 2, days_ahead: int = 45) -> list[dict]:
    """The release calendar over a window around today, classified and enriched.

    Each row: date (ISO), release_id, name, impact (tracked|major|other),
    scheduled (bool — date is in the future, may shift), time (ET, when known),
    source (official agency for tracked, else the FRED release page)."""
    today = dt.date.today()
    start = (today - dt.timedelta(days=days_back)).isoformat()
    end = (today + dt.timedelta(days=days_ahead)).isoformat()
    raw = _fetch_raw(start, end)
    drop = _continuous_release_ids(raw)
    out = []
    for d in raw:
        if d["release_id"] in drop:
            continue
        rid = d["release_id"]
        impact = classify(rid)
        rec = {
            "date": d["date"],
            "release_id": rid,
            "name": d["release_name"],
            "impact": impact,
            "scheduled": d["date"] > today.isoformat(),
            "time": None,
            "source": _fred_release_url(rid),
            "key": rid in KEY,
        }
        if impact == "tracked":
            label, url, time, event_types = TRACKED[rid]
            rec.update(name=label, source=url, time=time, event_types=event_types)
        out.append(rec)
    # date, then impact priority (tracked first, key major before plain), then name
    rank = {"tracked": 0, "major": 1, "other": 2}
    out.sort(key=lambda r: (r["date"], rank[r["impact"]], not r["key"], r["name"]))
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    rows = upcoming()
    n_t = sum(r["impact"] == "tracked" for r in rows)
    n_m = sum(r["impact"] == "major" for r in rows)
    print(f"calendar: {len(rows)} dates  ({n_t} tracked, {n_m} major, "
          f"{len(rows)-n_t-n_m} other)\n")
    for r in rows:
        if r["impact"] == "other":
            continue
        flag = "sched" if r["scheduled"] else "out  "
        t = f" {r['time']}" if r["time"] else ""
        print(f"  {r['date']} [{flag}] {r['impact']:7s} {r['name']}{t}")

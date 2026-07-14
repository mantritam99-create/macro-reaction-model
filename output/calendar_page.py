"""Render the FRED economic-release calendar -> docs/calendar.html.

A self-contained dark page (no CDN), agenda-style: one row per scheduled date,
releases tiered tracked / major / other. Future dates are labelled *scheduled*
(FRED's projected dates can shift). Source = FRED `releases/dates`.

Run locally:  py -3.12 -m output.calendar_page
Wired into the daily build by output/build_static.py.
"""
import os, sys, html, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from config import ROOT
from data import consensus, fred_calendar
from output import provenance

_CSS = """
*{box-sizing:border-box} body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#0f1419;color:#e6e9ee} a{color:#6db3f2;text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1000px;margin:0 auto;padding:22px}
h1{font-size:19px;margin:0 0 2px} .meta{color:#8a93a2;font-size:12px;margin-bottom:6px}
.nav{font-size:12px;margin-bottom:16px}
.legend{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:14px 0 4px;
font-size:12px;color:#8a93a2}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.dot.tracked{background:#5fd38a} .dot.major{background:#6db3f2} .dot.other{background:#46505e}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 18px}
.filters button{background:#161d26;border:1px solid #2c3744;color:#cdd4dd;border-radius:20px;
padding:5px 13px;font-size:12px;cursor:pointer}
.filters button.on{background:#1d4ed8;border-color:#1d4ed8;color:#fff}
.day{display:flex;gap:14px;padding:11px 0;border-bottom:1px solid #1a2230}
.day.hidden{display:none}
.dlabel{flex:0 0 118px;font-size:12px}
.dlabel .dow{color:#e6e9ee;font-weight:600} .dlabel .dnum{color:#8a93a2}
.dlabel .sched{display:inline-block;margin-top:3px;font-size:10px;color:#8a93a2;
background:#161d26;border:1px solid #222b36;border-radius:10px;padding:0 7px}
.day.today .dlabel .dow{color:#e9b949}
.day.past{opacity:.5}
.rels{flex:1;min-width:0}
.rel{display:flex;align-items:baseline;gap:8px;padding:3px 0}
.rel.hidden{display:none}
.rel .nm{flex:1}
.rel.tracked .nm{color:#eaf1f7;font-weight:600}
.rel.major .nm{color:#aab4c0}
.rel.major.key .nm{color:#e6ecf3;font-weight:600}
.rel.other .nm{color:#7b8694}
.tag{font-size:10px;padding:1px 7px;border-radius:10px;white-space:nowrap}
.tag.modeled{background:#13301f;color:#5fd38a;border:1px solid #1f5b35}
.t{font-size:11px;color:#8a93a2;white-space:nowrap} .src{font-size:11px}
.note{color:#6b7785;font-size:11px;margin-top:18px;line-height:1.6}
.empty{color:#8a93a2;padding:20px 0}
""" + provenance.CSS

def render(rows: list[dict], coverage=None, feed_status=None, provider_by_event=None) -> str:
    provider_by_event = provider_by_event or {}
    n_t = sum(r["impact"] == "tracked" for r in rows)
    n_m = sum(r["impact"] == "major" for r in rows)
    n_k = sum(r.get("key") for r in rows)
    n_o = len(rows) - n_t - n_m
    gen = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # group by date (rows already sorted by date, then impact, then name).
    # NOTE: "Today" / "Tomorrow" / "scheduled" / past-dimming are decided in the
    # BROWSER (see markDates() below), not here — otherwise a static page built at
    # 23:00 UTC would show a stale "Today" all of the next day. Server emits the
    # absolute weekday + an empty .reltag slot; the client fills relatives in ET.
    from itertools import groupby
    days_html = []
    for date_str, grp in groupby(rows, key=lambda r: r["date"]):
        d = dt.date.fromisoformat(date_str)
        dow = d.strftime("%a")
        dnum = d.strftime("%b ") + str(d.day)
        rel_html = []
        for r in grp:
            imp = r["impact"]
            time = f"<span class='t'>{html.escape(r['time'])}</span>" if r.get("time") else ""
            tag = "<span class='tag modeled'>modeled</span>" if imp == "tracked" else ""
            if imp == "tracked" and provider_by_event:
                providers = dict.fromkeys(provider_by_event.get(et, "proxy")
                                          for et in r.get("event_types", ()))
                tag += "".join(provenance.badge(p) for p in providers)
            src = (f"<a class='src' href='{html.escape(r['source'])}' target='_blank' "
                   f"rel='noopener'>source ↗</a>")
            keycls = " key" if r.get("key") else ""
            rel_html.append(
                f"<div class='rel {imp}{keycls}' data-impact='{imp}'>"
                f"<span class='dot {imp}'></span>"
                f"<span class='nm'>{html.escape(r['name'])}</span>"
                f"{tag}{time}{src}</div>")
        days_html.append(
            f"<div class='day' data-date='{date_str}'>"
            f"<div class='dlabel'><div class='dow'>{dow}</div>"
            f"<div class='dnum'>{dnum}</div><div class='reltag'></div></div>"
            f"<div class='rels'>{''.join(rel_html)}</div></div>")

    body = "".join(days_html) if days_html else (
        "<div class='empty'>No scheduled releases returned — check the FRED key "
        "(<code>FRED_API_KEY</code>) or connectivity.</div>")

    # window describes the actual data span (not build-day) so it can't go stale
    dates = [r["date"] for r in rows]
    if dates:
        first = dt.date.fromisoformat(min(dates))
        last = dt.date.fromisoformat(max(dates))
        window = f"{first.strftime('%b %d')} – {last.strftime('%b %d, %Y')}"
    else:
        window = "—"

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FRED Release Calendar</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>Economic Release Calendar</h1>
<div class="meta">{window} · {n_m + n_t} US economic indicators ({n_k} top-tier, {n_t} modeled) · {n_o} other · source: FRED <code>releases/dates</code> · built {gen}</div>
<div class="nav"><a href="index.html">← Macro Reaction Dashboard</a></div>
{provenance.summary(coverage or consensus.coverage(), feed_status)}

<div class="filters">
  <button data-view="major" class="on">Economic indicators</button>
  <button data-view="tracked">Modeled only</button>
  <button data-view="all">Everything</button>
</div>
<div class="legend">
  <span><span class="dot tracked"></span>modeled in this dashboard</span>
  <span><span class="dot major"></span>economic indicator <b style="color:#e6ecf3">(bold = top-tier)</b></span>
  <span><span class="dot other"></span>markets / global / granular</span>
</div>

{body}

<p class="note">
Dates past today are FRED's <b>scheduled</b> projections and can shift — especially
beyond ~a month — so they're marked as such, not asserted as fact. Future dates come
from <code>include_release_dates_with_no_data=true</code>; releases that FRED pads
onto every calendar day (daily market series, and the FOMC press release — FRED
carries no scheduled meeting dates for it) are filtered out. For FOMC decision dates
see <a href="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" target="_blank" rel="noopener">federalreserve.gov ↗</a>.
"Tracked" releases are the ones this repo's reaction model is fit on; "source ↗"
links to the official agency for those and to the FRED release page otherwise.
Provider badges beside tracked releases describe the latest modeled observation;
future street consensus is not known until a feed or manual value arrives.
</p>
</div>

<script>
(function(){{
  // Decide Today / Tomorrow / scheduled / past in the viewer's browser, in US
  // Eastern (the release schedule's timezone), so a statically-built page never
  // shows a stale "Today". en-CA gives an ISO YYYY-MM-DD date string.
  function markDates(){{
    var today = new Date().toLocaleDateString('en-CA', {{timeZone:'America/New_York'}});
    var a = today.split('-').map(Number);
    var u = new Date(Date.UTC(a[0], a[1]-1, a[2]));
    u.setUTCDate(u.getUTCDate()+1);
    var tomorrow = u.toISOString().slice(0,10);
    document.querySelectorAll('.day').forEach(function(d){{
      var date = d.getAttribute('data-date');
      var dow = d.querySelector('.dow');
      var tag = d.querySelector('.reltag');
      d.classList.remove('today','past');
      if(tag) tag.innerHTML = '';
      if(date===today){{ if(dow) dow.textContent='Today'; d.classList.add('today'); }}
      else if(date===tomorrow){{ if(dow) dow.textContent='Tomorrow'; }}
      if(date>today){{ if(tag) tag.innerHTML='<span class="sched">scheduled</span>'; }}
      else if(date<today){{ d.classList.add('past'); }}
    }});
  }}
  markDates();

  var btns = document.querySelectorAll('.filters button');
  function apply(view){{
    document.querySelectorAll('.rel').forEach(function(r){{
      var imp = r.getAttribute('data-impact');
      var show = view==='all' || imp==='tracked'
                 || (view==='major' && imp==='major');
      r.classList.toggle('hidden', !show);
    }});
    document.querySelectorAll('.day').forEach(function(d){{
      var any = d.querySelectorAll('.rel:not(.hidden)').length > 0;
      d.classList.toggle('hidden', !any);
    }});
    btns.forEach(function(b){{ b.classList.toggle('on', b.getAttribute('data-view')===view); }});
  }}
  btns.forEach(function(b){{ b.addEventListener('click', function(){{ apply(b.getAttribute('data-view')); }}); }});
  apply('major');
}})();
</script>
</body></html>"""


def main(coverage=None, feed_status=None, provider_by_event=None):
    rows = fred_calendar.upcoming()
    htmlstr = render(rows, coverage=coverage, feed_status=feed_status,
                     provider_by_event=provider_by_event)
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    out = os.path.join(docs, "calendar.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlstr)
    print(f"  wrote {out} ({len(htmlstr):,} bytes, {len(rows)} releases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

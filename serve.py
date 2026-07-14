"""Local dashboard.  Run:  py -3.12 serve.py  -> opens http://127.0.0.1:8765

No web dependencies (stdlib http.server). It:
  * lists each report with its OFFICIAL source link and publish status (alert),
  * lets you log a print by typing ONE number — the consensus — because the actual
    is already pulled from FRED (surprise = actual - your number),
  * runs the history-trained reaction model and shows the expected market move for
    that surprise, plus the current regime read.

The model rebuilds in-memory on each save; FRED/Yahoo are cached (12h) so it's fast.
"""
import os, sys, urllib.parse, webbrowser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pandas as pd
from model import events, reaction, inference
from data import consensus as cons
from output import provenance

HOST, PORT = "127.0.0.1", 8765
STATE: dict = {}
STATIC = False  # when True (static build for GitHub Pages) the input form is omitted


def rebuild():
    panel = events.build_panel()
    STATE["panel"] = panel
    STATE["matrix"] = reaction.reaction_matrix(panel) if len(panel) else pd.DataFrame()
    STATE["si"] = reaction.surprise_index(panel) if len(panel) else {}
    STATE["diff"] = reaction.diffusion(panel) if len(panel) else {}
    STATE["status"] = events.latest_status()
    STATE["coverage"] = cons.coverage(panel)
    STATE.setdefault("feed_status", {"state": "unknown", "detail": "feed not checked"})


# ---------------------------------------------------------------- render -----
def _regime_html():
    si, df = STATE["si"], STATE["diff"]
    cells = []
    for region in sorted(si):
        s = si[region].dropna()
        if s.empty:
            continue
        d = df.get(region, pd.Series(dtype=float)).dropna()
        val = s.iloc[-1]
        br = d.iloc[-1] if not d.empty else float("nan")
        tone = "good-news" if val > 0 else "bad-news"
        cls = "pos" if val > 0 else "neg"
        brtxt = "-" if pd.isna(br) else f"{br:.0%} up"
        cells.append(
            f"<div class='rg'><div class='rgr'>{region}</div>"
            f"<div class='rgv {cls}'>{val:+.2f}</div>"
            f"<div class='rgs'>{tone} · breadth {brtxt}<br>as of {s.index[-1].date()}</div></div>")
    return "<div class='regime'>" + "".join(cells) + "</div>"


def _reports_html():
    matrix = STATE["matrix"]
    cards = []
    for s in STATE["status"]:
        if s.get("status") == "no data":
            cards.append(f"<div class='card muted'>{s['label']} — no FRED data</div>")
            continue
        logged = s.get("logged")
        provider = s.get("provider", "proxy")
        chip = provenance.badge(provider)
        src = f"<a href='{s['url']}' target='_blank' rel='noopener'>official source ↗</a>"
        sz = s.get("surprise_z")
        sz_txt = f" · surprise <b>{sz:+.2f}σ</b>" if sz is not None else ""
        prefill = (f"value='{s['consensus']}'"
                   if logged and s.get("consensus") is not None else "")
        if STATIC:
            form = (f"<div class='note'>Latest consensus source: "
                    f"{provenance.LABELS.get(provider, provider)}. Proxy values are "
                    "model expectations, not street consensus.</div>")
        else:
            form = (
                "<form method='post' action='/submit' class='inp'>"
                f"<input type='hidden' name='event_type' value='{s['event_type']}'>"
                f"<input type='hidden' name='period' value='{s['period']}'>"
                f"<label>street consensus "
                f"<input type='number' step='any' name='consensus' {prefill} "
                f"placeholder='one number'></label>"
                "<button>save</button></form>")
        proj = ""
        if sz is not None:
            pj = inference.project(s["event_type"], sz, matrix)
            if not pj.empty:
                body = "".join(
                    f"<tr><td>{r.market}</td><td>T+{int(r.horizon)}</td>"
                    f"<td class='{'pos' if r.expected_move_pct >= 0 else 'neg'}'>"
                    f"{r.expected_move_pct:+.2f}%</td>"
                    f"<td>{r.r2:.2f}</td><td>{r.hit:.0%}</td><td>{int(r.n)}</td></tr>"
                    for r in pj.head(4).itertuples())
                proj = ("<table class='proj'><tr><th>market</th><th>win</th>"
                        "<th>expected move</th><th>R²</th><th>hit</th><th>n</th></tr>"
                        f"{body}</table>")
        cards.append(
            "<div class='card'>"
            f"<div class='hd'><b>{s['label']}</b> {chip} {src}</div>"
            f"<div class='sub'>{s.get('period_label','-')} · actual "
            f"<b>{s.get('actual','-')}</b> {s['unit']} · released {s.get('released','-')}"
            f"{sz_txt}</div>{form}{proj}</div>")
    return "\n".join(cards)


def _matrix_html():
    m = STATE["matrix"]
    if m.empty:
        return "<p class='muted'>no fitted cells yet</p>"
    def source_mix(r):
        return "".join(provenance.badge(p, int(getattr(r, f"{p}_n", 0)))
                       for p in ("csv", "feed", "proxy")
                       if getattr(r, f"{p}_n", 0))

    body = "".join(
        f"<tr><td>{r.event_type}</td><td>{r.market}</td><td>T+{int(r.horizon)}</td>"
        f"<td class='{'pos' if r.beta_pct >= 0 else 'neg'}'>{r.beta_pct:+.2f}</td>"
        f"<td>{r.r2:.2f}</td><td>{r.hit:.0%}</td><td>{int(r.n)}</td>"
        f"<td>{source_mix(r)}</td></tr>"
        for r in m.head(25).itertuples())
    return ("<table class='mtx'><tr><th>event</th><th>market</th><th>win</th>"
            "<th>β %/1σ</th><th>R²</th><th>hit</th><th>n</th><th>src</th></tr>"
            f"{body}</table>")


_CSS = """
*{box-sizing:border-box} body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
margin:0;background:#0f1419;color:#e6e9ee} a{color:#6db3f2}
.wrap{max-width:1000px;margin:0 auto;padding:22px}
h1{font-size:19px;margin:0 0 2px} .meta{color:#8a93a2;font-size:12px;margin-bottom:18px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#8a93a2;
margin:26px 0 10px;border-bottom:1px solid #222b36;padding-bottom:6px}
.regime{display:flex;gap:12px;flex-wrap:wrap}
.rg{background:#161d26;border:1px solid #222b36;border-radius:10px;padding:12px 16px;min-width:150px}
.rgr{font-size:12px;color:#8a93a2} .rgv{font-size:26px;font-weight:700}
.rgs{font-size:11px;color:#8a93a2}
.card{background:#161d26;border:1px solid #222b36;border-radius:10px;padding:13px 15px;margin-bottom:10px}
.card.muted{color:#6b7785} .hd{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.sub{color:#8a93a2;font-size:12px;margin:3px 0 8px}
.chip{font-size:11px;padding:2px 8px;border-radius:20px}
.chip.ok{background:#16351f;color:#5fd38a;border:1px solid #1f5b35}
.chip.warn{background:#3a2d12;color:#e9b949;border:1px solid #6b4f15}
.inp{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.inp input[type=number]{background:#0f1419;border:1px solid #2c3744;color:#e6e9ee;
border-radius:6px;padding:5px 8px;width:140px}
.inp button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer}
.inp button:hover{background:#1d4ed8}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}
th,td{text-align:right;padding:4px 8px;border-bottom:1px solid #1c2530}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
.proj{background:#10171f;border-radius:6px}
.pos{color:#5fd38a} .neg{color:#f08a8a} .muted{color:#6b7785}
.note{color:#6b7785;font-size:11px;margin-top:8px}
""" + provenance.CSS


def page():
    panel = STATE["panel"]
    if len(panel):
        span = f"{str(panel['release_dt'].min())[:10]} … {str(panel['release_dt'].max())[:10]}"
        meta = f"{len(panel):,} obs · {panel['event_type'].nunique()} event types · {span}"
    else:
        meta = "no data — check FRED key / connectivity"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Macro Reaction Dashboard</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>Macro Reaction Dashboard</h1><div class="meta">{meta}</div>
<div class="meta"><a href="calendar.html">Economic release calendar →</a></div>
{provenance.summary(STATE.get("coverage", {}), STATE.get("feed_status"))}

<h2>Regime read</h2>{_regime_html()}

<h2>Reports — log consensus, get the model's read</h2>
<p class="note">The actual is auto-pulled from FRED; you type only the street's
consensus. Surprise = actual − consensus. "Expected move" = the history-trained
β × this surprise — a conditional historical average, <b>not</b> a forecast of
which way the next print lands.</p>
{_reports_html()}

<h2>Reaction matrix — the trained model (top cells by R²)</h2>
{_matrix_html()}
<p class="note">High R² = a reliable reaction function; near-zero R² = that event is
noise for that market (shown, not hidden). Source badges show the observations behind
each coefficient; proxy-derived observations are never street-consensus evidence.</p>
</div></body></html>"""


# ---------------------------------------------------------------- server -----
class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if b:
            self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/favicon"):
            self._send("", 204); return
        self._send(page())

    def do_POST(self):
        if self.path != "/submit":
            self._send("not found", 404); return
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
        et = form.get("event_type", [""])[0]
        period = form.get("period", [""])[0]
        raw = form.get("consensus", [""])[0].strip()
        if et and period and raw:
            try:
                cons.log_consensus(et, period, float(raw))
                rebuild()
                print(f"  logged {et} {period} consensus={raw}")
            except Exception as e:
                print(f"  submit error: {e.__class__.__name__}: {e}")
        self.send_response(303); self.send_header("Location", "/"); self.end_headers()

    def log_message(self, *a):
        pass


def main():
    print("building model (first run pulls FRED + Yahoo, then cached)...")
    rebuild()
    url = f"http://{HOST}:{PORT}/"
    print(f"\n  dashboard ready: {url}\n  (Ctrl+C to stop)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

# macro-reaction-model

Turns the macro-event calendars into a backtested **reaction model**: for every
economic release, what *surprise* did it carry, and how did each market move? The
sibling of `recession-dashboard` — same plumbing (urllib → FRED + Yahoo,
`config.yaml`, date-stamped cache, `py` launcher, no `yfinance`/`statsmodels`).

## The one idea that keeps it honest

Markets move on the **surprise** — `actual − consensus` — not the actual. Every
number here is keyed on that, standardized so a 1σ CPI surprise is comparable to a
1σ payrolls surprise. A model keyed on the raw actual would "discover" garbage.

**What it can do:** characterize reaction functions (which event moves which
market, how hard, how reliably), nowcast laggy prints from timely ones, and read
the regime (good-news vs bad-news). **What it can't:** predict which way a
scheduled print lands. If a version ever claims that, it's overfit — delete it.

## Run

```
pip install -r requirements.txt
copy config.example.yaml config.yaml   # then paste your FRED key (or set $FRED_API_KEY)
py -3.12 main.py
```

> Pin **`py -3.12`**: pandas is installed on 3.12 here, but the default `py`
> resolves to 3.14 (no pandas). Same interpreter recession-dashboard uses.

Smoke-test the data layer on its own:
```
py -3.12 data\fetch_fred.py     # initial-release pulls for CPI / NFP / UNRATE
py -3.12 data\fetch_market.py   # SPX / SOX / NIFTY / USDINR closes
py -3.12 model\events.py        # build + summarize the event panel
```

## Dashboard

```
py -3.12 serve.py               # opens http://127.0.0.1:8765
```

A zero-dependency local dashboard (stdlib `http.server`, no CDN/Flask). It:
- lists each report with its **official source link** and publish status (alert),
- lets you log a print by typing **one number — the consensus** — because the
  actual is already pulled from FRED (surprise = actual − your number),
- runs the history-trained model and shows the **expected market move** for that
  surprise, plus the current **regime read**.

Saving writes `data/consensus_log.csv` and rebuilds the model in-memory (FRED/Yahoo
are cached 12h, so it's fast). Each logged number flips that print's `provider` from
`proxy` to `csv`, sharpening the betas over time.

## Automation (free) + live site

A daily GitHub Action (`.github/workflows/deploy.yml`) runs the whole loop with no
manual input and no paid APIs:

```
free consensus feed → rebuild model → render docs/index.html → commit → GitHub Pages
```

- **Consensus, automated for free:** `data/forexfactory.py` pulls the public
  ForexFactory calendar JSON (the `forecast` field = street consensus) for every
  major event, parses units, and bridges each forecast to its FRED first-print by
  release date — appending to `consensus_log.csv`. The feed is current-week and
  rate-limits, so it's hit **once daily**; real-consensus betas accumulate going
  forward while older history stays on the proxy. If the feed ever breaks, the
  pipeline degrades to the proxy (never crashes).
- **Static render:** `output/build_static.py` writes the read-only dashboard to
  `docs/`, served by GitHub Pages (no backend — the live site shows regime, the
  reaction matrix, and "just published" alerts with source links).
- **Secret:** the FRED key is a repo Actions secret (`FRED_API_KEY`), never
  committed (`config.yaml` is gitignored).

Run the static build locally:  `py -3.12 -m output.build_static`

## Pipeline

```
FRED first-prints (output_type=4)  ┐
consensus (proxy | csv | feed)     ├─► event panel ─► reaction matrix
Yahoo close prices                 ┘   (surprise_z)   surprise index (regime)
                                                      diffusion nowcast
```

| file | role |
|---|---|
| `data/fetch_fred.py` | FRED API; `releases()` returns **initial-release** values + their publication date (no revision lookahead) |
| `data/fetch_market.py` | Yahoo daily closes, keyless |
| `data/consensus.py` | the consensus layer — **proxy** (default, free), **csv** (manual log), **feed** (stub for a calendar API) |
| `model/events.py` | event catalog + builds the panel (surprise z-score + market windows) |
| `model/reaction.py` | reaction matrix, surprise index, diffusion nowcast |
| `output/report.py` | console report |
| `main.py` | orchestrator |

## Consensus — the one real fork

`consensus.py` is pluggable per event. The default **proxy** is a walk-forward
forecast from prior first-prints — fully free, runs today, but it's a *model's*
expectation, not the street's, and every row is tagged with its `provider` so the
report never conflates the two. To use real street consensus, drop a
`data/consensus_log.csv` (`event_type,period,consensus`) and set an event's
`consensus` to `"csv"`, or implement `fetch_feed()` against a calendar API.

## Data-reality notes

- **US** series have rich first-print vintages on FRED → clean release-day numbers.
- **India** IIP / WPI / RBI repo lack reliable FRED vintages → they belong in the
  manual CSV path, not the auto catalog. India CPI is included best-effort.
- Market windows use **daily** closes. US prints land after the India close, so
  India reactions are measured on the next session (lag baked into the window
  math). Intraday windows would sharpen this but Yahoo only serves ~60d of
  free intraday history — a later upgrade if you want event-day precision.

## Roadmap

- [ ] Wire the manual `consensus_log.csv` for the India events + RBI.
- [ ] Add a regime-conditioned reaction matrix (split cells by surprise-index sign
      to quantify the "good news is bad news" flip).
- [ ] HTML dashboard (reuse `recession-dashboard/output/dashboard.py` style) with a
      reaction heatmap + a calendar overlay marking the next Tier-1 dates.
- [ ] Backtest a regime signal vs forward index returns (the recession-dashboard
      no-lookahead discipline).
```

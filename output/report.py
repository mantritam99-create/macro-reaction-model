"""Console report: the reaction matrix + the current regime read.

Deliberately honest about its ceiling -- it characterizes reaction functions and
reads the regime; it never prints a directional call on an upcoming print.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd


def _fmt_matrix(rm: pd.DataFrame, top: int = 20) -> str:
    if rm.empty:
        return "  (no reaction cells met the min-events threshold yet)"
    lines = [f"  {'event':14s} {'mkt':6s} {'h':>2s} "
             f"{'beta%/1σ':>9s} {'R²':>5s} {'hit':>5s} {'n':>4s}  src"]
    for _, r in rm.head(top).iterrows():
        lines.append(f"  {r.event_type:14s} {r.market:6s} {int(r.horizon):>2d} "
                     f"{r.beta_pct:>+9.2f} {r.r2:>5.2f} {r.hit:>5.0%} "
                     f"{int(r.n):>4d}  {r.provider}")
    return "\n".join(lines)


def _regime_line(name: str, si: dict, df: dict) -> str:
    out = []
    for region in sorted(si):
        s = si[region].dropna()
        d = df.get(region, pd.Series(dtype=float)).dropna()
        if s.empty:
            continue
        val = s.iloc[-1]
        breadth = d.iloc[-1] if not d.empty else float("nan")
        tone = "good-news" if val > 0 else "bad-news"
        out.append(f"  {region}:  surprise-index {val:+.2f} ({tone}), "
                   f"breadth {breadth:.0%} up  [as of {s.index[-1].date()}]")
    return "\n".join(out) if out else "  (insufficient history)"


def render(panel, rm, si, df) -> str:
    n_ev = panel["event_type"].nunique() if len(panel) else 0
    span = (f"{panel['release_dt'].min().date()} .. {panel['release_dt'].max().date()}"
            if len(panel) else "-")
    parts = [
        "=" * 68,
        "  MACRO REACTION MODEL",
        "=" * 68,
        f"  panel: {len(panel)} obs · {n_ev} event types · {span}",
        "",
        "  REACTION MATRIX  (move per +1σ surprise; sorted by R²)",
        "  ----------------------------------------------------------------",
        _fmt_matrix(rm),
        "",
        "  REGIME READ  (cumulative-surprise momentum & breadth)",
        "  ----------------------------------------------------------------",
        _regime_line("regime", si, df),
        "",
        "  Reading it: high-R² rows are reliable reaction functions; near-zero-R²",
        "  rows mean that event is noise for that market. The regime read tells you",
        "  WHICH regime you're in (good-news vs bad-news) — it does NOT predict the",
        "  direction of the next print. Map these to the calendar to size expected",
        "  noise around each date; let trip-wires, not this table, decide action.",
        "=" * 68,
    ]
    return "\n".join(parts)

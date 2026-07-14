"""Shared provider badges for both static pages."""
import html


CSS = """
.provbox{background:#161d26;border:1px solid #2c3744;border-radius:9px;padding:9px 12px;
margin:10px 0 16px;color:#aab4c0;font-size:12px}.provbox b{color:#e6e9ee}
.badge{display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;margin:2px 2px}
.badge.csv{background:#16351f;color:#5fd38a;border:1px solid #1f5b35}
.badge.feed{background:#132d46;color:#6db3f2;border:1px solid #245478}
.badge.proxy{background:#3a2d12;color:#e9b949;border:1px solid #6b4f15}
.feedstate{display:inline-block;margin-left:6px}.feedstate.current{color:#5fd38a}
.feedstate.degraded{color:#f08a8a}.feedstate.unknown{color:#8a93a2}
"""

LABELS = {"csv": "actual CSV", "feed": "feed", "proxy": "proxy"}


def badge(provider: str, count=None) -> str:
    label = LABELS.get(provider, provider)
    text = f"{label}: {count}" if count is not None else label
    return f"<span class='badge {provider}'>{html.escape(str(text))}</span>"


def summary(coverage: dict, feed_status: dict | None = None) -> str:
    feed_status = feed_status or {"state": "unknown", "detail": "feed not checked"}
    state = feed_status.get("state", "unknown")
    detail = html.escape(feed_status.get("detail", ""))
    badges = "".join(badge(p, coverage.get(p, 0)) for p in ("csv", "feed", "proxy"))
    return (
        "<div class='provbox'><b>Consensus provenance</b> Â· "
        f"{coverage.get('actual', 0):,} actual-consensus observations / "
        f"{coverage.get('total', 0):,} modeled observations Â· {badges}"
        f"<span class='feedstate {state}'>feed {html.escape(state)}</span>"
        f"<div>{detail}</div>"
        "<div>Actual CSV and feed badges are street-consensus inputs; proxy is a "
        "walk-forward model expectation, not street consensus.</div></div>"
    )

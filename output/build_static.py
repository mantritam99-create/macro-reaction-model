"""Render the static dashboard for GitHub Pages -> docs/index.html.

Best-effort refresh of consensus from the public feed, rebuild the model, write a
read-only page (no input form). Run by the daily GitHub Action; also runnable
locally:  py -3.12 -m output.build_static
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from config import ROOT
import serve
from data import forexfactory


def main():
    try:
        n = forexfactory.update()
        got = 0 if n is None or n.empty else len(n)
        print(f"  consensus feed: {got} row(s) refreshed")
    except Exception as e:
        print(f"  consensus feed skipped ({e.__class__.__name__}) — using existing log")

    serve.STATIC = True
    serve.rebuild()
    html = serve.page()

    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    open(os.path.join(docs, ".nojekyll"), "w").close()  # serve files as-is
    out = os.path.join(docs, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  wrote {out} ({len(html):,} bytes)")

    # the full FRED economic-release calendar -> docs/calendar.html
    try:
        from output import calendar_page
        calendar_page.main()
    except Exception as e:
        print(f"  calendar page skipped ({e.__class__.__name__}: {str(e)[:80]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

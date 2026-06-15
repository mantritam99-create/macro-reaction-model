"""Orchestrator. Run:  py main.py

Pipeline:  FRED first-prints + consensus + market prices
        -> event panel (surprise z-scored)
        -> reaction matrix + surprise index + diffusion nowcast
        -> console report.
"""
import sys
try:                                  # Windows console defaults to cp1252; report uses σ, R²
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from model import events, reaction
from output import report


def main():
    print("building event panel (FRED first-prints + Yahoo prices)...")
    panel = events.build_panel()
    if panel.empty:
        print("\nNo events built. Check the FRED key in config.yaml and connectivity "
              "(try:  py -m data.fetch_fred  and  py -m data.fetch_market).")
        return 1

    rm = reaction.reaction_matrix(panel)
    si = reaction.surprise_index(panel)
    df = reaction.diffusion(panel)
    print("\n" + report.render(panel, rm, si, df))
    print("\nsaved: data/event_panel.csv  (the full panel, one row per release×market×horizon)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

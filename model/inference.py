"""Apply the trained reaction function to a fresh print.

The reaction matrix is the model trained on ~25 years of first-print history. Given
the standardized surprise a new release carried (which becomes accurate the moment
you log its street consensus), project the *historically expected* move for each
market: expected_move% = beta_pct * surprise_z.

HONESTY: this is a conditional historical average, not a forecast of direction. It
answers "given a surprise THIS big, how has this market typically reacted," carrying
the reliability (R², hit-rate, n) so a noisy cell is never dressed up as a signal.
It does NOT predict whether the next print will surprise up or down.
"""
import pandas as pd


def project(event_type: str, surprise_z: float, matrix: pd.DataFrame,
            min_r2: float = 0.0) -> pd.DataFrame:
    """Expected move per market for one event's surprise. Returns a DataFrame
    sorted by reliability (R²), or empty if the event has no fitted cells."""
    if matrix.empty or surprise_z is None or pd.isna(surprise_z):
        return pd.DataFrame()
    m = matrix[(matrix["event_type"] == event_type) & (matrix["r2"] >= min_r2)].copy()
    if m.empty:
        return m
    m["surprise_z"] = surprise_z
    m["expected_move_pct"] = m["beta_pct"] * surprise_z
    return m.sort_values(["r2", "horizon"], ascending=[False, True])[
        ["market", "horizon", "expected_move_pct", "beta_pct", "r2", "hit", "n", "provider"]
    ].reset_index(drop=True)

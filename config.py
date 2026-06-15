"""Config + path resolution. Import this anywhere; it finds project root.

Loads config.yaml if present (local). In CI that file is gitignored and absent, so
it falls back to config.example.yaml for the knobs and reads the FRED key from the
FRED_API_KEY env var (a GitHub Actions secret). Never crashes on a missing file.
"""
import os, yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(CACHE_DIR, exist_ok=True)


def _load_cfg() -> dict:
    for name in ("config.yaml", "config.example.yaml"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}  # defaults handled by .get() calls downstream


CFG = _load_cfg()


def fred_key() -> str:
    """Key from config.yaml, else FRED_API_KEY env var (CI secret), else ''."""
    return (CFG.get("fred", {}).get("api_key") or os.environ.get("FRED_API_KEY") or "").strip()


def has_fred() -> bool:
    return len(fred_key()) >= 32  # FRED keys are 32-char alphanumeric

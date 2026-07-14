import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import serve
from data import consensus, forexfactory
from output import calendar_page


class ProviderDataTests(unittest.TestCase):
    def test_coverage_counts_unique_releases(self):
        panel = pd.DataFrame([
            {"event_type": "A", "period": "2026-01-01", "provider": "proxy"},
            {"event_type": "A", "period": "2026-01-01", "provider": "proxy"},
            {"event_type": "B", "period": "2026-01-01", "provider": "proxy"},
            {"event_type": "C", "period": "2026-01-01", "provider": "proxy"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "consensus_log.csv")
            path.write_text(
                "event_type,period,consensus,provider\n"
                "A,2026-01-01,1.0,feed\nB,2026-01-01,2.0,csv\n",
                encoding="utf-8",
            )
            with mock.patch.object(consensus, "_CSV", str(path)):
                result = consensus.coverage(panel)

        self.assertEqual(result, {"total": 3, "actual": 2, "csv": 1,
                                  "feed": 1, "proxy": 1})

    def test_all_feed_failures_are_not_silent(self):
        with mock.patch.object(forexfactory, "_fetch", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "all ForexFactory feeds failed"):
                forexfactory._collect_forecasts()

    def test_feed_provider_reaches_the_modeled_release(self):
        metric = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-01-01", "2026-02-01"]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "consensus_log.csv")
            path.write_text(
                "event_type,period,consensus,provider\nA,2026-01-01,0.5,feed\n",
                encoding="utf-8",
            )
            with mock.patch.object(consensus, "_CSV", str(path)):
                _, providers = consensus.consensus_for(
                    "A", metric, {"consensus": "csv", "proxy_method": "rw"})

        self.assertEqual(providers.loc[pd.Timestamp("2026-01-01")], "feed")
        self.assertEqual(providers.loc[pd.Timestamp("2026-02-01")], "proxy")


class StaticProvenanceTests(unittest.TestCase):
    COVERAGE = {"total": 100, "actual": 9, "csv": 1, "feed": 8, "proxy": 91}
    FEED = {"state": "degraded", "detail": "Feed check failed; archived data retained."}

    def test_both_renderers_show_provider_provenance(self):
        serve.STATE.update({
            "panel": pd.DataFrame(), "matrix": pd.DataFrame(), "si": {}, "diff": {},
            "coverage": self.COVERAGE, "feed_status": self.FEED,
            "status": [{"event_type": "US_CPI", "label": "US CPI", "unit": "%",
                        "url": "https://example.test", "period_label": "Jun 2026",
                        "actual": 0.3, "released": "2026-07-14", "surprise_z": None,
                        "consensus": 0.2, "logged": True, "provider": "feed"}],
        })
        with mock.patch.object(serve, "STATIC", True):
            dashboard = serve.page()
        calendar_rows = [{"date": "2026-07-15", "release_id": 10,
                          "name": "CPI", "impact": "tracked", "key": False,
                          "time": "8:30 AM ET", "source": "https://example.test",
                          "event_types": ("US_CPI", "US_CORE_CPI")}]
        calendar = calendar_page.render(
            calendar_rows, self.COVERAGE, self.FEED,
            {"US_CPI": "feed", "US_CORE_CPI": "proxy"})
        pages = (dashboard, calendar)
        for page in pages:
            for text in ("Consensus provenance", "actual CSV", "feed", "proxy",
                         "actual-consensus observations", "degraded"):
                self.assertIn(text, page)
        self.assertIn("class='badge feed'>feed</span>", calendar)
        self.assertIn("class='badge proxy'>proxy</span>", calendar)

    def test_generated_pages_include_provider_provenance(self):
        for path in (Path("docs/index.html"), Path("docs/calendar.html")):
            page = path.read_text(encoding="utf-8")
            self.assertIn("Consensus provenance", page, path)
            self.assertIn("actual CSV", page, path)
            self.assertIn("feed", page, path)
            self.assertIn("proxy", page, path)


if __name__ == "__main__":
    unittest.main()

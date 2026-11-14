"""Tests for the January safeguards in update_prices.py: finding LEA's newest file, keeping history
across files, and failing loudly when the prices stop changing. No network is used."""
import datetime as dt
import json
import os
import sys
import tempfile
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import update_prices as up  # noqa: E402

LINK_2026 = "https://ltenergagen.sharepoint.com/:x:/s/intra/doc/IQ2026?e=a"
LINK_2027 = "https://ltenergagen.sharepoint.com/:x:/s/intra/doc/IQ2027?e=b"


def anchor(href, title="", text=""):
    return '<a href="%s" target="_blank" title="%s">%s</a>' % (href, title, text)


def point(date, petrol=1.9):
    return {"date": date, "petrol95": petrol, "diesel": 2.2, "lpg": 0.9}


class FindUrlTests(unittest.TestCase):
    def test_finds_todays_page_format(self):
        html = '<a href="Naujiena/kdk-20261030/" title="Pranešimas 2026-10-30">x</a>' + \
               anchor(LINK_2026, "2026 m. degalų kainos (nuo 2026-04-08)")
        self.assertEqual(up.find_xlsx_url(html), LINK_2026)

    def test_prefers_the_newest_year(self):
        html = anchor(LINK_2026, "2026 m. degalų kainos") + anchor(LINK_2027, "2027 m. degalų kainos")
        self.assertEqual(up.find_xlsx_url(html), LINK_2027)
        html = anchor(LINK_2027, "2027 m. degalų kainos") + anchor(LINK_2026, "2026 m. degalų kainos")
        self.assertEqual(up.find_xlsx_url(html), LINK_2027)

    def test_reads_the_link_text_too(self):
        self.assertEqual(up.find_xlsx_url(anchor(LINK_2027, "", "2027 m. degalų kainos")), LINK_2027)

    def test_rejects_other_addresses(self):
        for bad in ("https://evil.example/2027.xlsx",
                    "https://ltenergagen.sharepoint.com.evil.example/x",
                    "http://ltenergagen.sharepoint.com/x"):
            with self.subTest(bad):
                self.assertIsNone(up.find_xlsx_url(anchor(bad, "2027 m. degalų kainos")))

    def test_an_other_address_cannot_outrank_a_good_one(self):
        html = anchor("https://evil.example/x", "2030 m. degalų kainos") + anchor(LINK_2026, "2026 m. degalų kainos")
        self.assertEqual(up.find_xlsx_url(html), LINK_2026)

    def test_nothing_matching(self):
        self.assertIsNone(up.find_xlsx_url(anchor(LINK_2026, "Metinė ataskaita")))
        self.assertIsNone(up.find_xlsx_url(""))


class ResolveUrlTests(unittest.TestCase):
    def test_uses_the_page(self):
        with mock.patch.object(up, "fetch_page", return_value=anchor(LINK_2027, "2027 m. degalų kainos")):
            self.assertEqual(up.current_xlsx_url(), LINK_2027)

    def test_falls_back_when_the_page_fails(self):
        with mock.patch.object(up, "fetch_page", side_effect=OSError("down")):
            self.assertEqual(up.current_xlsx_url(), up.XLSX_URL)

    def test_falls_back_when_the_layout_changes(self):
        with mock.patch.object(up, "fetch_page", return_value="<html>new layout</html>"):
            self.assertEqual(up.current_xlsx_url(), up.XLSX_URL)


class HistoryTests(unittest.TestCase):
    def test_carries_history_into_a_new_file(self):
        old = [point("2026-12-30"), point("2026-12-31")]
        new = [point("2027-01-04", 2.0)]
        merged = up.merge_history(new, old, "2027-01-04")
        self.assertEqual([p["date"] for p in merged], ["2026-12-30", "2026-12-31", "2027-01-04"])

    def test_new_file_wins_on_the_same_day(self):
        merged = up.merge_history([point("2027-01-04", 2.0)], [point("2027-01-04", 1.0)], "2027-01-04")
        self.assertEqual(merged, [point("2027-01-04", 2.0)])

    def test_keeps_only_the_window(self):
        self.assertGreaterEqual(up.HISTORY_DAYS, 260)   # a year of working days for the 1Y chart
        start = dt.date(2025, 1, 1)
        old = [point((start + dt.timedelta(days=i)).isoformat()) for i in range(up.HISTORY_DAYS + 20)]
        latest = (start + dt.timedelta(days=up.HISTORY_DAYS + 20)).isoformat()
        merged = up.merge_history([point(latest)], old, latest)
        self.assertEqual(len(merged), up.HISTORY_DAYS)
        self.assertEqual(merged[-1]["date"], latest)
        self.assertEqual(merged[0]["date"], old[-(up.HISTORY_DAYS - 1)]["date"])

    def test_drops_days_after_the_files_own_date(self):
        merged = up.merge_history([point("2026-12-01")], [point("2026-12-02")], "2026-12-01")
        self.assertEqual([p["date"] for p in merged], ["2026-12-01"])

    def test_reads_history_from_prices_js(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write("window.FUEL_PRICES = " + json.dumps({"date": "2026-12-31", "history": [point("2026-12-31")]}) + ";\n")
            self.assertEqual(up.read_history(path), [point("2026-12-31")])

    def test_missing_or_broken_prices_js_gives_no_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.js")
            self.assertEqual(up.read_history(path), [])
            with open(path, "w") as f:
                f.write("not javascript")
            self.assertEqual(up.read_history(path), [])


class BuildTests(unittest.TestCase):
    def test_newest_history_point_matches_the_national_average(self):
        day = dt.date(2026, 10, 30)
        rows = [(day, "A", "M", "G 1", "petrol95", 1.900),
                (day, "A", "M", "G 1", "petrol95", 1.900),   # a duplicate row for the same station
                (day, "B", "M", "G 2", "petrol95", 2.000)]
        data = up.build(rows)
        self.assertEqual(data["national"]["petrol95"]["avg"], 1.95)
        self.assertEqual(data["history"][-1]["petrol95"], 1.95)
        self.assertIsNone(data["history"][-1]["diesel"])


class FreshnessTests(unittest.TestCase):
    def write(self, d, date):
        path = os.path.join(d, "prices.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write('window.FUEL_PRICES = {"date":"%s","history":[{"date":"2020-01-01"}]};\n' % date)
        return path

    def test_seven_days_is_still_fine(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(up.check_fresh(self.write(d, "2027-01-01"), dt.date(2027, 1, 8)), 0)

    def test_eight_days_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(up.check_fresh(self.write(d, "2026-12-31"), dt.date(2027, 1, 8)), 1)

    def test_missing_or_broken_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "prices.js")
            self.assertEqual(up.check_fresh(path, dt.date(2027, 1, 8)), 1)
            with open(path, "w") as f:
                f.write("not javascript")
            self.assertEqual(up.check_fresh(path, dt.date(2027, 1, 8)), 1)

    def test_workflow_runs_the_check_after_committing(self):
        with open(os.path.join(ROOT, ".github", "workflows", "update-prices.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("update_prices.py --check-fresh", text)
        self.assertLess(text.index("Commit new prices"), text.index("--check-fresh"))


class LocalFileTests(unittest.TestCase):
    def test_picks_the_newest_year(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("DK-2026.xlsx", "DK-2027.xlsx", "other.xlsx"):
                open(os.path.join(d, name), "w").close()
            self.assertEqual(up.newest_local_xlsx(d), os.path.join(d, "DK-2027.xlsx"))

    def test_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(up.newest_local_xlsx(d))


class PositionsTests(unittest.TestCase):
    ADDR = "Garliava, Vytauto g. 111A, 53258"

    def rows(self):
        day = dt.date(2026, 11, 14)
        return [(day, "UAB Alfa", "Kauno r. sav.", self.ADDR, "diesel", 1.9),
                (day, "UAB Beta", "Vilniaus m. sav.", "Vilnius, Gedimino pr. 1", "diesel", 1.8)]

    def run_main(self, d, extra, get):
        coords = os.path.join(d, "station-coords.json")
        out = os.path.join(d, "prices.js")
        with mock.patch.object(up, "parse", return_value=self.rows()), \
                mock.patch.object(up, "COORDS_FILE", coords), \
                mock.patch.object(up.geocode_stations, "http_get", get), \
                mock.patch("time.sleep"):
            code = up.main(["update_prices.py", "fake.xlsx", out] + extra)
        return code, coords, up.read_prices_js(out)

    def test_main_applies_cached_positions_without_lookups(self):
        def boom(url):
            raise AssertionError("network used")
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "station-coords.json"), "w") as f:
                json.dump({self.ADDR: {"g": [54.82, 23.87], "checked": "2026-11-01"}}, f)
            code, _, data = self.run_main(d, ["--no-geocode"], boom)
        self.assertEqual(code, 0)
        by_addr = {s["a"]: s for s in data["stations"]}
        self.assertEqual(by_addr[self.ADDR]["g"], [54.82, 23.87])
        self.assertNotIn("g", by_addr["Vilnius, Gedimino pr. 1"])

    def test_main_geocodes_and_saves_cache(self):
        def fake(url):
            if "photon" in url:
                return {"features": [{"geometry": {"coordinates": [23.87, 54.82]}, "properties": {"type": "house"}}]}
            return {"address": {"state_district": "Kauno rajono savivaldybė"}}
        with tempfile.TemporaryDirectory() as d:
            code, coords, data = self.run_main(d, [], fake)
            with open(coords, encoding="utf-8") as f:
                cache = json.load(f)
        self.assertEqual(code, 0)
        self.assertEqual(cache[self.ADDR]["g"], [54.82, 23.87])
        self.assertEqual([s["g"] for s in data["stations"] if s["a"] == self.ADDR], [[54.82, 23.87]])

    def test_main_logs_why_geocoding_stopped_and_passes_a_save_callback(self):
        def down(url):
            raise OSError("down")
        saves = []
        real = up.geocode_stations.update_cache

        def spy(stations, cache, today, get, **kw):
            saves.append(kw.get("save"))
            kw.setdefault("sleep", lambda seconds: None)
            return real(stations, cache, today, get, **kw)
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d, redirect_stdout(buf), \
                mock.patch.object(up.geocode_stations, "update_cache", spy):
            code, _, _ = self.run_main(d, [], down)
        self.assertEqual(code, 0)
        self.assertTrue(callable(saves[0]))
        self.assertRegex(buf.getvalue(), r"Positions: .*stopped early \(errors\)")

    def test_main_log_has_no_stop_note_when_all_went_well(self):
        def fake(url):
            if "photon" in url:
                return {"features": [{"geometry": {"coordinates": [23.87, 54.82]}, "properties": {"type": "house"}}]}
            return {"address": {"state_district": "Kauno rajono savivaldybė"}}
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d, redirect_stdout(buf):
            self.run_main(d, [], fake)
        self.assertNotIn("stopped", buf.getvalue())

    def test_workflow_commits_coords(self):
        with open(os.path.join(ROOT, ".github", "workflows", "update-prices.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("git add prices.js station-coords.json", text)
        self.assertIn("timeout-minutes: 45", text)
        self.assertIn("git diff --quiet -- station-coords.json", text)


if __name__ == "__main__":
    unittest.main()

"""Tests for route-stations.js, the pure route maths, called through the page."""
import functools
import http.server
import os
import re
import threading
import unittest

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAT = 54.9
ROUTE = [[LAT, 23.9], [LAT, 25.3]]
KM_LNG = 64.0  # km per degree of longitude at 54.9 N
KM_LAT = 110.57


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def st(addr, price, along_km, off_km, c="Circle K", field="p"):
    return {"c": c, "m": "X", "a": addr, field: price,
            "g": [LAT + off_km / KM_LAT, 23.9 + along_km / KM_LNG]}


class RouteStationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(Quiet, directory=ROOT)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel=os.environ.get("FC_BROWSER_CHANNEL") or None)
        cls.ctx = cls.browser.new_context(service_workers="block")
        cls.ctx.route(re.compile(r"/config\.js(\?.*)?$"), lambda r: r.abort())
        cls.page = cls.ctx.new_page()
        cls.page.goto(base + "/fuel-calculator.html")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, expr, arg=None):
        return self.page.evaluate("a => RouteStations." + expr, arg)

    def test_project_on_and_off_the_line(self):
        r = self.page.evaluate("([r, p]) => RouteStations.project(r, p)",
                               [ROUTE, [LAT + 0.5 / KM_LAT, 23.9 + 10 / KM_LNG]])
        self.assertAlmostEqual(r["alongKm"], 10, delta=0.1)
        self.assertAlmostEqual(r["offKm"], 0.5, delta=0.02)
        past = self.page.evaluate("([r, p]) => RouteStations.project(r, p)", [ROUTE, [LAT, 26.0]])
        end = self.page.evaluate("([r, p]) => RouteStations.project(r, p)", [ROUTE, ROUTE[1]])
        self.assertAlmostEqual(past["alongKm"], end["alongKm"], places=6)
        self.assertAlmostEqual(end["alongKm"], 1.4 * KM_LNG, delta=0.1)

    def corridor(self, stations, **opts):
        return self.page.evaluate("([s, r, o]) => RouteStations.corridor(s, r, o)", [stations, ROUTE, opts])

    def test_corridor_filters_distance_fuel_network(self):
        a, b, c = st("a", 1.8, 10, 0.5), st("b", 1.9, 20, 3), st("c", 1.7, 30, 0.2, c="Viada")
        stations = [a, b, c]
        self.assertEqual(len(self.corridor(stations, field="p", maxOffKm=2)), 2)
        self.assertEqual(len(self.corridor(stations, field="p", maxOffKm=5)), 3)
        nulled = dict(a, p=None)
        nog = {k: v for k, v in a.items() if k != "g"}
        self.assertEqual(len(self.corridor([nulled, nog, c], field="p", maxOffKm=5)), 1)
        got = self.corridor(stations, field="p", maxOffKm=5, network="Viada")
        self.assertEqual([i["station"]["c"] for i in got], ["Viada"])

    def test_corridor_ties_are_stable(self):
        s = [st("far", 1.8, 40, 0.5), st("near", 1.8, 10, 0.5)]
        first = [i["station"]["a"] for i in self.corridor(s, field="p", maxOffKm=2)]
        again = [i["station"]["a"] for i in self.corridor(list(reversed(s)), field="p", maxOffKm=2)]
        self.assertEqual(first, ["near", "far"])
        self.assertEqual(first, again)

    def items(self, a_price, c_price):
        return [{"station": {"a": "A"}, "price": a_price, "offKm": 0.5, "alongKm": 10},
                {"station": {"a": "C"}, "price": c_price, "offKm": 0.2, "alongKm": 60}]

    def recommend(self, items):
        return self.page.evaluate("([i]) => RouteStations.recommend(i, {fillL: 50, consPer100: 7.0})", [items])

    def test_recommend_numbers(self):
        r = self.recommend(self.items(1.8, 1.9))
        self.assertEqual(r["item"]["station"]["a"], "A")
        self.assertAlmostEqual(r["reference"], 1.85, places=6)
        self.assertAlmostEqual(r["saving"], 2.374, delta=0.001)

    def test_recommend_none_below_50_cents(self):
        self.assertIsNone(self.recommend(self.items(1.8, 1.805)))

    def test_insert_index(self):
        self.assertEqual(self.page.evaluate("RouteStations.insertIndex(35, [10, 50])"), 1)
        self.assertEqual(self.page.evaluate("RouteStations.insertIndex(5, [])"), 0)

    def test_shade_thirds(self):
        got = self.page.evaluate("[1.0, 1.1, 1.4, 1.5, 1.9, 2.0].map(p => RouteStations.shade(p, 1.0, 2.0))")
        self.assertEqual(got, [0, 0, 1, 1, 2, 2])
        self.assertEqual(self.page.evaluate("RouteStations.shade(1.5, 1.5, 1.5)"), 0)

    def test_sort_along(self):
        items = [{"price": 1.7, "alongKm": 30, "station": {"a": "z"}},
                 {"price": 1.9, "alongKm": 5, "station": {"a": "y"}}]
        got = self.page.evaluate("([i]) => RouteStations.sortItems(i, 'along')", [items])
        self.assertEqual([i["alongKm"] for i in got], [5, 30])
        by_price = self.page.evaluate("([i]) => RouteStations.sortItems(i, 'price')", [items])
        self.assertEqual([i["price"] for i in by_price], [1.7, 1.9])

    PERF_JS = """() => {
        const route = [];
        for (let i = 0; i < 7000; i++) route.push([54.2 + i * 0.0001 + Math.sin(i / 50) * 0.01, 23.0 + i * 0.0006]);
        const stations = [];
        for (let i = 0; i < 700; i++) {
            const r = route[(i * 10) % 7000];
            stations.push({c: "X", m: "Y", a: "Town, Street " + i, p: 1.7 + (i % 40) / 100,
                           g: [r[0] + ((i % 7) - 3) / 400, r[1] + ((i % 5) - 2) / 400]});
        }
        const t = performance.now();
        const out = RouteStations.corridor(stations, route, {field: "p", maxOffKm: 2});
        return [performance.now() - t, out.length];
    }"""

    def test_corridor_is_fast_on_a_long_route(self):
        self.page.evaluate(self.PERF_JS)   # warm up
        ms, n = min((self.page.evaluate(self.PERF_JS) for _ in range(3)), key=lambda r: r[0])
        self.assertGreater(n, 100)
        print("corridor 700 stations x 7000 points: %.1f ms" % ms)
        self.assertLess(ms, 40)

    def test_project_wrapper_matches_corridor(self):
        got = self.page.evaluate("""() => {
            const route = [[54.9, 23.9], [55.0, 24.3], [54.8, 24.9]];
            const s = {c: "X", m: "Y", a: "A", p: 1.5, g: [54.95, 24.2]};
            const c = RouteStations.corridor([s], route, {field: "p", maxOffKm: 50})[0];
            const p = RouteStations.project(route, s.g);
            return [c.offKm, p.offKm, c.alongKm, p.alongKm];
        }""")
        self.assertEqual(got[0], got[1])
        self.assertEqual(got[2], got[3])


if __name__ == "__main__":
    unittest.main()

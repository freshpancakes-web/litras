"""Browser tests for the Trip Fuel Calculator (fuel-calculator.html).

The repo root is served from a local http.server thread. The outside services (address search, routing,
map tiles) are mocked, config.js and prices.js are replaced per test, and Leaflet and the fonts load from
the real CDN. Run with:  python -m unittest discover -s tests -v
Locally set FC_BROWSER_CHANNEL=chrome to use the installed Chrome; CI uses Playwright's Chromium.
"""
import base64
import datetime
import functools
import http.server
import json
import os
import re
import subprocess
import threading
import unittest
import urllib.parse

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "prices.js")
PAGE = "fuel-calculator.html"

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*"}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def photon_default(q):
    """One Photon feature whose name is the first part of the query."""
    name = q.split(",")[0].strip() or "Place"
    return {"features": [{
        "geometry": {"type": "Point", "coordinates": [24.0 + len(name) / 100, 54.9]},
        "properties": {"name": name, "country": "Lithuania"},
    }]}


def osrm_default():
    return osrm_legs([(100000, 4200)])


def osrm_legs(legs):
    """An OSRM response whose route is made of the given (metres, seconds) legs."""
    coords = [[25.28 - i * 0.2, 54.69 + i * 0.1] for i in range(len(legs) + 1)]
    return {"code": "Ok", "routes": [{
        "distance": sum(m for m, _ in legs), "duration": sum(s for _, s in legs),
        "geometry": {"type": "LineString", "coordinates": coords},
        "legs": [{"distance": m, "duration": s} for m, s in legs],
    }]}


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=ROOT)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        channel = os.environ.get("FC_BROWSER_CHANNEL") or None
        cls.browser = cls.pw.chromium.launch(channel=channel)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.contexts = []
        self.tile_urls = []
        self.routes = {"photon": photon_default, "osrm": osrm_default(), "ors": None}
        self.addCleanup(self.close_contexts)

    def close_contexts(self):
        for c in self.contexts:
            c.close()

    # ----- helpers -----

    def open(self, theme="light", width=1280, height=900, key=None, prices="fixture"):
        """Open the app in a fresh browser context with the outside services mocked."""
        self.tile_urls = []
        ctx = self.browser.new_context(
            viewport={"width": width, "height": height}, color_scheme=theme, locale="en-GB",
        )
        self.contexts.append(ctx)
        self.context = ctx
        ctx.route(re.compile(r"/config\.js(\?.*)?$"), lambda r: self._config(r, key))
        ctx.route(re.compile(r"/prices\.js(\?.*)?$"), lambda r: self._prices(r, prices))
        ctx.route(re.compile(r"^https://photon\.komoot\.io/"), self._photon)
        ctx.route(re.compile(r"^https://router\.project-osrm\.org/"), self._osrm)
        ctx.route(re.compile(r"^https://api\.openrouteservice\.org/"), self._ors)
        ctx.route(re.compile(r"^https://(tile\.openstreetmap\.org|[^/]*basemaps\.cartocdn\.com)/"), self._tile)
        page = ctx.new_page()
        self.page = page
        page.goto(self.base + "/" + PAGE)
        page.wait_for_selector(".leaflet-container")
        return page

    def _config(self, route, key):
        if key is None:
            route.abort()
        else:
            route.fulfill(content_type="text/javascript",
                          body='window.FC_CONFIG = { cartoKey: "%s" };' % key)

    def _prices(self, route, mode):
        if mode == "none":
            route.abort()
            return
        with open(FIXTURE, encoding="utf-8") as f:
            body = f.read().replace("__TODAY__", datetime.date.today().isoformat())
        route.fulfill(content_type="text/javascript; charset=utf-8", body=body)

    def _json(self, route, data, status=200):
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, headers=CORS)
            return
        route.fulfill(status=status, content_type="application/json", headers=CORS, body=json.dumps(data))

    def _photon(self, route):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query).get("q", [""])[0]
        handler = self.routes["photon"]
        self._json(route, handler(q) if callable(handler) else handler)

    def _osrm(self, route):
        self._json(route, self.routes["osrm"])

    def _ors(self, route):
        self._json(route, self.routes["ors"] or {"error": "no mock"}, 200 if self.routes["ors"] else 500)

    def _tile(self, route):
        self.tile_urls.append(route.request.url)
        route.fulfill(content_type="image/png", headers=CORS, body=PNG)

    def text(self, id_):
        return self.page.inner_text("#" + id_).strip()

    def value(self, id_):
        return self.page.input_value("#" + id_)

    def wait_tiles(self):
        self.page.wait_for_selector(".leaflet-tile")
        self.page.wait_for_load_state("networkidle")

    # ----- prices and results -----

    def test_default_trip_costs(self):
        self.open()
        self.assertEqual(self.text("rCost"), "13.71")
        self.assertEqual(self.text("rKm"), "100.0 km")
        self.assertEqual(self.value("price"), "1.959")
        self.assertIn("live", self.page.get_attribute("#priceState", "class").split())

    def test_missing_prices_uses_bundled(self):
        self.open(prices="none")
        self.assertEqual(self.value("price"), "1.925")
        self.assertEqual(self.text("priceState"), "bundled")

    def test_network_cheapest_changes_price(self):
        page = self.open()
        page.select_option("#priceNetwork", "Šiaulių degalinė")
        page.locator('label:has(input[name="basis"][value="min"])').click()
        self.assertEqual(self.value("price"), "1.9")
        # the list sits in a closed <details>, so read textContent rather than rendered text
        self.assertIn("Šiaulių degalinė", page.text_content("#stationList"))

    # ----- route legs -----

    def test_stop_shows_legs_and_cycle_changes_them(self):
        page = self.open()
        self.routes["osrm"] = osrm_legs([(60000, 3000), (40000, 2400)])
        page.click("#addStop")
        page.fill("#stop1In", "Kedainiai")
        page.click("#routeBtn")
        page.wait_for_selector("#legs:not([hidden])")
        legs = page.locator("#legs li")
        self.assertEqual(legs.count(), 2)
        before = legs.nth(0).inner_text()
        page.locator('label:has(input[name="cycle"][value="highway"])').click()
        self.assertNotEqual(legs.nth(0).inner_text(), before)
        page.fill("#distance", "80")
        page.wait_for_selector("#legs", state="hidden")

    # ----- saved trips -----

    def test_saved_trip_survives_reload(self):
        page = self.open()
        page.check("#roundTrip")
        page.fill("#perWeek", "5")
        page.click("#saveTripBtn")
        page.fill("#tripName", "Home → work")
        page.click("#saveTrip button[type=submit]")
        self.assertIn("Home → work", self.text("tripList"))
        page.reload()
        page.wait_for_selector(".leaflet-container")
        row = page.locator("#tripList li .open")
        self.assertEqual(row.count(), 1)
        self.assertIn("Home → work", row.inner_text())
        page.fill("#perWeek", "")
        page.uncheck("#roundTrip")
        row.click()
        self.assertEqual(self.value("perWeek"), "5")
        self.assertTrue(page.is_checked("#roundTrip"))

    # ----- theme -----

    def test_theme_is_remembered(self):
        page = self.open()
        self.assertEqual(page.get_attribute("html", "data-theme"), "light")
        page.click("#themeBtn")
        after_click = page.get_attribute("html", "data-theme")
        self.assertEqual(after_click, "dark")
        page.reload()
        page.wait_for_selector(".leaflet-container")
        self.assertEqual(page.get_attribute("html", "data-theme"), after_click)
        self.assertEqual(page.evaluate("localStorage.getItem('fc.theme')"), '"dark"')

    # ----- map tiles -----

    def test_hosted_map_never_uses_keyless_carto(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page = self.open(theme=theme, key=None)
                self.wait_tiles()
                self.assertTrue(self.tile_urls)
                for url in self.tile_urls:
                    self.assertTrue(url.startswith("https://tile.openstreetmap.org/"), url)
                has_dark = page.evaluate("document.getElementById('map').classList.contains('osm-dark')")
                self.assertEqual(has_dark, theme == "dark")

    def test_key_uses_carto_in_dark(self):
        self.open(theme="dark", key="test-key")
        self.wait_tiles()
        self.assertTrue(self.tile_urls)
        for url in self.tile_urls:
            self.assertIn("rastertiles/dark_all", url)
            self.assertIn("key=test-key", url)

    # ----- layout and credits -----

    def test_no_sideways_scroll(self):
        for width in (360, 768, 1280):
            with self.subTest(width=width):
                page = self.open(width=width)
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))

    def test_attribution_visible(self):
        self.open()
        self.page.wait_for_selector(".leaflet-control-attribution")
        self.assertIn("OpenStreetMap", self.text_of(".leaflet-control-attribution"))
        self.assertIn("Lithuanian Energy Agency", self.text("priceNote"))

    def text_of(self, selector):
        return self.page.inner_text(selector)

    # ----- keyboard support for address suggestions -----

    def three_places(self, q):
        names = ["Panevezys", "Pasvalys", "Pakruojis"]
        return {"features": [{
            "geometry": {"type": "Point", "coordinates": [24.0 + i / 10, 55.0]},
            "properties": {"name": n, "country": "Lithuania"},
        } for i, n in enumerate(names)]}

    def open_suggestions(self, field="dest"):
        """Open the app with 3 suggestions showing for the given input; returns (page, osrm_requests)."""
        self.routes["photon"] = self.three_places
        page = self.open()
        osrm = []
        page.on("request", lambda r: osrm.append(r.url) if "router.project-osrm.org" in r.url else None)
        if field.startswith("stop"):
            page.click("#addStop")
        page.click("#" + field)
        page.fill("#" + field, "")
        page.type("#" + field, "Pan")
        page.wait_for_selector("#%s ~ .sugg li, .sugg:not([hidden]) li" % field)
        self.assertEqual(page.locator(".sugg:not([hidden]) li").count(), 3)
        return page, osrm

    def active_state(self, page, field):
        return page.evaluate("""(id) => {
            const input = document.getElementById(id);
            const opts = [...document.getElementById(input.getAttribute('aria-controls')).querySelectorAll('li')];
            const act = opts.map((li) => li.querySelector('button').classList.contains('active'));
            return {index: act.indexOf(true), count: act.filter(Boolean).length,
                    ad: input.getAttribute('aria-activedescendant'), ids: opts.map((li) => li.id)};
        }""", field)

    def check_arrows(self, page, field):
        def at(i):
            st = self.active_state(page, field)
            self.assertEqual((st["index"], st["count"]), (i, 1))
            self.assertEqual(st["ad"], st["ids"][i])
        page.press("#" + field, "ArrowDown"); at(0)
        page.press("#" + field, "ArrowDown")
        page.press("#" + field, "ArrowDown"); at(2)
        page.press("#" + field, "ArrowDown"); at(0)
        page.press("#" + field, "ArrowUp"); at(2)

    def test_arrow_keys_move_highlight(self):
        page, _ = self.open_suggestions("dest")
        self.check_arrows(page, "dest")
        self.assertTrue(self.active_state(page, "dest")["ids"][0].startswith("destList-opt-"))

    def test_enter_picks_highlighted_without_routing(self):
        page, osrm = self.open_suggestions("dest")
        page.press("#dest", "ArrowDown")
        page.press("#dest", "Enter")
        self.assertEqual(self.value("dest"), "Panevezys, Lithuania")
        self.assertTrue(page.locator("#destList").is_hidden())
        page.wait_for_timeout(500)
        self.assertEqual(osrm, [])

    def test_enter_without_highlight_routes(self):
        page, osrm = self.open_suggestions("dest")
        page.press("#dest", "Enter")
        page.wait_for_timeout(1000)
        self.assertTrue(osrm)

    def test_escape_closes_and_clears(self):
        page, _ = self.open_suggestions("dest")
        page.press("#dest", "ArrowDown")
        page.press("#dest", "Escape")
        self.assertTrue(page.locator("#destList").is_hidden())
        self.assertIsNone(page.get_attribute("#dest", "aria-activedescendant"))

    def test_stop_field_has_keyboard_support(self):
        page, osrm = self.open_suggestions("stop1In")
        self.check_arrows(page, "stop1In")
        page.press("#stop1In", "ArrowDown")  # wraps to first
        page.press("#stop1In", "Enter")
        self.assertEqual(self.value("stop1In"), "Panevezys, Lithuania")
        self.assertTrue(page.locator("#stop1List").is_hidden())
        page.wait_for_timeout(500)
        self.assertEqual(osrm, [])

    # ----- secrets -----

    def test_no_secret_tracked(self):
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
        files = [f for f in out.decode("utf-8").split("\0") if f]
        self.assertNotIn("config.js", files)
        prefix = ("cb1" + "_").encode()
        for f in files:
            path = os.path.join(ROOT, f)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                self.assertNotIn(prefix, fh.read(), f)


if __name__ == "__main__":
    unittest.main()

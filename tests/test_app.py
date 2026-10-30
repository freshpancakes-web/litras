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


# A controllable navigator.geolocation. Modes: allow, denied, unavailable, hold (never answers until
# window.__geo.answer() is called), none (the browser has no geolocation at all).
GEO_STUB = """
(() => {
  const g = window.__geo = { mode: "__MODE__", calls: 0, ok: null,
    answer() { g.ok({ coords: { latitude: 54.7, longitude: 25.3, accuracy: 10 } }); } };
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: g.mode === "none" ? undefined : {
    getCurrentPosition(ok, err) {
      g.calls++; g.ok = ok;
      if (g.mode === "allow") setTimeout(g.answer, 0);
      if (g.mode === "denied") setTimeout(() => err({ code: 1, message: "denied" }), 0);
      if (g.mode === "unavailable") setTimeout(() => err({ code: 2, message: "unavailable" }), 0);
    } } });
})();
"""
REVERSE_REPLY = {"features": [{"geometry": {"coordinates": [25.3, 54.7]}, "properties": {
    "name": "Cyclocity", "street": "Gediminas Avenue", "city": "Vilnius", "country": "Lithuania"}}]}


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
        self.routes = {"photon": photon_default, "osrm": osrm_default(), "ors": None, "reverse": REVERSE_REPLY}
        self.reverse_requests = []
        self.addCleanup(self.close_contexts)

    def close_contexts(self):
        for c in self.contexts:
            c.close()

    # ----- helpers -----

    def open(self, theme="light", width=1280, height=900, key=None, prices="fixture", history=(), geo="hold"):
        """Open the app in a fresh browser context with the outside services mocked."""
        self.tile_urls = []
        self.history = list(history)
        ctx = self.browser.new_context(
            viewport={"width": width, "height": height}, color_scheme=theme, locale="en-GB",
        )
        self.contexts.append(ctx)
        self.context = ctx
        ctx.add_init_script(GEO_STUB.replace("__MODE__", geo))
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
            day = datetime.date.today() - datetime.timedelta(days=5 if mode == "old" else 0)
            body = f.read().replace("__TODAY__", day.isoformat())
        body = body.replace('"history": []', '"history": ' + json.dumps(self.history))
        route.fulfill(content_type="text/javascript; charset=utf-8", body=body)

    def _json(self, route, data, status=200):
        if route.request.method == "OPTIONS":
            route.fulfill(status=204, headers=CORS)
            return
        route.fulfill(status=status, content_type="application/json", headers=CORS, body=json.dumps(data))

    def _photon(self, route):
        if "/reverse" in route.request.url:
            self.reverse_requests.append(route.request.url)
            reply = self.routes["reverse"]
            if reply is None:
                route.abort()
            else:
                self._json(route, reply)
            return
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

    def test_stale_prices_on_http_do_not_mention_the_script(self):
        self.open(prices="old")
        note = self.text("priceNote")
        self.assertIn("This data is 5 days old. Go online to refresh it.", note)
        self.assertNotIn("update_prices.py", note)

    def test_missing_prices_on_http_do_not_mention_the_script(self):
        self.open(prices="none")
        note = self.text("priceNote")
        self.assertIn("prices.js was not found", note)
        self.assertNotIn("update_prices.py", note)

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
        page.fill("#origin", "Vilnius")
        page.fill("#dest", "Kaunas")
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
        page.fill("#origin", "Vilnius")
        page.fill("#dest", "Kaunas")
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

    # ----- name and logo -----

    def test_page_shows_the_name_and_logo(self):
        page = self.open()
        self.assertEqual(page.title(), "Litras: trip fuel calculator")
        self.assertEqual(page.inner_text("h1"), "Litras")
        self.assertIn("Fuel use and cost", page.inner_text("header"))
        self.assertGreater(page.evaluate("document.querySelector('header img').naturalWidth"), 0)
        self.assertEqual(page.get_attribute("header img", "alt"), "")
        self.assertEqual(page.get_attribute('link[rel="icon"]', "href"), "icons/icon.svg")

    def test_old_name_is_gone_from_what_people_see(self):
        for name in ("index.html", "manifest.webmanifest", "README.md", "fuel-calculator.html"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                self.assertNotIn("trip fuel calculator</", f.read().lower().replace("litras: trip fuel calculator</", ""), name)

    def test_icons_are_the_right_size_and_home_screen_icon_has_no_transparency(self):
        for name, size, color_type in (("icon-180.png", 180, 2), ("icon-192.png", 192, 6),
                                       ("icon-512.png", 512, 6), ("icon-maskable-512.png", 512, 2)):
            with self.subTest(name), open(os.path.join(ROOT, "icons", name), "rb") as f:
                head = f.read(26)
                self.assertEqual(int.from_bytes(head[16:20], "big"), size)
                self.assertEqual(head[25], color_type)   # 2 = no alpha, 6 = alpha

    # ----- empty start and current location -----

    def wait_location(self, page, expected):
        page.wait_for_function("(v) => document.getElementById('origin').value === v", arg=expected)

    def test_starts_empty_with_no_pins(self):
        page = self.open()
        self.assertEqual(self.value("origin"), "")
        self.assertEqual(self.value("dest"), "")
        self.assertEqual(page.locator(".pin").count(), 0)
        self.assertTrue(page.locator("#locMsg").is_hidden())
        self.assertEqual(self.text("rCost"), "13.71")

    def test_calculate_with_empty_fields_asks_for_them(self):
        page = self.open()
        page.click("#routeBtn")
        page.wait_for_function("document.getElementById('routeMsg').textContent !== 'Calculating...'")
        self.assertEqual(self.text("routeMsg"), "Enter both From and To.")

    def test_asks_for_location_on_opening(self):
        page = self.open()
        self.assertEqual(page.evaluate("window.__geo.calls"), 1)

    def test_location_fills_from_without_business_names(self):
        page = self.open(geo="allow")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")
        self.assertEqual(self.value("dest"), "")
        self.assertEqual(page.locator(".pin").count(), 1)
        self.assertIn("lat=54.7", self.reverse_requests[0])
        self.assertIn("lon=25.3", self.reverse_requests[0])

    def test_real_browser_geolocation_api(self):
        page = self.open(geo="hold")
        self.context.grant_permissions(["geolocation"])
        self.context.set_geolocation({"latitude": 54.7, "longitude": 25.3})
        page.evaluate("delete navigator.geolocation")   # back to the browser's own API
        page.click("#useLocation")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")

    def test_route_uses_the_exact_coordinates(self):
        page = self.open(geo="allow")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")
        page.fill("#dest", "Kaunas, Lithuania")
        with page.expect_request(lambda r: "router.project-osrm.org" in r.url) as req:
            page.click("#routeBtn")
        self.assertIn("/25.3,54.7;", req.value.url)

    def test_failed_street_lookup_says_my_location(self):
        self.routes["reverse"] = None
        page = self.open(geo="allow")
        self.wait_location(page, "My location")
        self.assertEqual(page.locator(".pin").count(), 1)

    def test_no_address_in_reply_says_my_location(self):
        self.routes["reverse"] = {"features": []}
        page = self.open(geo="allow")
        self.wait_location(page, "My location")

    def test_denied_stays_quiet_and_is_not_asked_again(self):
        page = self.open(geo="denied")
        page.wait_for_function("localStorage.getItem('fc.locationDenied') === 'true'")
        self.assertEqual(self.value("origin"), "")
        self.assertTrue(page.locator("#locMsg").is_hidden())
        page.reload()
        page.wait_for_selector(".leaflet-container")
        self.assertEqual(page.evaluate("window.__geo.calls"), 0)

    def test_button_after_denied_explains_then_works_when_allowed(self):
        page = self.open(geo="denied")
        page.wait_for_function("localStorage.getItem('fc.locationDenied') === 'true'")
        page.click("#useLocation")
        page.wait_for_selector("#locMsg:not([hidden])")
        self.assertIn("browser's settings", self.text("locMsg"))
        self.assertFalse(page.is_disabled("#useLocation"))
        page.evaluate("window.__geo.mode = 'allow'")
        page.click("#useLocation")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")
        self.assertTrue(page.locator("#locMsg").is_hidden())
        self.assertIsNone(page.evaluate("JSON.parse(localStorage.getItem('fc.locationDenied'))"))

    def test_unavailable_location_is_explained_only_on_the_button(self):
        page = self.open(geo="unavailable")
        page.wait_for_function("window.__geo.calls === 1")
        page.wait_for_timeout(100)
        self.assertTrue(page.locator("#locMsg").is_hidden())
        self.assertIsNone(page.evaluate("localStorage.getItem('fc.locationDenied')"))
        page.click("#useLocation")
        page.wait_for_selector("#locMsg:not([hidden])")
        self.assertIn("Type your address", self.text("locMsg"))

    def test_browser_without_location_explains_on_the_button(self):
        page = self.open(geo="none")
        self.assertTrue(page.locator("#locMsg").is_hidden())
        page.click("#useLocation")
        self.assertIn("Type your address", self.text("locMsg"))

    def test_late_location_does_not_overwrite_typing(self):
        page = self.open(geo="hold")
        page.fill("#origin", "Kaun")
        page.evaluate("window.__geo.answer()")
        page.wait_for_timeout(300)
        self.assertEqual(self.value("origin"), "Kaun")
        self.assertEqual(self.reverse_requests, [])
        self.assertEqual(page.locator(".pin").count(), 0)

    def test_button_replaces_what_is_there(self):
        page = self.open(geo="hold")
        page.fill("#origin", "Kaunas")
        page.evaluate("window.__geo.mode = 'allow'")
        page.click("#useLocation")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")

    def test_location_is_not_stored(self):
        page = self.open(geo="allow")
        self.wait_location(page, "Gediminas Avenue, Vilnius, Lithuania")
        stored = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
        self.assertNotIn("54.7", stored)
        self.assertNotIn("Gediminas", stored)

    def test_save_form_has_no_placeholder_name_when_empty(self):
        page = self.open()
        page.click("#saveTripBtn")
        self.assertEqual(self.value("tripName"), "")

    # ----- price trend -----

    TREND = [
        {"date": "2026-10-05", "petrol95": 1.931, "diesel": 2.200, "lpg": None},
        {"date": "2026-10-06", "petrol95": 1.950, "diesel": 2.210, "lpg": 0.900},
        {"date": "2026-10-07", "petrol95": 1.970, "diesel": 2.220, "lpg": None},
        {"date": "2026-10-08", "petrol95": 1.960, "diesel": 2.230, "lpg": 0.900},
        {"date": "2026-10-09", "petrol95": 1.940, "diesel": 2.240, "lpg": 0.900},
        {"date": "2026-10-12", "petrol95": 1.920, "diesel": 2.250, "lpg": None},
        {"date": "2026-10-13", "petrol95": 1.905, "diesel": 2.250, "lpg": 0.900},
        {"date": "2026-10-14", "petrol95": 1.908, "diesel": 2.248, "lpg": 0.900},
    ]

    def add_car(self, page, name, fuel):
        page.locator("summary", has_text="Add another car").click()
        page.fill("#newName", name)
        page.select_option("#newFuel", fuel)
        page.click("#addCar button[type=submit]")

    @staticmethod
    def long_history(first, last, step=1):
        """Working days from first to last, with a price rising 0.001 per point."""
        day, out = first, []
        while day <= last:
            if day.weekday() < 5:
                out.append({"date": day.isoformat(), "petrol95": round(1.800 + 0.001 * len(out), 3), "diesel": None, "lpg": None})
            day += datetime.timedelta(days=step)
        return out

    def point_xy(self, page, index):
        """Page coordinates of a point on the drawn line, scrolled into view."""
        page.locator("#trendChart").scroll_into_view_if_needed()
        pts = page.get_attribute("#trendChart .trend-line", "points").split()
        x, y = (float(n) for n in pts[index].split(","))
        box = page.locator("#trendChart").bounding_box()
        return box["x"] + x, box["y"] + y

    def pick_range(self, page, value):
        page.locator('label:has(input[name="trendRange"][value="%s"])' % value).click()

    def test_trend_states_change_for_the_cars_fuel(self):
        page = self.open(history=self.TREND)
        self.assertTrue(page.locator("#priceTrend").is_visible())
        self.assertEqual(self.text("trendText"), "National average 1.908 EUR/l. Down 2.3 ct since 5 Oct.")

    def test_trend_follows_the_selected_car(self):
        page = self.open(history=self.TREND)
        self.add_car(page, "Test diesel", "diesel")
        self.assertEqual(self.text("trendText"), "National average 2.248 EUR/l. Up 4.8 ct since 5 Oct.")

    def test_trend_skips_gaps_in_the_data(self):
        page = self.open(history=self.TREND)
        self.add_car(page, "Test LPG", "lpg")
        self.assertEqual(self.text("trendText"), "National average 0.900 EUR/l. Unchanged since 6 Oct.")
        self.assertEqual(page.locator("#trendChart .trend-dot").count(), 1)

    def test_trend_chart_draws_every_point_and_is_described(self):
        page = self.open(history=self.TREND)
        points = page.get_attribute("#trendChart .trend-line", "points").split()
        self.assertEqual(len(points), len(self.TREND))
        ys = [float(p.split(",")[1]) for p in points]
        # Highest price (third point) is drawn highest; lowest (seventh) lowest. SVG y grows downwards.
        self.assertEqual(ys.index(min(ys)), 2)
        self.assertEqual(ys.index(max(ys)), 6)
        self.assertEqual(page.get_attribute("#trendChart", "role"), "img")
        self.assertIn("Down 2.3 ct", page.get_attribute("#trendChart", "aria-label"))

    def test_trend_hidden_without_enough_data(self):
        cases = {"no history": dict(history=[]), "one point": dict(history=self.TREND[:1]),
                 "no prices.js": dict(prices="none", history=self.TREND)}
        for name, kw in cases.items():
            with self.subTest(name):
                page = self.open(**kw)
                self.assertTrue(page.locator("#priceTrend").is_hidden())

    def test_trend_fits_a_phone_in_both_themes(self):
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page = self.open(theme=theme, width=360, history=self.TREND)
                self.assertTrue(page.locator("#priceTrend").is_visible())
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 360)

    # ----- trend ranges -----

    def test_ranges_show_the_right_number_of_points(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        count = lambda: len(page.get_attribute("#trendChart .trend-line", "points").split())
        self.assertTrue(page.is_checked('input[name="trendRange"][value="30d"]'))
        self.assertEqual(count(), 30)
        self.pick_range(page, "5d")
        self.assertEqual(count(), 5)
        self.pick_range(page, "1y")
        self.assertEqual(count(), len(history))

    def test_text_follows_the_range(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        self.pick_range(page, "5d")
        self.assertEqual(self.text("trendText"),
                         "National average %.3f EUR/l. Up 0.4 ct since 8 Oct." % history[-1]["petrol95"])

    def test_one_year_says_when_the_data_starts(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        self.assertNotIn("Data starts", self.text("trendText"))
        self.pick_range(page, "1y")
        self.assertIn("Data starts 8 Apr 2026.", self.text("trendText"))

    def test_one_year_stops_at_twelve_months(self):
        history = self.long_history(datetime.date(2025, 1, 1), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        self.pick_range(page, "1y")
        self.assertNotIn("Data starts", self.text("trendText"))
        kept = [h for h in history if h["date"] >= "2025-10-14"]
        self.assertEqual(len(page.get_attribute("#trendChart .trend-line", "points").split()), len(kept))

    def test_range_is_remembered(self):
        page = self.open(history=self.TREND)
        self.pick_range(page, "5d")
        page.reload()
        page.wait_for_selector("#priceTrend:not([hidden])")
        self.assertTrue(page.is_checked('input[name="trendRange"][value="5d"]'))
        self.assertEqual(len(page.get_attribute("#trendChart .trend-line", "points").split()), 5)

    def test_axes_label_time_and_price(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        self.pick_range(page, "1y")
        months = page.locator("#trendChart .trend-xtick").all_text_contents()
        for month in ("May", "Jul", "Oct"):
            self.assertIn(month, months)
        prices = page.locator("#trendChart .trend-ytick").all_text_contents()
        self.assertIn("%.3f" % history[0]["petrol95"], prices)
        self.assertIn("%.3f" % history[-1]["petrol95"], prices)
        self.pick_range(page, "5d")
        days = page.locator("#trendChart .trend-xtick").all_text_contents()
        self.assertIn("14 Oct", days)

    # ----- trend hover, touch and keyboard -----

    def test_hover_shows_the_date_price_and_change(self):
        page = self.open(history=self.TREND)
        self.assertTrue(page.locator("#trendTip").is_hidden())
        page.mouse.move(*self.point_xy(page, 3))
        self.assertTrue(page.locator("#trendTip").is_visible())
        tip = self.text("trendTip")
        self.assertIn("8 Oct 2026", tip)
        self.assertIn("1.960 EUR/l", tip)
        self.assertIn("+2.9 ct", tip)
        self.assertTrue(page.locator("#trendChart .trend-cursor").is_visible())
        page.mouse.move(5, 5)
        self.assertTrue(page.locator("#trendTip").is_hidden())
        self.assertEqual(page.locator("#trendChart .trend-cursor").count(), 0)

    def test_tip_does_not_cover_the_chart(self):
        for width in (1280, 360):
            with self.subTest(width=width):
                page = self.open(width=width, history=self.TREND)
                page.mouse.move(*self.point_xy(page, 3))
                tip = page.locator("#trendTip").bounding_box()
                chart = page.locator("#trendChart").bounding_box()
                self.assertLessEqual(tip["y"] + tip["height"], chart["y"])

    def test_date_labels_do_not_overlap(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        for width in (1280, 360):
            for rng in ("5d", "30d", "1y"):
                with self.subTest(width=width, range=rng):
                    page = self.open(width=width, history=history)
                    self.pick_range(page, rng)
                    boxes = page.evaluate("""[...document.querySelectorAll('#trendChart .trend-xtick')]
                        .map((t) => { const r = t.getBoundingClientRect(); return [r.left, r.right]; })""")
                    self.assertGreaterEqual(len(boxes), 2)
                    for (_, right), (left, _) in zip(boxes, boxes[1:]):
                        self.assertLess(right, left)

    def test_hover_on_the_first_point_has_no_change(self):
        page = self.open(history=self.TREND)
        page.mouse.move(*self.point_xy(page, 0))
        self.assertIn("Start of this range", self.text("trendTip"))

    def test_hover_shows_the_month_on_the_year_chart(self):
        history = self.long_history(datetime.date(2026, 4, 8), datetime.date(2026, 10, 14))
        page = self.open(history=history)
        self.pick_range(page, "1y")
        page.mouse.move(*self.point_xy(page, 40))
        day = datetime.date.fromisoformat(history[40]["date"])
        self.assertIn(day.strftime("%b %Y"), self.text("trendTip"))

    def test_tip_stays_inside_the_screen_on_a_phone(self):
        ctx_page = self.open(width=360, history=self.TREND)
        for index in (0, len(self.TREND) - 1):
            with self.subTest(index=index):
                ctx_page.locator("#trendChart").scroll_into_view_if_needed()
                ctx_page.mouse.move(*self.point_xy(ctx_page, index))
                box = ctx_page.locator("#trendTip").bounding_box()
                self.assertGreaterEqual(box["x"], 0)
                self.assertLessEqual(box["x"] + box["width"], 360)

    def test_touch_shows_the_tip(self):
        self.tile_urls = []
        self.history = list(self.TREND)
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, locale="en-GB")
        self.contexts.append(ctx)
        ctx.route(re.compile(r"/config\.js(\?.*)?$"), lambda r: self._config(r, None))
        ctx.route(re.compile(r"/prices\.js(\?.*)?$"), lambda r: self._prices(r, "fixture"))
        ctx.route(re.compile(r"^https://(tile\.openstreetmap\.org|[^/]*basemaps\.cartocdn\.com)/"), self._tile)
        page = ctx.new_page()
        self.page = page
        page.goto(self.base + "/" + PAGE)
        page.wait_for_selector("#priceTrend:not([hidden])")
        page.locator("#trendChart").scroll_into_view_if_needed()
        page.touchscreen.tap(*self.point_xy(page, 3))
        self.assertIn("8 Oct 2026", self.text("trendTip"))

    def test_keyboard_moves_through_the_points(self):
        page = self.open(history=self.TREND)
        page.focus("#trendChart")
        self.assertIn("14 Oct 2026", self.text("trendTip"))
        page.keyboard.press("ArrowLeft")
        self.assertIn("13 Oct 2026", self.text("trendTip"))
        page.keyboard.press("Home")
        self.assertIn("5 Oct 2026", self.text("trendTip"))
        page.keyboard.press("ArrowLeft")
        self.assertIn("5 Oct 2026", self.text("trendTip"))
        page.keyboard.press("End")
        self.assertIn("14 Oct 2026", self.text("trendTip"))
        page.keyboard.press("Escape")
        self.assertTrue(page.locator("#trendTip").is_hidden())

    def test_changing_range_clears_the_tip(self):
        page = self.open(history=self.TREND)
        page.mouse.move(*self.point_xy(page, 3))
        self.pick_range(page, "5d")
        self.assertTrue(page.locator("#trendTip").is_hidden())

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
        page.fill("#origin", "Vilnius, Lithuania")
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

    def test_typing_resets_highlight(self):
        page, osrm = self.open_suggestions("dest")
        page.press("#dest", "ArrowDown")
        page.type("#dest", "e")
        self.assertIsNone(page.get_attribute("#dest", "aria-activedescendant"))
        page.press("#dest", "Enter")
        page.wait_for_timeout(1000)
        self.assertTrue(osrm)   # routed from the typed text, rather than picking the old suggestion

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

    def test_file_url_has_no_service_worker(self):
        ctx = self.browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
        self.contexts.append(ctx)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route(re.compile(r"^https?://"), lambda r: r.abort())
        page.goto("file://" + os.path.join(ROOT, PAGE))
        page.wait_for_selector("#priceState")
        self.assertTrue(page.input_value("#price"))
        self.assertTrue(page.inner_text("#rCost").strip())
        self.assertFalse(page.evaluate("navigator.serviceWorker ? !!navigator.serviceWorker.controller : false"))
        regs = page.evaluate("navigator.serviceWorker ? navigator.serviceWorker.getRegistrations().then(r => r.length, () => 0) : 0")
        self.assertEqual(regs, 0)
        self.assertEqual(errors, [])

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

"""Install and offline tests for the Trip Fuel Calculator.

These run the real service worker (sw.js) against a local server whose prices.js and config.js can change
between loads, so the worker sees real responses. Going offline is context.set_offline(True) plus State.down, which makes the
server drop every connection (set_offline alone does not reach the worker's own fetch).
Run with:  python -m unittest tests.test_offline -v   (locally set FC_BROWSER_CHANNEL=chrome)
"""
import base64
import datetime
import functools
import http.server
import json
import os
import re
import struct
import threading
import time
import unittest
import urllib.parse

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "prices.js")
PAGE = "fuel-calculator.html"
OFFLINE_NOTE = "You're offline. The map and new routes need a connection. Saved trips and prices still work."
FAKE_KEY = "fake" + "-test-key-0000"
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def fmt_date(d):
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


class State:
    prices_date = datetime.date.today()
    prices_status = 200
    config = None
    config_delay = 0
    sw_suffix = ""
    down = False


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if State.down:
            self.close_connection = True   # no response at all, like a dead network
            return
        if path == "/sw.js":
            with open(os.path.join(ROOT, "sw.js"), encoding="utf-8") as f:
                body = (f.read() + State.sw_suffix).encode("utf-8")
            return self.send_body(200, "text/javascript", body)
        if path == "/prices.js":
            if State.prices_status != 200:
                return self.send_body(State.prices_status, "text/plain", b"server error")
            with open(FIXTURE, encoding="utf-8") as f:
                body = f.read().replace("__TODAY__", State.prices_date.isoformat()).encode("utf-8")
            return self.send_body(200, "text/javascript; charset=utf-8", body)
        if path == "/config.js":
            if State.config_delay:
                time.sleep(State.config_delay)
            if State.config is None:
                return self.send_body(404, "text/plain", b"not found")
            return self.send_body(200, "text/javascript", State.config.encode("utf-8"))
        return super().do_GET()

    def send_body(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


class OfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=ROOT))
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel=os.environ.get("FC_BROWSER_CHANNEL") or None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        State.prices_date = datetime.date.today()
        State.config = None
        State.config_delay = 0
        State.prices_status = 200
        State.sw_suffix = ""
        State.down = False
        self.tiles = []
        self.ctx = self.browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
        self.addCleanup(self.ctx.close)
        self.ctx.route(re.compile(r"^https://(tile\.openstreetmap\.org|[^/]*basemaps\.cartocdn\.com)/"), self.tile)
        self.ctx.set_default_timeout(8000)
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tile(self, route):
        if State.down:
            return route.abort()   # tiles fail while offline, like on a real phone
        self.tiles.append(route.request.url)
        route.fulfill(content_type="image/png", headers=CORS, body=PNG)

    def load(self):
        """Open the page and wait until the service worker controls it, then reload so it serves the page."""
        p = self.page
        p.goto(self.base + "/" + PAGE)
        p.wait_for_selector(".leaflet-container")
        p.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller", timeout=8000)
        p.reload()
        p.wait_for_selector(".leaflet-container")
        return p

    def text(self, id_):
        return self.page.inner_text("#" + id_).strip()

    def value(self, id_):
        return self.page.input_value("#" + id_)

    def go_offline(self):
        State.down = True            # the worker's own fetch hits a dead server
        self.ctx.set_offline(True)   # navigator.onLine goes false

    def go_online(self):
        State.down = False
        self.ctx.set_offline(False)

    def reload_offline(self):
        self.go_offline()
        self.page.reload()
        self.page.wait_for_selector("#priceState")

    def test_manifest_is_installable(self):
        p = self.page
        p.goto(self.base + "/" + PAGE)
        href = p.get_attribute('link[rel="manifest"]', "href")
        self.assertTrue(href)
        resp = self.ctx.request.get(urllib.parse.urljoin(self.base + "/" + PAGE, href))
        self.assertEqual(resp.status, 200)
        m = resp.json()
        self.assertEqual(m["name"], "Trip fuel calculator")
        self.assertEqual(m["short_name"], "Fuel")
        self.assertEqual(m["start_url"], "./fuel-calculator.html")
        self.assertEqual(m["scope"], "./")
        self.assertEqual(m["display"], "standalone")
        sizes = set()
        for icon in m["icons"]:
            r = self.ctx.request.get(urllib.parse.urljoin(self.base + "/", icon["src"]))
            self.assertEqual(r.status, 200, icon["src"])
            body = r.body()
            w, h = struct.unpack(">II", body[16:24])
            self.assertEqual("%dx%d" % (w, h), icon["sizes"], icon["src"])
            sizes.add((icon["sizes"], icon.get("purpose", "any")))
        self.assertIn(("192x192", "any"), sizes)
        self.assertIn(("512x512", "any"), sizes)
        self.assertIn(("512x512", "maskable"), sizes)
        apple = p.get_attribute('link[rel="apple-touch-icon"]', "href")
        r = self.ctx.request.get(urllib.parse.urljoin(self.base + "/" + PAGE, apple))
        self.assertEqual(struct.unpack(">II", r.body()[16:24]), (180, 180))
        self.assertTrue(p.get_attribute('meta[name="theme-color"]', "content"))

    def test_offline_keeps_prices_and_date(self):
        old = datetime.date.today() - datetime.timedelta(days=2)
        State.prices_date = old
        self.load()
        price = self.value("price")
        self.assertTrue(price)
        State.prices_date = datetime.date.today()   # the server now has newer prices; offline must not show them
        self.reload_offline()
        self.assertEqual(self.value("price"), price)
        self.assertIn(fmt_date(old), self.text("priceState"))
        self.assertNotIn(fmt_date(State.prices_date), self.text("priceState"))
        self.assertTrue(re.search(r"\d", self.text("rCost")))
        self.assertEqual(self.errors, [])

    def test_offline_saved_trip_opens(self):
        p = self.load()
        p.click("#saveTripBtn")
        p.fill("#tripName", "Home")
        p.click("#saveTrip button[type=submit]")
        km = self.value("distance")
        self.reload_offline()
        p.locator("#tripList li .open").click()
        p.wait_for_function("document.querySelector('#routeMsg').textContent.includes('Check your connection')")
        self.assertEqual(self.value("distance"), km)
        self.assertIn("Could not reach the address or routing service", self.text("routeMsg"))
        p.wait_for_function("document.querySelector('#distHint').textContent.includes('could not be updated')")

    def test_offline_shows_map_note(self):
        p = self.load()
        self.assertTrue(p.is_hidden("#mapNote"))
        self.go_offline()
        p.wait_for_selector("#mapNote", state="visible")
        self.assertEqual(self.text("mapNote"), OFFLINE_NOTE)
        self.go_online()
        p.wait_for_selector("#mapNote", state="hidden")

    def test_map_tiles_reload_when_back_online(self):
        p = self.load()
        p.wait_for_function("document.querySelectorAll('.leaflet-tile-loaded').length > 0")
        p.wait_for_timeout(500)
        self.go_offline()
        p.wait_for_selector("#mapNote", state="visible")
        p.evaluate("map.panBy([300, 0], {animate: false})")   # new tiles are asked for and fail
        p.wait_for_timeout(500)
        self.tiles.clear()
        self.go_online()
        p.wait_for_selector("#mapNote", state="hidden")
        deadline = time.time() + 5
        while not self.tiles and time.time() < deadline:
            p.wait_for_timeout(100)
        self.assertTrue(self.tiles, "no tile was requested again after reconnecting")

    def test_online_gets_new_prices_after_cache(self):
        State.prices_date = datetime.date.today() - datetime.timedelta(days=2)
        self.load()
        self.assertIn(fmt_date(State.prices_date), self.text("priceState"))
        State.prices_date = datetime.date.today()
        self.page.reload()
        self.page.wait_for_selector(".leaflet-container")
        self.assertIn(fmt_date(State.prices_date), self.text("priceState"))

    def test_reload_prices_offline_keeps_prices(self):
        self.load()
        price = self.value("price")
        self.reload_offline()
        with self.page.expect_request(lambda r: "prices.js?t=" in r.url):
            self.page.click("#priceRefresh")
        # The button is disabled while the reload runs; wait for it to be done.
        self.page.wait_for_function("!document.querySelector('#priceRefresh').disabled")
        self.assertEqual(self.value("price"), price)
        self.assertIn(fmt_date(State.prices_date), self.text("priceState"))
        self.assertEqual(self.errors, [])

    def test_config_never_cached(self):
        State.config = 'window.FC_CONFIG = { cartoKey: "%s" };' % FAKE_KEY
        requested = []
        self.page.on("request", lambda r: requested.append(r.url))
        p = self.load()
        self.assertTrue([u for u in requested if u.endswith("/config.js")], "the page never asked for config.js")
        direct = p.goto(self.base + "/config.js")
        self.assertIn(FAKE_KEY, direct.text())   # the visit itself works; it just must not be cached
        found = p.evaluate("""async () => {
            const out = [];
            for (const name of await caches.keys()) {
                const c = await caches.open(name);
                for (const req of await c.keys()) {
                    const body = await (await c.match(req)).clone().text().catch(() => "");
                    out.push([req.url, body]);
                }
            }
            return out;
        }""")
        self.assertTrue(found, "nothing was cached at all")
        for url, body in found:
            self.assertNotIn("config.js", url)
            if "image" not in url and not url.endswith(".png"):
                self.assertNotIn(FAKE_KEY, body, url)

    def test_stalled_config_does_not_freeze_the_page(self):
        State.config = 'window.FC_CONFIG = { cartoKey: "%s" };' % FAKE_KEY
        self.load()
        State.config_delay = 10
        self.page.reload(wait_until="commit")
        self.page.wait_for_function("document.querySelector('#price') && document.querySelector('#price').value !== ''",
                                    timeout=5000)
        self.assertEqual(self.errors, [])

    def test_activation_keeps_other_projects_caches(self):
        p = self.load()
        p.evaluate("""async () => {
            await caches.open("other-project");
            await caches.open("fc-old");
        }""")
        State.sw_suffix = "\n// a new release\n"
        p.evaluate("navigator.serviceWorker.getRegistration().then((r) => r.update())")
        deadline = time.time() + 8
        while "fc-old" in p.evaluate("caches.keys()") and time.time() < deadline:
            p.wait_for_timeout(100)
        keys = p.evaluate("caches.keys()")
        self.assertIn("other-project", keys)
        self.assertIn("fc-v1", keys)
        self.assertNotIn("fc-old", keys)

    def test_server_error_keeps_cached_prices(self):
        old = datetime.date.today() - datetime.timedelta(days=2)
        State.prices_date = old
        self.load()
        price = self.value("price")
        State.prices_status = 503
        self.page.reload()
        self.page.wait_for_selector("#priceState")
        self.assertIn(fmt_date(old), self.text("priceState"))
        self.assertEqual(self.value("price"), price)
        self.assertNotIn("not found", self.text("priceNote"))

    def test_attribution_visible_offline(self):
        self.load()
        self.reload_offline()
        self.assertIn("Lithuanian Energy Agency", self.text("priceNote"))


if __name__ == "__main__":
    unittest.main()

"""Tests for geocode_stations.py. A fake `get` and `sleep` are injected: no network is used."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import geocode_stations as gs  # noqa: E402

TODAY = dt.date(2026, 11, 14)
ADDR = "Garliava, Vytauto g. 111A, 53258"
MUNI = "Kauno r. sav."


def photon(kind, lng=23.87, lat=54.82):
    return {"features": [{"geometry": {"coordinates": [lng, lat]}, "properties": {"type": kind}}]}


def nominatim(district):
    return {"address": {"state_district": district}}


class FakeGet:
    """Maps URL substrings to replies (a dict, or a list consumed in order); records every URL."""

    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        for key, reply in self.routes.items():
            if key in url:
                if isinstance(reply, list):
                    reply = reply.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError("unexpected URL " + url)


def nosleep(s):
    pass


class LookupTests(unittest.TestCase):
    def test_accepts_a_building_in_the_right_municipality(self):
        get = FakeGet({"photon": photon("house"), "nominatim": nominatim("Kauno rajono savivaldybė")})
        self.assertEqual(gs.lookup(ADDR, MUNI, get, nosleep), [54.82, 23.87])

    def test_retries_without_postcode(self):
        get = FakeGet({"photon": [photon("street"), photon("house")],
                       "nominatim": nominatim("Kauno rajono savivaldybė")})
        self.assertEqual(gs.lookup(ADDR, MUNI, get, nosleep), [54.82, 23.87])
        photon_urls = [u for u in get.urls if "photon" in u]
        self.assertEqual(len(photon_urls), 2)
        self.assertIn("53258", photon_urls[0])
        self.assertNotIn("53258", photon_urls[1])

    def test_rejects_non_buildings(self):
        get = FakeGet({"photon": [photon("postcode"), photon("street")]})
        self.assertIsNone(gs.lookup(ADDR, MUNI, get, nosleep))

    def test_rejects_wrong_municipality(self):
        get = FakeGet({"photon": photon("house"), "nominatim": nominatim("Lazdijų rajono savivaldybė")})
        self.assertIsNone(gs.lookup("Šilutė, Lietuvininkų g. 1, 99001", "Šilutės r. sav.", get, nosleep))

    def test_rounds_to_five_decimals(self):
        get = FakeGet({"photon": photon("house", 23.8712349, 54.8214567),
                       "nominatim": nominatim("Kauno rajono savivaldybė")})
        self.assertEqual(gs.lookup(ADDR, MUNI, get, nosleep), [54.82146, 23.87123])

    def test_rate_limits(self):
        sleeps = []
        events = []

        def get(url):
            events.append("photon" if "photon" in url else "nominatim")
            return photon("house") if "photon" in url else nominatim("Kauno rajono savivaldybė")

        def sleep(s):
            events.append(("sleep", s))
            sleeps.append(s)

        gs.lookup(ADDR, MUNI, get, sleep)
        self.assertEqual(events, ["photon", ("sleep", 0.5), "nominatim", ("sleep", 1.1)])


class LeaMunicipalityTests(unittest.TestCase):
    def test_lea_municipality(self):
        for name, expected in [("Kauno rajono savivaldybė", "Kauno r. sav."),
                               ("Vilniaus miesto savivaldybė", "Vilniaus m. sav."),
                               ("Neringos savivaldybė", "Neringos sav."),
                               ("Kazlų Rūdos savivaldybė", "Kazlų Rūdos sav.")]:
            self.assertEqual(gs.lea_municipality(name), expected)


def stations(*addrs):
    return [{"c": "X", "m": MUNI, "a": a} for a in addrs]


GOOD = {"photon": photon("house"), "nominatim": nominatim("Kauno rajono savivaldybė")}


class UpdateCacheTests(unittest.TestCase):
    def test_new_address_is_looked_up_and_cached(self):
        cache = {}
        result = gs.update_cache(stations(ADDR), cache, TODAY, FakeGet(dict(GOOD)), nosleep)
        self.assertEqual(result, {"looked_up": 1, "found": 1, "skipped": 0})
        self.assertEqual(cache[ADDR], {"g": [54.82, 23.87], "checked": "2026-11-14"})

    def test_cache_hit_makes_no_requests(self):
        cache = {ADDR: {"g": [54.1, 23.1], "checked": "2026-01-01"}}
        get = FakeGet({})
        result = gs.update_cache(stations(ADDR), cache, TODAY, get, nosleep)
        self.assertEqual(get.urls, [])
        self.assertEqual(result["looked_up"], 0)

    def test_not_found_retried_after_30_days(self):
        recent = (TODAY - dt.timedelta(days=29)).isoformat()
        old = (TODAY - dt.timedelta(days=31)).isoformat()
        get = FakeGet({})
        gs.update_cache(stations(ADDR), {ADDR: {"g": None, "checked": recent}}, TODAY, get, nosleep)
        self.assertEqual(get.urls, [])
        get = FakeGet(dict(GOOD))
        cache = {ADDR: {"g": None, "checked": old}}
        result = gs.update_cache(stations(ADDR), cache, TODAY, get, nosleep)
        self.assertEqual(result["looked_up"], 1)
        self.assertEqual(cache[ADDR]["g"], [54.82, 23.87])

    def test_limit_caps_lookups(self):
        addrs = ["Town, Street %d, 5325%d" % (i, i) for i in range(5)]
        cache = {}
        result = gs.update_cache(stations(*addrs), cache, TODAY, FakeGet(dict(GOOD)), nosleep, limit=2)
        self.assertEqual(result["looked_up"], 2)
        self.assertEqual(len(cache), 2)

    def test_service_errors_count_as_skipped_not_cached(self):
        cache = {}
        get = FakeGet({"photon": OSError("down")})
        result = gs.update_cache(stations(ADDR), cache, TODAY, get, nosleep)
        self.assertEqual(cache, {})
        self.assertEqual(result, {"looked_up": 0, "found": 0, "skipped": 1})

    def test_duplicate_addresses_are_looked_up_once(self):
        get = FakeGet(dict(GOOD))
        result = gs.update_cache(stations(ADDR, ADDR), {}, TODAY, get, nosleep)
        self.assertEqual(result["looked_up"], 1)


class ApplyAndCacheFileTests(unittest.TestCase):
    def test_apply_positions(self):
        data = [{"a": "A", "g": [1, 2]}, {"a": "B"}, {"a": "C", "g": [9, 9]}, {"a": "D"}]
        cache = {"A": {"g": None, "checked": "2026-11-01"}, "B": {"g": [54.1, 23.2], "checked": "2026-11-01"},
                 "C": {"g": [54.5, 23.5], "checked": "2026-11-01"}}
        gs.apply_positions(data, cache)
        self.assertNotIn("g", data[0])
        self.assertEqual(data[1]["g"], [54.1, 23.2])
        self.assertEqual(data[2]["g"], [54.5, 23.5])
        self.assertNotIn("g", data[3])

    def test_corrupt_cache_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                f.write("not json")
            self.assertEqual(gs.load_cache(path), {})
            self.assertEqual(gs.load_cache(os.path.join(d, "missing.json")), {})

    def test_save_cache_sorted_and_unescaped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            cache = {"Šilutė": {"g": None, "checked": "2026-11-14"}, "Alytus": {"g": [1.0, 2.0], "checked": "2026-11-14"}}
            gs.save_cache(path, cache)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("Šilutė", text)
            self.assertLess(text.index("Alytus"), text.index("Šilutė"))
            self.assertEqual(gs.load_cache(path), cache)
            json.loads(text)


if __name__ == "__main__":
    unittest.main()

"""Turns station addresses into map positions. Used by update_prices.py; Python 3 standard library only.

Photon finds a building for the address; Nominatim then confirms the position lies in the
station's municipality. Positions are cached in station-coords.json so each address is looked up once."""
import datetime
import http.client
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request

USER_AGENT = "Litras price updater (https://github.com/freshpancakes-web/litras)"
PHOTON_URL = "https://photon.komoot.io/api/?q=%s&limit=1&bbox=20.9,53.89,26.84,56.45&lang=default"
NOMINATIM_URL = ("https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=8&accept-language=lt"
                 "&lat=%s&lon=%s")
PHOTON_DELAY = 0.5
NOMINATIM_DELAY = 1.1
RETRY_DAYS = 30
MAX_LOOKUPS = 900
TIME_BUDGET = 20 * 60      # seconds: stop starting new lookups after this, so the price job never nears its timeout
MAX_CONSECUTIVE_ERRORS = 5
SAVE_EVERY = 25
HTTP_TIMEOUT = 10


def http_get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def lea_municipality(name):
    """Nominatim's 'Kauno rajono savivaldybė' -> LEA's 'Kauno r. sav.' (same as the app's leaMunicipality)."""
    name = (name or "").strip()
    if name.endswith(" miesto savivaldybė"):
        return name[:-len(" miesto savivaldybė")] + " m. sav."
    if name.endswith(" rajono savivaldybė"):
        return name[:-len(" rajono savivaldybė")] + " r. sav."
    if name.endswith(" savivaldybė"):
        return name[:-len(" savivaldybė")] + " sav."
    return name


def _photon_building(query, get, sleep):
    url = PHOTON_URL % urllib.parse.quote(query + ", Lithuania")
    try:
        reply = get(url)
    finally:
        sleep(PHOTON_DELAY)
    features = (reply or {}).get("features") or []
    if not features or features[0].get("properties", {}).get("type") != "house":
        return None
    lng, lat = features[0]["geometry"]["coordinates"][:2]
    return lat, lng


def lookup(address, municipality, get, sleep=time.sleep):
    """Returns [lat, lng] rounded to 5 decimals, or None when no building is found in the right municipality."""
    queries = [address]
    without_postcode = re.sub(r",?\s*\b\d{5}\b", "", address).strip(" ,")
    if without_postcode != address and without_postcode:
        queries.append(without_postcode)
    for query in queries:
        found = _photon_building(query, get, sleep)
        if found is None:
            continue
        lat, lng = found
        try:
            reply = get(NOMINATIM_URL % (lat, lng))
        finally:
            sleep(NOMINATIM_DELAY)
        district = ((reply or {}).get("address") or {}).get("state_district")
        if district and lea_municipality(district) == municipality:
            return [round(lat, 5), round(lng, 5)]
        return None
    return None


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


def save_cache(path, cache):
    """Writes through a temp file in the same folder, then swaps it in, so a failure keeps the old file."""
    fd, tmp = tempfile.mkstemp(prefix=".coords-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, sort_keys=True, indent=0)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _needs_lookup(entry, today):
    if not isinstance(entry, dict) or "checked" not in entry:
        return True
    if entry.get("g"):
        return False
    try:
        checked = datetime.date.fromisoformat(entry["checked"])
    except (TypeError, ValueError):
        return True
    return (today - checked).days > RETRY_DAYS


def update_cache(stations, cache, today, get, sleep=time.sleep, limit=MAX_LOOKUPS,
                 clock=time.monotonic, save=None, budget=TIME_BUDGET):
    """Looks up positions for new addresses. Stops early (stats["stopped"]) after `budget` seconds ("time")
    or MAX_CONSECUTIVE_ERRORS service errors in a row ("errors"). `save()` runs every SAVE_EVERY lookups and
    once at the end, even when something unexpected escapes."""
    looked_up = found = skipped = attempts = errors_in_a_row = 0
    stopped = None
    started = clock()
    seen = set()
    try:
        for s in stations:
            address = s["a"]
            if address in seen:
                continue
            seen.add(address)
            if not _needs_lookup(cache.get(address), today):
                continue
            if attempts >= limit:
                break
            if clock() - started >= budget:
                stopped = "time"
                break
            attempts += 1
            try:
                position = lookup(address, s["m"], get, sleep)
            except (OSError, http.client.HTTPException, ValueError, KeyError, IndexError, TypeError):
                skipped += 1
                errors_in_a_row += 1
            else:
                errors_in_a_row = 0
                looked_up += 1
                if position:
                    found += 1
                cache[address] = {"g": position, "checked": today.isoformat()}
            if errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                stopped = "errors"
                break
            if save and attempts % SAVE_EVERY == 0:
                save()
    finally:
        if save:
            save()
    return {"looked_up": looked_up, "found": found, "skipped": skipped, "stopped": stopped}


def apply_positions(stations, cache):
    for s in stations:
        entry = cache.get(s["a"])
        if isinstance(entry, dict) and entry.get("g"):
            s["g"] = entry["g"]
        else:
            s.pop("g", None)

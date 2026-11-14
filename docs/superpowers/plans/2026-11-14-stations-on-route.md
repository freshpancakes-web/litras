# Stations on Your Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a route is calculated, show the stations along it as price pins, as a sortable list and as one recommended stop that can be added to the route.

**Architecture:**
- **Positions on GitHub:** station positions are looked up when prices are built, by a new standard-library module `geocode_stations.py`. They're cached in `station-coords.json` and written into `prices.js` as `g: [lat, lng]`.
- **Pure logic in its own file:** the route maths (distance to the route, which stations are near it, the recommendation, where to insert a stop) goes in `route-stations.js`. It's a plain script exposing `window.RouteStations`, so it can be tested on its own.
- **Interface in the page:** `fuel-calculator.html` gets the list, the recommendation and the Leaflet pins.

**Tech Stack:** Python 3 standard library, plain JavaScript, Leaflet 1.9.4, Python Playwright tests, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-14-stations-on-route-design.md` (approved with its defaults: full tank, 2 km, 0.50 EUR).

## Global Constraints

- No build step and no server. Works from `file://`. Data loads through `<script>`, never `fetch`.
- Leaflet 1.9.4 only, with no new libraries.
- The browser sends no new data anywhere. Geocoding runs only in `update_prices.py`.
- `update_prices.py` and `geocode_stations.py` use the Python 3 standard library only.
- Rate limits: Photon one request per 0.5 s; Nominatim one request per 1.1 s, `User-Agent: Litras price updater (https://github.com/freshpancakes-web/litras)`; at most 900 lookups per run.
- Photon search: `https://photon.komoot.io/api/?q=<address>, Lithuania&limit=1&bbox=20.9,53.89,26.84,56.45&lang=default`. Accept only `properties.type == "house"`.
- Nominatim check: `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=8&accept-language=lt&lat=..&lon=..`. Convert `address.state_district` exactly as the app's `leaMunicipality`.
- Positions are rounded to 5 decimals. Not-found addresses are retried after 30 days.
- Off-route choices are 1, 2 and 5 km, default 2, in `fc.detourKm`. Sort is `price` or `along`, default `price`, in `fc.stationSort`.
- The fill is the car's tank size. The minimum saving to recommend is 0.50 EUR. Detour cost is `2 * offKm * mixed consumption / 100 * price`.
- Pins are shaded in three steps of the accent blue (darkest = cheapest third), never red or green. Below Leaflet zoom 10 they're dots, except the recommended stop.
- The list shows 10 rows, then "Show all N".
- `{town}` in copy is the text before the first comma of the station's LEA address (LEA writes the town or village first, as in `Garliava, Vytauto g. 111A, 53253`).
- Copy (exact):
  - Recommendation: `Cheapest stop on your way: {network}, {town}. {price} EUR/l, about {off} km off route. A {fill} L fill saves about {saving} EUR against the average on your route.`
  - No recommendation: `Prices on your route are within a few cents of each other, so any station will do.`
  - Empty state: `No stations with a known position within {km} km of this route.` plus a button `Try 5 km`, only when km < 5.
  - Coverage note: `Positions are looked up from addresses, so a few stations can't be shown.`
  - Stop limit: `A trip can have up to 8 stops.`
  - No positions in the data: `Station positions aren't available yet.`
- Existing IDs, behaviour and storage keys are unchanged. Light and dark mode, 360 px and the keyboard must all work.
- The service worker's `CACHE_NAME` becomes `fc-v3`, and `route-stations.js` joins its shell.
- **Ruling (spec gap):** the workflow keeps a rebuilt `prices.js` when its date is later, **or** when the date is equal and `station-coords.json` changed. Otherwise the same-day hand run the spec promises would discard the positions.

## Review Focus

1. **Recalculating after Add as stop:** the old pins, list and recommendation must be replaced, never added on top. Test: `test_recalculating_replaces_pins` (Task 5).
2. **Typing a distance by hand after a route:** the section hides, because there's no route to measure against. Test: `test_manual_distance_hides_section` (Task 4).
3. **A long route with hundreds of stations:** the page stays responsive. Test: `test_many_stations_render_quickly` (Task 4): 500 stations render in under 300 ms.
4. **Equal prices:** stable order (price, then along the route), and the recommendation doesn't flip between reloads. Test: `test_corridor_ties_are_stable` (Task 3).
5. **A corrupted `station-coords.json`:** treated as empty, without crashing the price job. Test: `test_corrupt_cache_is_empty` (Task 1).

---

### Task 1: Geocoding module

**Files:**
- Create: `geocode_stations.py`
- Test: `tests/test_geocode_stations.py`

**Interfaces:**
- Produces:
  - `lea_municipality(name: str) -> str`
  - `lookup(address: str, municipality: str, get: Callable[[str], dict], sleep=time.sleep) -> list[float] | None`. Returns `[lat, lng]` rounded to 5 decimals, or `None`.
  - `load_cache(path: str) -> dict`
  - `save_cache(path: str, cache: dict) -> None`, writing sorted keys with `ensure_ascii=False`.
  - `update_cache(stations: list[dict], cache: dict, today: datetime.date, get, sleep=time.sleep, limit=900) -> dict`. Returns `{"looked_up": n, "found": n, "skipped": n}`.
  - `apply_positions(stations: list[dict], cache: dict) -> None`. Sets `s["g"]` from the cache by `s["a"]`, and removes `g` when the cache has none.
  - `http_get(url: str) -> dict`, the real one, using the User-Agent from Global Constraints.
- The cache entry format is `{"g": [lat, lng] | None, "checked": "YYYY-MM-DD"}`.

- [ ] **Step 1: Write the failing tests**

All tests use a fake `get` mapping URL substrings to replies, and `sleep=lambda s: None`.
- `test_accepts_a_building_in_the_right_municipality`: Photon `type: house` at `[23.87, 54.82]`, Nominatim `Kauno rajono savivaldybė`, station municipality `Kauno r. sav.` → `[54.82, 23.87]`
- `test_retries_without_postcode`: the first query `... 53258, Lithuania` gives `type: street`; the second, without `53258`, gives `house` → a position. Assert the second URL has no `53258`.
- `test_rejects_non_buildings`: a postcode or street on both tries → `None`
- `test_rejects_wrong_municipality`: Nominatim `Lazdijų rajono savivaldybė` for a `Šilutės r. sav.` station → `None`
- `test_rounds_to_five_decimals`: `54.8214567` → `54.82146`
- `test_cache_hit_makes_no_requests` and `test_not_found_retried_after_30_days`: checked 29 days ago → skipped; 31 days ago → looked up
- `test_limit_caps_lookups`: `limit=2` with 5 new addresses → `looked_up == 2`
- `test_service_errors_count_as_skipped_not_cached`: `get` raises `OSError` → the cache is unchanged, no exception
- `test_apply_positions` (sets and removes `g`), `test_lea_municipality` (the same four pairs as the app's test)
- `test_corrupt_cache_is_empty`: a file containing `not json` → `{}`
- `test_rate_limits`: Photon calls followed by `sleep(0.5)`, Nominatim calls by `sleep(1.1)`

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_geocode_stations -v`
Expected: FAIL (the module doesn't exist).

- [ ] **Step 3: Implement `geocode_stations.py` with the interfaces above**

- [ ] **Step 4: Run them to verify they pass**

Run the same command. Expected: OK.

- [ ] **Step 5: Commit**

Commit with message `feat: geocode station addresses for map positions`.

### Task 2: Positions in `prices.js` and the workflow

**Files:**
- Modify: `update_prices.py` (`main`, at about line 301)
- Create: `station-coords.json` (`{}`)
- Modify: `.github/workflows/update-prices.yml`, `README.md`
- Test: `tests/test_update_prices.py`

**Interfaces:**
- Consumes: Task 1's `load_cache`, `update_cache`, `save_cache`, `apply_positions`, `http_get`.
- Produces:
  - Stations in `prices.js` may carry `g: [lat, lng]`.
  - The `--no-geocode` flag, which can be combined with the existing positional arguments.
  - `COORDS_FILE = os.path.join(HERE, "station-coords.json")`.

- [ ] **Step 1: Write the failing tests**

- `test_main_applies_cached_positions_without_lookups`:
  - A temp folder with a `station-coords.json` holding one address. Patch `update_prices.parse` to return rows for two stations, so no xlsx is needed.
  - Run `main(["update_prices.py", xlsx, out, "--no-geocode"])`.
  - Assert that station has `g`, the others don't, and `http_get` was never called (patch it to raise).
- `test_main_geocodes_and_saves_cache`: patch `geocode_stations.http_get` with the fake → the cache file has the new entry.
- `test_workflow_commits_coords`:
  - `update-prices.yml` contains `git add prices.js station-coords.json` and `timeout-minutes: 45`.
  - The keep condition allows an equal date when `station-coords.json` changed (assert the text `git diff --quiet -- station-coords.json`).

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_update_prices -v`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

- `main(argv=None)` reads `argv or sys.argv` and removes `--no-geocode` before the positional parsing. Keep `--check-fresh` working.
- After `build`:
  - Unless `--no-geocode`: load the cache, `update_cache`, save it, and log the stats line `Positions: {found} found, {looked_up} looked up, {skipped} skipped.`
  - Always: `apply_positions`.
- Workflow:
  - Add `timeout-minutes: 45` to the job.
  - Keep `prices.js` when the date is later, or the dates are equal and `git diff --quiet -- station-coords.json` fails. Otherwise run `git checkout -- prices.js station-coords.json`.
  - Commit both files.
- README: add a row for `station-coords.json` and a line about positions in "How prices stay fresh".

- [ ] **Step 4: Run all Python tests**

Run: `.venv/bin/python -m unittest tests.test_update_prices tests.test_geocode_stations tests.test_update_from_github -v`. Expected: OK.

- [ ] **Step 5: Commit**

Commit with message `feat: add station positions to prices.js`.

### Task 3: Route maths (`route-stations.js`)

**Files:**
- Create: `route-stations.js`
- Modify: `fuel-calculator.html`: add `<script src="route-stations.js"></script>` before the main script.
- Test: `tests/test_route_stations.py`, which loads the page and calls the functions through `page.evaluate`.

**Interfaces:**
- Produces `window.RouteStations` with:
  - `project(route: [lat,lng][], point: [lat,lng]) -> {offKm, alongKm}`. Uses a flat-earth approximation: x = lng × cos(mean route lat) × 111.32, y = lat × 110.57, with the nearest point on any segment.
  - `corridor(stations, route, {field, network, maxOffKm}) -> item[]`, where `item = {station, price, offKm, alongKm}`. Keeps only stations with `g`, a non-null `station[field]`, and the network filter if set. Sorted by price, then `alongKm`, then address.
  - `sortItems(items, "price"|"along") -> item[]`, a new array.
  - `recommend(items, {fillL, consPer100}) -> {item, saving, reference} | null`. Uses the spec's formula and 0.50 EUR minimum. Ties go to the lower `alongKm`.
  - `insertIndex(alongKm, stopAlongKms: number[]) -> number`, the count of stops before the station.
  - `shade(price, min, max) -> 0|1|2`, where 0 is the cheapest third. All 0 when `min == max`.

- [ ] **Step 1: Write the failing tests**

The route runs along latitude 54.9 from longitude 23.9 to 25.3, where 1° of longitude ≈ 64.0 km.
- `test_project_on_and_off_the_line`: a point 10 km along and 0.5 km north → `alongKm` ≈ 10 ± 0.1, `offKm` ≈ 0.5 ± 0.02. A point past the end → `alongKm` equals the route length.
- `test_corridor_filters_distance_fuel_network`: stations at 0.5, 3 and 0.2 km off; 2 km → 2 stations, 5 km → 3. A station with `p: null` or without `g` is excluded, and `network` limits by `c`.
- `test_corridor_ties_are_stable`: two equal prices → the lower `alongKm` first, the same on repeated calls.
- `test_recommend_numbers`: stations A at 10 km, 0.5 km off, 1.800 and C at 60 km, 0.2 km off, 1.900; fill 50, consumption 7.0 → A, reference 1.85, saving 2.374 ± 0.001.
- `test_recommend_none_below_50_cents`: prices 1.800 and 1.805 → `null`.
- `test_insert_index`: `insertIndex(35, [10, 50]) == 1`, `insertIndex(5, []) == 0`.
- `test_shade_thirds`.
- `test_sort_along`.

- [ ] **Step 2: Run them to verify they fail**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_route_stations -v`. Expected: FAIL.

- [ ] **Step 3: Implement `route-stations.js`**

A plain script with no globals other than `RouteStations`.

- [ ] **Step 4: Run them to verify they pass**

Expected: OK.

- [ ] **Step 5: Commit**

Commit with message `feat: add route maths for stations along a route`.

### Task 4: List and recommended stop

**Files:**
- Modify: `fuel-calculator.html`: markup in the results column between the results card and `.mapbox`; styles; logic.
- Modify: `tests/test_app.py`: `open()` gains `stations=None`, which replaces the fixture's `stations` array (parse the fixture JSON, then replace it).

**Interfaces:**
- Consumes: Task 3's `RouteStations`; `routeCoords` (below).
- Produces:
  - `let routeCoords = null;`, an array of `[lat, lng]`. Set in `calculateRoute` after success. Cleared on a route error, on manual distance input and in `loadTrip` before recalculating.
  - `renderRouteStations()`, called at the end of `applyPriceToInput`, after a route succeeds, and when `routeCoords` is cleared.
  - `addStationStop(item)`.
  - `addStopAt(index: number, place: {lat,lng,label}) -> stop`.
- IDs:
  - `#routeStations` (the section, `hidden` when there's no route), `#rsSummary`.
  - Radio groups `name="detourKm"` (`1`, `2`, `5`) and `name="stationSort"` (`price`, `along`).
  - `#rsRecommend` (with `#rsRecText` and button `#rsAddRec`), list `#rsList` (rows are `<button class="rs-row" data-i>`), `#rsShowAll`.
  - `#rsEmpty` (with `#rsWiden`), `#rsNote`, `#rsMsg` (stop-limit message).
- Row text: `{price}`, `{network}`, `{address}`, `at {along} km, about {off} km off route`. Along is rounded to whole km, off to 1 decimal.
- `addStationStop` uses the label `{network}, {address}`. It inserts at `insertIndex` using each existing stop's projected `alongKm`, then calls `calculateRoute()`.

- [ ] **Step 1: Write the failing tests**

These use the Task 3 test route as the mocked OSRM geometry, and `stations=` with A, B (40 km, 3 km off, 1.700) and C. Fill From and To, then click `#routeBtn`.
- `test_hidden_without_route`.
- `test_list_shows_stations_within_2_km`: 2 rows; the first has `1.800` and `at 10 km, about 0.5 km off route`.
- `test_detour_5_km_adds_station`.
- `test_sort_along_the_route`.
- `test_recommendation_text`: exactly `Cheapest stop on your way: Test Oil, Kaunas. 1.800 EUR/l, about 0.5 km off route. A 50 L fill saves about 2.37 EUR against the average on your route.` Adjust the station fields so that town is `Kaunas`.
- `test_no_recommendation_text`.
- `test_add_as_stop_inserts_and_recalculates`: `#stop1In` value starts with `Test Oil`, and the OSRM URL contains A's coordinates.
- `test_stop_limit_message`: with 8 stops, `#rsMsg` reads `A trip can have up to 8 stops.`, and there's still exactly 8 stops.
- `test_empty_state_and_widen`: an LPG car with no LPG stations nearby → `#rsEmpty` visible; `#rsWiden` sets 5 km.
- `test_show_all_after_10`: 14 stations → 10 rows, then 14.
- `test_manual_distance_hides_section`.
- `test_no_positions_message`: stations without `g` → `Station positions aren't available yet.`
- `test_many_stations_render_quickly`: 500 stations → `renderRouteStations()` takes under 300 ms (`performance.now()`).
- `test_choices_are_remembered`.
- `test_section_fits_a_phone`: no sideways scroll at 360 px, in light and dark mode.

- [ ] **Step 2: Run them to verify they fail**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_app -k rs_ -k station -k recommend -k detour -v`. Expected: FAIL.

- [ ] **Step 3: Implement**

- Section markup and styles follow the existing `.legs` and `.stlist` patterns.
- The "Show all" state resets on every render.

- [ ] **Step 4: Run the full suite**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests`. Expected: OK.

- [ ] **Step 5: Commit**

Commit with message `feat: list stations along the route with a recommended stop`.

### Task 5: Price pins on the map

**Files:**
- Modify: `fuel-calculator.html`, `tests/test_app.py`

**Interfaces:**
- Consumes: Task 4's items from `renderRouteStations` and `RouteStations.shade`.
- Produces:
  - `let stationLayer`, an `L.layerGroup`, cleared on every render.
  - Markers use `L.divIcon` with class `st-pin st-shade-{0|1|2}`, plus ` st-rec` for the recommended stop, and HTML set to the price with 3 decimals.
  - The map container gets class `st-zoomed-out` when `map.getZoom() < 10`. CSS turns pins into dots then, except `.st-rec`.
  - Popup: network, address, `{price} EUR/l on {date}`, and a button `.st-add` calling `addStationStop`.
  - Clicking a row: `map.panTo`, then `openPopup`, and class `active` on the row and the pin. Clicking a pin: `active` on the row, which is scrolled into view.

- [ ] **Step 1: Write the failing tests**

- `test_pins_match_list`: the `.st-pin` count equals the item count; the labels are the prices.
- `test_cheapest_pin_is_darkest`: the cheapest pin has `st-shade-0`.
- `test_recommended_pin_marked`: exactly one `.st-rec`.
- `test_dots_when_zoomed_out`: `map.setZoom(8)` → the container has `st-zoomed-out`.
- `test_row_and_pin_highlight_each_other`.
- `test_popup_add_as_stop`.
- `test_recalculating_replaces_pins`: calculate, add the recommended stop, recalculate → the pin count equals the new item count, with no duplicates.
- `test_no_pins_without_route`.

- [ ] **Step 2: Run them to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement**

- Shades use the accent with stepped opacity backgrounds and `--accent-ink` text, readable in both themes.

- [ ] **Step 4: Run the full suite**

Expected: OK. Also take screenshots of a real Vilnius → Kaunas route, light and dark, at 1280 and 360 px, and look at them.

- [ ] **Step 5: Commit**

Commit with message `feat: show station price pins along the route`.

### Task 6: Offline cache and release notes

**Files:**
- Modify: `sw.js` (`CACHE_NAME = "fc-v3"`, add `./route-stations.js` to `SHELL`), `tests/test_offline.py` (`fc-v3`), `README.md` ("What it does" line), `fuel-calculator.html` footer: add `Station positions looked up from addresses with Photon and Nominatim.`

- [ ] **Step 1: Update the tests**

`test_offline` expects `fc-v3`, and a new `test_route_stations_js_cached` checks it's in the cache.

- [ ] **Step 2: Run them to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement** the changes listed above.

- [ ] **Step 4: Run the full suite**

Expected: OK.

- [ ] **Step 5: Commit**

Commit with message `chore: cache route-stations.js offline and credit position lookups`.

## After the tasks (the controller asks the user first)

1. Whole-branch review, then a pull request with the tests on GitHub, then a merge on the user's OK.
2. On the user's OK, trigger "Update fuel prices" by hand. It's the first geocoding run, taking about 20 minutes. Then check:
   - the log line `Positions: N found`, expecting about 680 of 756
   - that `station-coords.json` and `prices.js` were committed
   - the live page with a real route
3. Bring the Mac to `main`.

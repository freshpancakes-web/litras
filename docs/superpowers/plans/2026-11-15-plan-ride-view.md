# Plan ride view Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the app into two views, Trip cost and Plan ride, switched from the header, with the stations-on-your-route feature shown only in Plan ride.

**Architecture:**
- One page (`fuel-calculator.html`) with `document.documentElement.dataset.view` set to `"cost"` or `"plan"` from `location.hash`.
- CSS hides `.plan-only` elements in the cost view and `.cost-only` elements in the plan view.
- The station pin layer is removed from or added to the map on each switch.
- Route, stops, car and map state are shared and never recalculated by a switch.

**Tech Stack:** Plain HTML/CSS/JS, Leaflet 1.9.4, Python Playwright tests.

**Spec:** `docs/superpowers/specs/2026-11-15-plan-ride-view-design.md`

## Global Constraints

- No build step, no server, and it works from `file://`. Data loads through `<script>`, not `fetch`.
- Trip cost is `#` (no hash) and Plan ride is `#plan`. Any other hash shows Trip cost. There's no new storage key.
- Header switch labels, exactly: "Trip cost" and "Plan ride". The current one has `aria-current="page"`.
- Empty Plan ride copy, exactly: "Enter From and To and press Calculate route to see the stations on your way."
- Existing IDs, `localStorage` keys, corridor/recommendation/pin behaviour and `route-stations.js` are unchanged.
- Light and dark mode, 360 px phones with no sideways scroll, keyboard and screen readers.
- Tests run with `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The map after a switch:** the side column changes height and contents, so Leaflet must be told (`map.invalidateSize()`). Otherwise tiles stay grey or misplaced. A test checks that `map.getSize()` matches `#map`'s client size after switching (Task 1).
2. **An open pin popup when switching to Trip cost:** it must close, and no `.leaflet-popup` stays visible (Task 1).
3. **Unknown hashes such as `#foo` or `#Plan`:** they show Trip cost and nothing breaks (Task 1).
4. **"Add as stop" in Plan ride, then switching to Trip cost:** the stop and the recalculated cost are there (Task 1).
5. **The two network selects:** changing either one changes the other, the saved `fc.priceNet`, the fuel price and the station list (Task 2).

---

### Task 1: View switch and gating the stations feature

**Files:**
- Modify: `fuel-calculator.html`: header markup and CSS, the `#routeStations` section, `initMap` and the pin drawing code (around lines 999–1030 and 1513–1545), plus a new `setView` near the other init code.
- Modify: `tests/test_app.py`
- Modify: `README.md`, the "What it does" bullet about stations.

**Interfaces:**
- Produces:
  - `currentView(): "cost" | "plan"`, returning `"plan"` only when `location.hash === "#plan"`.
  - `applyView(): void`, which:
    - sets `document.documentElement.dataset.view`;
    - sets `aria-current="page"` on the matching link and removes it from the other;
    - adds or removes `stationLayer` (adds it only when the view is `"plan"`), closing any open popup on leaving Plan ride;
    - calls `map.invalidateSize()` when the map exists.

  It runs at start-up after `initMap`, and on `hashchange`.
- Produces: classes `.plan-only` (shown only in the plan view) and `.cost-only` (shown only in the cost view). `#routeStations` gets `plan-only`.
- Produces: the header nav `<nav class="views" aria-label="View">` with `<a id="viewCost" href="#">Trip cost</a>` and `<a id="viewPlan" href="#plan">Plan ride</a>`.
  - Styled like the existing `.seg` control.
  - On narrow screens it wraps to its own row under the brand, so there's no overflow at 360 px.
- Test helper: `open(..., view=None)` goes to `PAGE + "#plan"` when `view == "plan"`. `route_with(...)` passes `view` through, defaulting to `"plan"`.

- [ ] **Step 1: Write the failing tests.**
  - Point every existing stations-on-route test (the `stations_trio`/`route_with` class, about lines 1010–1316) at the plan view by giving `route_with` and their `open` calls `view="plan"`.
  - Add these tests to that class:

```python
def test_cost_view_has_no_stations_or_pins(self):
    page = self.route_with(list(self.stations_trio()), view=None)
    self.assertTrue(page.locator("#routeStations").is_hidden())
    self.assertEqual(page.locator(".st-pin").count(), 0)
    self.assertEqual(page.get_attribute("#viewCost", "aria-current"), "page")

def test_switching_to_plan_shows_pins_without_recalculating(self):
    page = self.route_with(list(self.stations_trio()), view=None)
    page.click("#viewPlan")
    page.wait_for_selector(".st-pin")
    self.assertEqual(page.locator(".st-pin").count(), 2)
    self.assertTrue(page.locator("#routeStations").is_visible())
    self.assertEqual(len(self.osrm_requests), 1)
    self.assertEqual(page.get_attribute("#viewPlan", "aria-current"), "page")

def test_add_as_stop_then_back_to_trip_cost(self):
    page = self.route_with(list(self.stations_trio()))
    page.click("#rsAddRec")
    page.wait_for_function("document.getElementById('routeBtn').disabled === false")
    page.click("#viewCost")
    self.assertEqual(page.locator("#stops .stoprow").count(), 1)
    self.assertTrue(page.locator("#results").is_visible())
    self.assertEqual(page.locator(".st-pin").count(), 0)

def test_back_button_returns_to_trip_cost(self):
    page = self.route_with(list(self.stations_trio()), view=None)
    page.click("#viewPlan")
    page.wait_for_selector(".st-pin")
    page.go_back()
    page.wait_for_function("document.documentElement.dataset.view === 'cost'")
    self.assertEqual(page.locator(".st-pin").count(), 0)

def test_open_popup_closes_when_leaving_plan(self):
    page = self.route_with(list(self.stations_trio()))
    page.click("#rsList .rs-row >> nth=0")
    page.wait_for_selector(".leaflet-popup")
    page.click("#viewCost")
    self.assertEqual(page.locator(".leaflet-popup").count(), 0)

def test_map_resizes_after_switch(self):
    page = self.route_with(list(self.stations_trio()), view=None)
    page.click("#viewPlan")
    page.wait_for_timeout(100)
    size = page.evaluate("[map.getSize().x, map.getSize().y, document.getElementById('map').clientWidth, document.getElementById('map').clientHeight]")
    self.assertEqual(size[0], size[2]); self.assertEqual(size[1], size[3])

def test_unknown_hash_shows_trip_cost(self):
    page = self.open(stations=list(self.stations_trio()))
    page.evaluate("location.hash = '#Plan'")
    page.wait_for_timeout(50)
    self.assertEqual(page.evaluate("document.documentElement.dataset.view"), "cost")
```

- [ ] **Step 2: Run the tests.**
  - Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_app -k station -k view -k hash -k pin`
  - Expected: the new tests FAIL, because there's no `#viewPlan` yet.

- [ ] **Step 3: Implement the header nav, `.plan-only`/`.cost-only` CSS, `currentView`, `applyView` and the `hashchange` listener.**
  - Put the `stationLayer` add/remove only in `applyView`, not in `drawStationPins`. `drawStationPins` keeps filling the layer group whether or not it's on the map.
  - Change the README stations bullet to start with "In Plan ride, …", and add one bullet: "Two views, Trip cost and Plan ride, switched from the header (`#plan`)".

- [ ] **Step 4: Run the whole suite.**
  - Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests`
  - Expected: all pass, including the phone no-sideways-scroll tests at 360 px.

- [ ] **Step 5: Commit.**

```bash
git add fuel-calculator.html tests/test_app.py README.md
git commit -m "feat: Trip cost and Plan ride views; stations only in Plan ride"
```

### Task 2: Plan ride layout, empty prompt and shared network select

**Files:**
- Modify: `fuel-calculator.html`: Trip section markup, `#results`, the Fuel price and Measure consumption sections, `#routeStations`, `renderRouteStations`/`drawRouteStationRows` (about lines 1403–1440), and `loadLea` (about line 699) with the `priceNetwork` change handler (about line 1600).
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `.cost-only`, `.plan-only`, `applyView` and the `open(view=…)`/`route_with` helpers from Task 1.
- Produces:
  - `cost-only` on:
    - the `#results` section;
    - the Fuel price section;
    - the Measure consumption section;
    - these parts of Trip: the `.row2` holding `#distance`/`#duration`, `#distHint`, `#legs`, `#cycleLabel` and its `.seg`, `.tripopts`, the actions div holding `#saveTripBtn`, `#saveTrip`, and the Routing options `<details>`.
  - Everything else in Trip (saved trips, From, stops, To, Add a stop, Calculate route with `#routeMsg`) and the Car section stay in both views.
  - Note: `#legs` keeps its own `hidden` handling. `cost-only` only adds the plan-view hide.
- Produces: `<div class="hint" id="rsPrompt">` inside `#routeStations`, holding the exact empty copy.
  - When there's no route (`!routeCoords`), `renderRouteStations` no longer sets `sec.hidden = true`. The section stays shown, so the view CSS decides.
  - In that state `#rsPrompt` shows, and the summary, options (`.rs-opts`), recommendation, list, Show all, empty state and note are all hidden.
  - With a route, `#rsPrompt` is hidden.
  - When `lea` is missing, keep today's behaviour (section hidden).
- Produces: `<select id="rsNetwork">` labelled "Station network", in `#routeStations` next to the Off route and Sort by controls.
  - `loadLea` copies `#priceNetwork`'s options into it and gives it the same value.
  - Changing `#rsNetwork` sets `#priceNetwork` to the same value and dispatches a `change` event on it.
  - The `#priceNetwork` change handler also sets `#rsNetwork.value`.
  - It's shown only when there's a route, like the other options.

- [ ] **Step 1: Write the failing tests.**
  - Update the existing tests that asserted `#routeStations` is hidden in the plan view (`test_hidden_without_route`, `test_removing_a_stop_hides_the_stations_section`, `test_manual_distance_hides_section`, `test_route_error_hides_section`, `test_no_pins_without_route`). They should now assert `#rsPrompt` is visible, there are 0 `#rsList .rs-row`, and there are 0 `.st-pin`.
  - `test_manual_distance_hides_section` types the distance in the cost view, then clicks `#viewPlan`.
  - Add:

```python
PROMPT = "Enter From and To and press Calculate route to see the stations on your way."

def test_plan_without_route_shows_prompt(self):
    page = self.open(stations=list(self.stations_trio()), view="plan")
    self.assertEqual(self.text("rsPrompt"), self.PROMPT)
    self.assertTrue(page.locator("#rsList").is_hidden() or page.locator("#rsList .rs-row").count() == 0)
    self.assertTrue(page.locator(".rs-opts").is_hidden())

def test_plan_view_hides_cost_parts(self):
    page = self.route_with(list(self.stations_trio()))
    for sel in ["#results", "#distance", "#saveTripBtn", "#price", "#mKm", 'input[name="cycle"] >> nth=0', "#perWeek"]:
        self.assertTrue(page.locator(sel).is_hidden(), sel)
    for sel in ["#origin", "#dest", "#routeBtn", "#carSelect", "#addStop"]:
        self.assertTrue(page.locator(sel).is_visible(), sel)

def test_network_selects_stay_in_sync(self):
    page = self.route_with(list(self.stations_trio()))
    page.select_option("#rsNetwork", "Viada")
    self.assertEqual(self.value("priceNetwork"), "Viada")
    self.assertEqual(page.evaluate("localStorage.getItem('fc.priceNet')"), "Viada")
    self.assertTrue(all("Viada" in t for t in page.locator("#rsList .rs-row").all_inner_texts()))
    page.click("#viewCost")
    page.select_option("#priceNetwork", "")
    page.click("#viewPlan")
    self.assertEqual(self.value("rsNetwork"), "")
```

  - Check how `fc.priceNet` is stored (raw string or JSON) and assert to match.
  - Also add a plan-view case to the existing 360 px no-sideways-scroll test, and a dark-mode plan-view run (`theme="dark"`) checking `#rsPrompt` is visible.

- [ ] **Step 2: Run the tests.**
  - Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_app`
  - Expected: the new and changed tests FAIL.

- [ ] **Step 3: Implement the classes, `#rsPrompt` and `#rsNetwork` as specified in Interfaces.**

- [ ] **Step 4: Run the whole suite.**
  - Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests`
  - Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add fuel-calculator.html tests/test_app.py
git commit -m "feat: Plan ride layout with route prompt and shared network select"
```

# Car section upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Auto driving type worked out from route speeds, and a compact car card with edit and delete.

**Architecture:**
- **New script `drive-split.js`:** pure speed classing (`window.DriveSplit`), loaded like `route-stations.js`.
- **Routing:** `fetchRoute` asks for per-stretch speeds and stores a split on each leg (`leg.split = {city, mixed, highway}`, in metres).
- **Calculation:** all fuel maths go through one helper, `litresFor(km, split)`.
- **Car card:** a summary line plus a single `<form id="carForm">`, used both to edit and to add a car.

**Tech Stack:** Plain HTML/CSS/JS, Leaflet 1.9.4, Python Playwright tests.

**Spec:** `docs/superpowers/specs/2026-11-15-car-section-upgrade-design.md`

## Global Constraints

- No build step, and it works from `file://`. Storage access stays wrapped in try/catch through `store`.
- Speed bands, exactly:
  - city is below 60 km/h;
  - mixed is 60 to 85 km/h, both limits included;
  - highway is above 85 km/h.
- Copy, exactly:
  - "Auto: N km highway, N km mixed, N km city" (km rounded to whole numbers, and parts with 0 km left out);
  - "Auto: no route yet, using Mixed";
  - the delete confirmation "Delete {name}? This can't be undone.";
  - the summary line "{Fuel} · {tank} l tank · {city} / {mixed} / {highway} l/100 km (city / mixed / highway)".
- The keys `fc.cars`, `fc.carId` and `fc.trips` keep their shape. A trip's `cycle` may now also be `"auto"`.
- `sw.js`: add `./drive-split.js` to `SHELL` and bump `CACHE_NAME` to `fc-v4`.
- Tests run with `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A route with no speed details**, such as test mocks or an OSRM reply without `annotation`: each leg is classed by its own average speed (Task 1).
2. **A saved trip from before this change**, with `cycle: "mixed"` and legs without `split`: it's priced exactly as before (Task 2).
3. **Round trip with Auto:** the split doubles along with the km (Task 2).
4. **Deleting the selected car:** the first remaining car is selected, and the price label and fuel follow it (Task 3).
5. **Editing a car's fuel**, for example Petrol to Diesel: the price field and the stations list switch fuel (Task 3).

---

### Task 1: Speed classing and the route split

**Files:**
- Create: `drive-split.js`
- Modify: `fuel-calculator.html` (the `<script>` tag, and `fetchRoute` for OSRM and ORS)
- Modify: `sw.js`
- Test: `tests/test_route_stations.py` (it already loads the page; add a `DriveSplitTest` class there), `tests/test_offline.py` if it lists the shell files

**Interfaces:**
- Produces `window.DriveSplit`:
  - `classify(pieces: Array<{meters, seconds}>) -> {city, mixed, highway}` (metres). A piece with `seconds <= 0` counts as mixed.
  - `consumption(split, cons) -> number` gives l/100 km weighted by the split's metres. With an empty split it returns `cons.mixed`.
  - `add(a, b) -> split` adds two splits.
- `fetchRoute` legs become `{meters, seconds, split}`.
  - OSRM: request `&annotations=distance,duration`. Pieces come from `leg.annotation.distance[i]` and `duration[i]`, falling back to `[{meters: leg.distance, seconds: leg.duration}]`.
  - ORS: pieces come from each segment's `steps`, falling back to the segment itself.

- [ ] **Step 1: Write the failing tests.**

```python
def test_classify_bands(self):
    split = self.page.evaluate("DriveSplit.classify([{meters:1000,seconds:72},{meters:1000,seconds:60},{meters:1000,seconds:42.35},{meters:1000,seconds:36}])")
    # 50 km/h, 60 km/h, 85 km/h, 100 km/h
    self.assertEqual(split, {"city": 1000, "mixed": 2000, "highway": 1000})

def test_zero_duration_counts_as_mixed(self):
    self.assertEqual(self.page.evaluate("DriveSplit.classify([{meters:500,seconds:0}])"), {"city": 0, "mixed": 500, "highway": 0})

def test_weighted_consumption(self):
    v = self.page.evaluate("DriveSplit.consumption({city:10000,mixed:0,highway:30000},{city:8,mixed:6,highway:5})")
    self.assertAlmostEqual(v, 5.75)

def test_empty_split_uses_mixed(self):
    self.assertEqual(self.page.evaluate("DriveSplit.consumption({city:0,mixed:0,highway:0},{city:8,mixed:6,highway:5})"), 6)
```

  - The 85 km/h test row: 1000 m in 42.35 s is 85.0 km/h. Make it exactly 85 by computing `seconds = 3.6 * meters / 85`, and assert that it counts as mixed.
  - In `tests/test_app.py`, add `osrm_with_speeds()`: one leg of 100 km, `annotation.distance = [20000, 80000]`, `annotation.duration = [1440, 3200]` (20 km at 50 km/h, then 80 km at 90 km/h). Add:

```python
def test_route_request_asks_for_speeds_and_legs_carry_a_split(self):
    page = self.open()
    self.routes["osrm"] = osrm_with_speeds()
    page.fill("#origin", "Vilnius"); page.fill("#dest", "Kaunas"); page.click("#routeBtn")
    page.wait_for_selector("#routeMsg.ok")
    self.assertIn("annotations=distance,duration", self.osrm_requests[-1])
    self.assertEqual(page.evaluate("lastRoute.legs[0].split"), {"city": 20000, "mixed": 0, "highway": 80000})
```

- [ ] **Step 2: Run the tests.** Expected: they FAIL, because `DriveSplit` is undefined and there are no annotations.
- [ ] **Step 3: Implement `drive-split.js`, the `fetchRoute` changes and the `sw.js` update.**
  - Check how `fetchRoute`'s legs reach `lastRoute.legs`, and attach the split there.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit.** Message: "feat: class route stretches by speed into city, mixed and highway".

### Task 2: Auto driving type in the maths, legs and saved trips

**Files:**
- Modify: `fuel-calculator.html`, in these places: the driving-type radio group, `cycle()`, `calc()`, `renderLegs()`, `tripCost()`, the code that saves a trip (`cycle: cycle()`) and the code that loads a trip.
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `DriveSplit` and `lastRoute.legs[i].split` from Task 1.
- Produces:
  - A radio `value="auto"` (label "Auto"), checked by default, as the first of four. The `.seg` grid gets 4 columns for this group.
  - A `<div class="hint" id="cycleNote">` under the control. It shows the split copy only when Auto is selected.
  - `routeSplit() -> split|null`, the sum of `lastRoute.legs[].split` when every leg has one, otherwise `null`.
  - `consNow() -> number`: with Auto, `DriveSplit.consumption(routeSplit(), car().cons)`, or `car().cons.mixed` when `routeSplit()` is null. Otherwise `car().cons[cycle()]`.
  - `calc` and `renderLegs` use `consNow()`. In Auto, each leg uses `DriveSplit.consumption(leg.split, cons)`.
  - `tripCost(t)`: when `t.cycle === "auto"` and every saved leg has a split, it uses the summed split. Otherwise it uses `cons[t.cycle] || cons.mixed`.
  - Typing a distance (which already sets `lastRoute = null`) makes Auto show "Auto: no route yet, using Mixed".

- [ ] **Step 1: Write the failing tests.**
  - The `test_app.py` tests:
    - `test_auto_is_the_default_and_shows_the_split`: route with `osrm_with_speeds()`. Check that `#cycleNote` reads "Auto: 80 km highway, 20 km city", and that `#rCons` is the weighted value for the default SEAT (9.2 city, 6.0 highway: (20×9.2 + 80×6.0)/100 = 6.64), shown as "6.6 l/100".
    - `test_auto_cost_uses_each_part`: `#rLitres` is "6.6" (6.64 L for 100 km).
    - `test_auto_without_route_uses_mixed`: on open, `#cycleNote` reads "Auto: no route yet, using Mixed" and `#rCons` is "7.0 l/100".
    - `test_manual_type_still_works`: clicking City makes `#rCons` "9.2 l/100" and hides `#cycleNote`.
    - `test_round_trip_auto_doubles`: with Round trip checked, `#rLitres` is "13.3".
    - `test_saved_auto_trip_prices_with_its_split`: save a trip, change the type to Highway, then check that the saved trip's cost still matches the Auto price.
    - `test_old_saved_trip_keeps_its_type`: seed `fc.trips` with `cycle: "city"` and legs without a split, then check its cost uses 9.2.
  - Update existing tests that click the cycle radios or assume Mixed is the default. The default fixture route (`osrm_default`, 100 km in 4200 s, about 86 km/h) now counts as highway. Fix each affected expected number by selecting Mixed in that test, rather than changing the numbers.
- [ ] **Step 2: Run the tests.** Expected: the new tests FAIL.
- [ ] **Step 3: Implement as specified in Interfaces.**
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit.** Message: "feat: Auto driving type from the route's speeds".

### Task 3: Compact car card with edit, add and delete

**Files:**
- Modify: `fuel-calculator.html` (the Car section markup and CSS, `renderCars`/`syncCarFields`, the `addCar` handler, `readConsFields` and the consumption inputs, and the `mUse` handler)
- Test: `tests/test_app.py`

**Interfaces:**
- Produces this markup inside the Car section:
  - `#carSelect`;
  - `#carSummary`, holding the exact summary copy;
  - `#editCar` ("Edit car") and `#newCar` ("+ Add a car");
  - `<form id="carForm" hidden>` with these fields: `#cfName`, `#cfYear` (optional number), `#cfFuel` (select with petrol95, diesel and lpg), `#cfTank`, `#cfCity`, `#cfMixed` and `#cfHwy`;
  - the form's buttons: `#cfSave` (submit), `#cfCancel` and `#cfDelete` (hidden in add mode, and when `cars.length === 1`);
  - the estimates hint, inside the form.
- Removes: `#consCity`, `#consMixed`, `#consHwy`, `#carSpec`, the `<details>` "Add another car" and the `#addCar` form. Update every reference, and change `mUse` to update the car and `#carSummary`.
- `openCarForm(mode: "edit" | "new")`: fills the form (Edit uses the car's values, New uses Petrol 95, 50 l, 9 / 7 / 6), shows it and focuses `#cfName`.
- Save:
  - Edit mode updates the car in place and keeps its id.
  - New mode adds a car with id `"car-" + Date.now()` and selects it.
  - Both then call `store.set("fc.cars")` and `renderCars()`, and hide the form.
- Delete:
  - It asks with `confirm("Delete {name}? This can't be undone.")`.
  - On yes, it removes the car, selects `cars[0]`, saves `fc.cars` and `fc.carId`, re-renders, and hides the form.
- After any change, the price label and fuel, the stations list (`renderRouteStations()`) and `calc()` follow the selected car.

- [ ] **Step 1: Write the failing tests.**
  - The `test_app.py` tests:
    - `test_car_card_is_compact`: `#carSummary` reads "Petrol 95 · 50 l tank · 9.2 / 7.0 / 6.0 l/100 km (city / mixed / highway)", `#carForm` is hidden, and `#consCity` doesn't exist.
    - `test_edit_car_changes_name_fuel_and_consumption`: click `#editCar`, set the name to "My Leon", the fuel to diesel and mixed to 6.5, then save. The select shows "2017 My Leon", the summary starts "Diesel", `#priceLabel` is "Diesel (EUR/l)", and `fc.cars[0].cons.mixed == 6.5` with the same id.
    - `test_add_car_selects_it`: click `#newCar`, fill the form and save. There are 2 options, and the new car is selected.
    - `test_cancel_leaves_car_unchanged`.
    - `test_delete_car`: add a car, then edit it and delete it, accepting the dialog with `page.once("dialog", lambda d: d.accept())`. One car is left and it's selected.
    - `test_delete_hidden_for_last_car`: `#cfDelete` is hidden when editing the only car.
    - `test_dismissed_delete_keeps_car`: dismiss the dialog and check that 2 cars remain.
    - `test_measured_value_updates_summary`: after `mUse`, the summary shows the new mixed value.
  - Update existing tests that used `#consCity`, `#consMixed`, `#consHwy` or `#addCar`, or the `add_car` helper. Rewrite `add_car` to use `#newCar` and `#carForm`.
- [ ] **Step 2: Run the tests.** Expected: the new tests FAIL.
- [ ] **Step 3: Implement as specified in Interfaces.**
  - Use the existing `.quiet`/`.primary` button styles, `.row`, `.row2` and `.stack`.
  - Add one short README line under "What it does" about editing and deleting cars and the Auto driving type.
- [ ] **Step 4: Run the whole suite.**
  - Expected: all pass, including the 360 px no-sideways-scroll tests.
  - Take a desktop and a 360 px screenshot of the Car section with the form open, and check them by eye.
- [ ] **Step 5: Commit.** Message: "feat: compact car card with edit, add and delete".

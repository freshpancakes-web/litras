# Fixes and Phone Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make today's prices reach the app sooner, stop the Mac and GitHub clashing over `prices.js`, add browser tests, make address suggestions keyboard-friendly, and let the app be installed on a phone and opened offline.

**Architecture:** The app stays one static page with no build step. A service worker and manifest are added beside it for the hosted copy only. GitHub stays the single producer of `prices.js`; the Mac asks GitHub to run the job and then pulls the result. Tests are Python Playwright, run locally and in GitHub Actions, with outside services mocked.

**Tech Stack:** Plain HTML/CSS/JS, Service Worker API, Web App Manifest, Bash, launchd, GitHub Actions, Python 3 `unittest` + Playwright.

**Spec:** No separate spec file. The requirements are this plan's Global Constraints plus the user's choice on 2026-10-30: "Fixes + phone install", from the recommendation of price timing, Mac/GitHub clash, browser tests and keyboard suggestions, plus install on a phone with offline use.

## Evidence behind the decisions

- GitHub's scheduled runs start about 5–7 hours late: the `30 8` run has been starting at 14:47–15:23 UTC.
- A manual `workflow_dispatch` run isn't subject to that schedule delay. On 2026-10-19 one was running within seconds.
- The Mac log shows when LEA publishes: runs at 10:37, 10:49 and 10:51 got that day's prices; a run at 10:32 on 2026-10-30 did not. So Mac runs start at 10:45.
- `git pull --rebase` refuses to run while the Mac's job has changed `prices.js`.
- Pushes made with `GITHUB_TOKEN` don't trigger other workflows, and Pages deploys from `main` directly.

## Global Constraints

- No build step and no server. `fuel-calculator.html` must keep working from `file:///`.
- Prices load through `<script src="prices.js">`, not `fetch`. Keep the "Reload prices" trick (re-inserting the script with `?t=timestamp`).
- Keep the services: Leaflet (cdnjs 1.9.4), Photon, OSRM, optional OpenRouteService. No Google Maps.
- Attribution stays visible: LEA and the station companies next to the prices, OpenStreetMap and CARTO on the map.
- Never publish the `CARTO_KEY` value. `config.js` stays untracked and is never cached by the service worker.
- All `localStorage` access stays inside try/catch; the page must work without it. Existing keys are unchanged.
- Existing element IDs and behaviour stay as they are unless a task says otherwise.
- `update_prices.py` keeps working by hand and stays Python 3 standard library only.
- `prices.js` is generated, never hand-edited, so discarding local changes to that one file is safe. No other local change may ever be discarded.
- Work on a branch from `origin/main`. Do not push, merge or reinstall the launchd job during task execution (see "After the tasks").

## Review Focus

1. **Stale offline data looks current:** offline, the price pill must still show the real data date, and old prices must not be shown as new. Test: `test_offline_keeps_prices_and_date` (Task 4).
2. **New prices must beat the cache:** a returning online visitor must get new `prices.js` and new HTML without clearing anything. Test: `test_online_gets_new_prices_after_cache` (Task 4).
3. **The Mac job must never destroy work:** a checkout with commits, edits or another branch must be left intact. Tests: `test_keeps_local_commit`, `test_keeps_other_edits`, `test_skips_other_branch` (Task 3).
4. **Enter in an address field:** Enter with no highlighted suggestion must still calculate the route, and Enter on a highlighted one must only pick it. Tests: `test_enter_picks_highlighted_without_routing`, `test_enter_without_highlight_routes` (Task 2).
5. **Secrets in the cache or repo:** `config.js` must never enter the cache and the key must never be tracked. Tests: `test_config_never_cached` (Task 4), `test_no_secret_tracked` (Task 1).

---

### Task 1: Browser test suite and CI

**Files:**
- Create: `tests/test_app.py`, `tests/fixtures/prices.js`, `tests/requirements.txt`, `.github/workflows/tests.yml`
- Modify: `.gitignore`, `README.md`

**Interfaces:**
- Produces: `tests/test_app.py` with base class `AppTest(unittest.TestCase)`, which later tasks extend:
  - `self.open(theme="light", width=1280, height=900, key=None, prices="fixture") -> Page`. It starts from a fresh browser context, serves the repo root over a local `http.server` thread at `self.base`, and mocks the outside services.
  - Routes: `key=None` aborts `config.js`, otherwise serves it with that key. `prices="fixture"` serves the fixture, `"none"` aborts `prices.js`.
  - Mocks: Photon, OSRM and OpenRouteService return JSON the test sets through `self.routes`; `tile.openstreetmap.org` and `basemaps.cartocdn.com` return a 1×1 PNG and are recorded in `self.tile_urls`.
  - Leaflet and fonts load from the real CDN.
- Browser choice: env `FC_BROWSER_CHANNEL` is passed to `launch(channel=...)`. Local runs use `chrome`; CI leaves it unset and uses Playwright's Chromium.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/prices.js` follows the README format with `date` set to today's date when the test runs. Do this by having the test's mock replace the placeholder `__TODAY__`, so the pill is always "live". Stations must include:
- a `Šiaulių degalinė` network at 1.900 petrol (UTF-8 check)
- enough stations for an average petrol price of exactly 1.959
- exactly one LPG and one diesel value

- [ ] **Step 2: Write the tests**

These pin current behaviour, so they should pass straight away except where noted:
- `test_default_trip_costs`: `rCost` == `13.71`, `rKm` == `100.0 km`, `price` == `1.959`
- `test_missing_prices_uses_bundled`: `prices="none"` → `price` == `1.925`, `priceState` == `bundled`
- `test_network_cheapest_changes_price`: picking the `Šiaulių degalinė` network and basis `min` → `price` == `1.9`, and the name shows correctly in `stationList`
- `test_stop_shows_legs_and_cycle_changes_them`: add a stop, calculate with a two-leg mock → 2 `#legs li`; choosing Highway changes the first leg's text; typing in `distance` hides `#legs`
- `test_saved_trip_survives_reload`: set round trip and `perWeek` 5, save as `Home → work`, reload → row shown; click it → `perWeek` is 5 and `roundTrip` is checked
- `test_theme_is_remembered`: click `themeBtn`, reload → `data-theme` unchanged, `fc.theme` set
- `test_hosted_map_never_uses_keyless_carto`: for both themes with `key=None`, every URL in `self.tile_urls` is on `tile.openstreetmap.org`; `.osm-dark` is on the map container only in dark.
- `test_key_uses_carto_in_dark`: `key="test-key"`, dark → tile URLs contain `rastertiles/dark_all` and `key=test-key`
- `test_no_sideways_scroll`: at widths 360, 768, 1280, `document.documentElement.scrollWidth <= innerWidth`
- `test_attribution_visible`: `.leaflet-control-attribution` contains `OpenStreetMap`; `priceNote` contains `Lithuanian Energy Agency`
- `test_no_secret_tracked`: `config.js` isn't in `git ls-files`, and no tracked file contains the key prefix. Build the prefix in the test as `"cb1" + "_"` so the test doesn't match itself.

- [ ] **Step 3: Run the tests**

Run: `python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt && FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests -v`
Expected: all pass. If one fails, report it as a real bug in the task report rather than weakening the test.

- [ ] **Step 4: Add CI and ignores**

- `tests.yml`: runs on `pull_request` and on `push` to `main`, using `ubuntu-latest`, `python -m playwright install --with-deps chromium`, then the unittest command.
- Pin the Playwright version in `tests/requirements.txt`.
- `.gitignore`: add `.venv/` and `.taste/`.
- `README.md`: add a short "Running the tests" section.

- [ ] **Step 5: Commit**

Commit `tests/`, `.github/workflows/tests.yml`, `.gitignore`, `README.md` with message `test: add browser tests and CI`.

### Task 2: Keyboard support for address suggestions

**Files:**
- Modify: `fuel-calculator.html` (`wireSuggest` at about line 766, Enter listeners at about lines 845 and 980, `.sugg` styles)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `AppTest`, `self.routes` from Task 1.
- Produces: while an option is highlighted, the input's `aria-activedescendant` holds that option's id. Option ids are `<listId>-opt-<index>`. Highlight class is `.active`.

- [ ] **Step 1: Write the failing tests** (Photon mock returning 3 places)

- `test_arrow_keys_move_highlight`: type `Pan`, wait for the list, ArrowDown → first option has `.active` and its id equals `aria-activedescendant`; ArrowDown twice more → third; ArrowDown again → wraps to first; ArrowUp → third
- `test_enter_picks_highlighted_without_routing`: ArrowDown, Enter → input holds the first label, list hidden, no OSRM request recorded
- `test_enter_without_highlight_routes`: type, list open, Enter with nothing highlighted → OSRM request recorded
- `test_escape_closes_and_clears`: ArrowDown, Escape → list hidden, `aria-activedescendant` absent
- `test_stop_field_has_keyboard_support`: the same arrow and Enter behaviour on a stop's input

- [ ] **Step 2: Run them to verify they fail**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_app -k arrow -k enter -k escape -k stop_field -v`
Expected: FAIL, because no arrow handling exists.

- [ ] **Step 3: Implement**

- Add the keydown handling inside `wireSuggest`.
- The list option's `<button>` gets `tabindex="-1"`, and a highlighted option scrolls with `scrollIntoView({block:"nearest"})`.
- Picking runs the same code as a click.
- `close()` also removes `aria-activedescendant`.
- The two Enter listeners calculate only when the input has no `aria-activedescendant`. `origin` and `dest` register their listener before `wireSuggest` runs, so this attribute check is required; don't rely on `stopPropagation`.
- `.sugg button.active` looks the same as the existing hover style.

- [ ] **Step 4: Run all tests**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

Commit with message `fix: add keyboard support to address suggestions`.

### Task 3: Faster prices and a clean Mac sync

**Files:**
- Create: `update_from_github.sh`, `tests/test_update_from_github.py`
- Modify: `.github/workflows/update-prices.yml`, `schedule_prices.sh`, `README.md`

**Interfaces:**
- Produces: `update_from_github.sh`, with no arguments. Overrides for tests: `FC_GH` (path to gh, default `$HOME/.local/bin/gh`), `FC_WAIT_ROUNDS` (default `6`), `FC_WAIT_SECONDS` (default `30`). It always exits 0 unless the folder isn't a git repo. Every log line starts with `[YYYY-MM-DD HH:MM]`.

**Script behaviour:**
1. If `gh` exists, run `gh workflow run update-prices.yml`. A failure is logged and the script continues.
2. Up to `FC_WAIT_ROUNDS` times: wait `FC_WAIT_SECONDS`, `git fetch origin main`, and stop early when `origin/main:prices.js` has a newer `date` than the local file.
3. If the current branch isn't `main`, log and stop.
4. Run `git checkout -- prices.js`, then `git pull --ff-only origin main`. If that fails, log the reason and leave everything else alone.

- [ ] **Step 1: Write the failing tests**

Each test builds a temp bare `origin`, a clone and a fake `gh`, with `FC_WAIT_SECONDS=0`, and uses only `unittest`, `subprocess` and `tempfile`:
- `test_pulls_new_prices_over_local_change`: clone behind origin with a dirty `prices.js` → file equals origin's, `git status --porcelain` is empty
- `test_keeps_local_commit`: clone has a commit origin lacks → that commit still exists, exit 0, log says it could not update
- `test_keeps_other_edits`: dirty `fuel-calculator.html` → the edit is still there afterwards, and origin's `prices.js` is applied when the pull can fast-forward
- `test_skips_other_branch`: on a feature branch → the branch, HEAD and working files are unchanged
- `test_missing_gh_still_pulls`: `FC_GH` points to nothing → the pull still happens
- `test_failing_gh_still_pulls`: fake `gh` exits 1 → the pull still happens and the failure is logged
- `test_triggers_the_price_job`: fake `gh` records its arguments → `workflow run update-prices.yml`

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_update_from_github -v`
Expected: FAIL, because the script doesn't exist.

- [ ] **Step 3: Write `update_from_github.sh`** with the behaviour above, and make it executable

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_update_from_github -v`
Expected: PASS.

- [ ] **Step 5: Update `schedule_prices.sh`**

- `ProgramArguments` becomes `/bin/bash` and `$DIR/update_from_github.sh`.
- `StartCalendarInterval` has weekdays 1–5 at **10:45, 12:00 and 15:00**.
- Update the comments and echo text. `remove` is unchanged.
- Add a `tests/test_update_from_github.py` test that runs `bash -n schedule_prices.sh` and checks the three times appear in the script's plist template.

- [ ] **Step 6: Update `update-prices.yml`**

- Crons: `"0 9 * * 1-5"`, `"30 10 * * 1-5"`, `"0 12 * * 1-5"`, `"30 14 * * 1-5"`. Add a comment that GitHub can start scheduled runs hours late and that the Mac's trigger is the fast path.
- Add `concurrency: { group: update-prices, cancel-in-progress: false }`.
- Commit only when the new `date` is **later** than the old one (string comparison), so an older file can never replace a newer one.
- Run `git pull --rebase origin main` before `git push`.

Validate with: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/update-prices.yml'))"`, adding `pyyaml` to `tests/requirements.txt`.

- [ ] **Step 7: Update the README**

Describe the new flow, and state plainly that the hosted page gets the day's prices at about 10:45 only when the Mac is awake. Otherwise it gets them when GitHub's schedule runs.

- [ ] **Step 8: Commit**

Commit with message `fix: run price job sooner and sync the Mac from GitHub`.

### Task 4: Install on a phone and open offline

**Files:**
- Create: `manifest.webmanifest`, `sw.js`, `icons/icon-180.png`, `icons/icon-192.png`, `icons/icon-512.png`, `icons/icon-maskable-512.png`, `tests/test_offline.py`
- Modify: `fuel-calculator.html`, `README.md`

**Interfaces:**
- Consumes: `AppTest` from Task 1.
- Produces: `sw.js` with `CACHE_NAME = "fc-v1"`. Later releases change this name to replace the cached shell.

**Service worker rules:**

| Request | Strategy |
|---|---|
| Same-origin navigation, `fuel-calculator.html`, `index.html` | Network first with a 3 s timeout, then cache |
| Same-origin `prices.js`, including `?t=...` | Network first with a 3 s timeout, then the cached `prices.js` (`ignoreSearch`). Successful responses overwrite that single entry, so `?t=` never adds new entries |
| Same-origin manifest and icons | Cache first |
| Leaflet JS and CSS on `cdnjs.cloudflare.com` | Cache first (the URL is versioned). Precache with `mode: "cors"` |
| `fonts.googleapis.com`, `fonts.gstatic.com` | Serve from cache, refresh in the background |
| Everything else: `config.js`, tiles, Photon, OSRM, OpenRouteService, all non-GET | Not intercepted, never cached |

Install precaches the shell. A failure on the optional CDN or font entries must not fail the install. Activate deletes caches whose name isn't `CACHE_NAME`.

- [ ] **Step 1: Write the failing tests** in `tests/test_offline.py`

These run on the local server with the real service worker and no service-worker bypass. The fixture `prices.js` is served by an in-test handler, so its contents can change between loads:
- `test_manifest_is_installable`: the page links a manifest; it has `name`, `short_name`, `start_url` `./fuel-calculator.html`, `scope` `./`, `display` `standalone`; and all the icons return 200 with the stated sizes (read the PNG header)
- `test_offline_keeps_prices_and_date`: load, wait for `navigator.serviceWorker.controller`, reload, go offline, reload → page renders, `price` equals the fixture value, `priceState` contains the fixture's date, and `rCost` is calculated
- `test_offline_saved_trip_opens`: save a trip, go offline, reload, click the row → saved distance stays, `routeMsg` shows the existing connection error, `distHint` says the route could not be updated
- `test_offline_shows_map_note`: offline → `mapNote` visible with the exact copy below; back online → hidden
- `test_online_gets_new_prices_after_cache`: load and get controlled, change the served prices to a later date, reload → the new date shows
- `test_reload_prices_offline_keeps_prices`: offline, click `priceRefresh` → still has the cached prices and no JS error
- `test_config_never_cached`: serve a `config.js` with a fake key, load and get controlled → no key in `caches` under any URL containing `config.js`
- `test_attribution_visible_offline`: `priceNote` still names the Lithuanian Energy Agency

Also add to `test_app.py`:
- `test_file_url_has_no_service_worker`: opening from `file://` works, with `price` and `rCost` filled in and no `serviceWorker` registration

- [ ] **Step 2: Run them to verify they fail**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest tests.test_offline -v`
Expected: FAIL, because there's no manifest or `sw.js`.

- [ ] **Step 3: Create the manifest and icons**

- `name` "Trip fuel calculator", `short_name` "Fuel", `theme_color` and `background_color` `#f5f6f7`.
- Icon: a white rounded fuel drop on the accent colour `#1c4fa1`, with no text. The maskable version keeps the drop inside the central 80%.
- Render the PNGs once from an inline SVG with headless Chrome. Commit the PNGs only.

- [ ] **Step 4: Create `sw.js`** with the rules above

- [ ] **Step 5: Wire it into the page**

In `fuel-calculator.html`:
- Add `<link rel="manifest">`, `<link rel="apple-touch-icon" href="icons/icon-180.png">` and `<meta name="theme-color">`. `syncThemeButton` updates the theme colour to the current theme's `--bg`.
- Register `sw.js` only when `location.protocol === "https:"` or the host is `localhost`/`127.0.0.1`, inside try/catch.
- Add offline handling: on load and on the `offline`/`online` events, if `navigator.onLine` is false, show through the existing `showMapNote` the exact text `You're offline. The map and new routes need a connection. Saved trips and prices still work.` Clear it when back online, without hiding the note that says the map library did not load.

- [ ] **Step 6: Run all tests**

Run: `FC_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 7: Update the README**

Add an "Install on your phone" section:
- iPhone: Safari → Share → Add to Home Screen
- Android: Chrome → menu → Install app

Say what works offline, and that the prices shown offline are the last ones downloaded, with their date.

- [ ] **Step 8: Commit**

Commit with message `feat: install on a phone and open offline`.

---

## After the tasks (the controller asks the user first; not subagent work)

1. Final whole-branch review, then push the branch and open a pull request. The tests run on it.
2. On the user's OK, merge. On the Mac, update the main checkout: `git checkout -- prices.js && git pull --ff-only`.
3. On the user's OK, reinstall the Mac job with `bash schedule_prices.sh`, then run `launchctl start com.fuelcalculator.updateprices` and read the log to confirm `gh` works under launchd. If it can't reach the keychain, the job still pulls, and this is reported to the user.
4. Check the live site: `sw.js` and the manifest return 200, and `config.js` returns 404.
5. The user tries the install on their own phone. Nobody else can verify real iPhone or Android install, so don't claim it works before they confirm.

## Known limits (accepted)

- A direct push to `main` goes live without waiting for tests, because Pages deploys from the branch. Tests guard pull requests; blocking direct pushes is out of scope.
- Price commits by the bot don't trigger the tests.
- If the Mac is off, prices arrive whenever GitHub's schedule actually runs.
- Map tiles aren't stored for offline use, which respects OpenStreetMap's tile policy.
- Offline behaviour is tested in desktop Chromium; iPhone Safari is only checked by the user's own try.

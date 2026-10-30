# Litras

A single page that works out the fuel use and cost of a car trip in Lithuania. It routes the trip on a map, applies the car's consumption, and prices the fuel with the latest station prices from the Lithuanian Energy Agency (LEA).

Open it: **https://freshpancakes-web.github.io/litras/**

## What it does
- A list of cars with City, Mixed and Highway consumption you can edit, plus your own cars
- Your current location as the starting point (the browser asks first), with a "Use my location" button
- From and To with address suggestions, up to 8 stops, the route on a map, and a cost for each leg
- Station prices by network and municipality (average or cheapest), the 8 cheapest stations, and a 5-day, 30-day and 1-year chart of the national average
- Trips per week and saved trips, with a weekly and monthly cost
- Measuring consumption from a fill-up
- Light and dark mode

Everything you enter stays in your browser (`localStorage`). Your location is only sent to the address and routing services, the same as a typed address, and is only kept if you save a trip.

## Install on your phone
- iPhone: open the page in Safari, tap Share, then Add to Home Screen.
- Android: open the page in Chrome, tap the menu, then Install app.

On iPhone the home-screen app keeps its own saved trips and cars, separate from Safari, so they start empty after installing.

Once opened online, the page opens offline too. Offline, the calculator, your cars and your saved trips work. The map and new routes need a connection (a note on the page says so). The prices shown offline are the last ones downloaded, and the price label shows their date. When you are online again the page picks up the newest prices on its own.

## Files
| File | Purpose |
|---|---|
| `fuel-calculator.html` | The whole app. It also works when opened straight from the file. |
| `manifest.webmanifest`, `sw.js`, `icons/` | Make the page installable and let it open offline. `sw.js` never caches `config.js` (it passes it through with a time limit); change `CACHE_NAME` in it to replace the cached copy in a release. |
| `prices.js` | Station prices, written by `update_prices.py`. Don't edit it by hand. |
| `update_prices.py` | Finds LEA's newest Excel file, downloads it and writes `prices.js`, keeping about a year of history across files. `--check-fresh` fails if the prices are more than 7 days old. Python 3 standard library only. |
| `schedule_prices.sh` | Optional: installs a macOS job that runs `update_from_github.sh` on weekdays at 10:45, 12:00 and 15:00. |
| `update_from_github.sh` | Asks GitHub to refresh the prices, waits up to 3 minutes, then pulls them into this folder (only on `main`, fast-forward only; it discards nothing except local changes to `prices.js`). |
| `.github/workflows/update-prices.yml` | Runs the updater on GitHub on weekdays and commits prices only when their date is later than the current file's. |
| `config.js` | Optional and not in the repository: `window.FC_CONFIG = { cartoKey: "..." }` for a CARTO basemaps key. |

## How prices stay fresh
GitHub Actions builds `prices.js` and commits it; the hosted page serves that file. GitHub's own schedule runs four times a day on weekdays, but GitHub can start scheduled runs hours late. To be faster, the optional Mac job (`bash schedule_prices.sh`) triggers the same workflow at 10:45, 12:00 and 15:00 and pulls the result, so it needs the GitHub CLI (`gh`) signed in.

The hosted page therefore gets the day's prices at about 10:45 only when the Mac is awake then. Otherwise it gets them when GitHub's schedule runs, which may be later.

## Data and credits
Fuel prices: Lithuanian Energy Agency (LEA) and the companies that operate the stations, collected at about 10:00 on working days. Map data © OpenStreetMap contributors, map tiles © CARTO, address search by Photon (komoot), routes by OSRM or, with your own key, OpenRouteService.

## Running the tests
The browser tests use Python 3 and Playwright. They serve the page locally and mock the address, routing and map-tile services, so they need no keys; Leaflet and the fonts still load from their CDNs.

```
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m unittest discover -s tests -v
```

To use the Chrome you already have instead of downloading Chromium, skip the `playwright install` line and set `FC_BROWSER_CHANNEL=chrome` before the last command. The same tests run on GitHub for every pull request and push to `main`.

# Trip Fuel Calculator

A single page that works out the fuel use and cost of a car trip in Lithuania. It routes the trip on a map, applies the car's consumption, and prices the fuel with the latest station prices from the Lithuanian Energy Agency (LEA).

Open it: **https://freshpancakes-web.github.io/special-palm-tree/**

## What it does
- A list of cars with City, Mixed and Highway consumption you can edit, plus your own cars
- From and To with address suggestions, up to 8 stops, the route on a map, and a cost for each leg
- Station prices by network and municipality (average or cheapest), and the 8 cheapest stations
- Trips per week and saved trips, with a weekly and monthly cost
- Measuring consumption from a fill-up
- Light and dark mode

Everything you enter stays in your browser (`localStorage`).

## Files
| File | Purpose |
|---|---|
| `fuel-calculator.html` | The whole app. It also works when opened straight from the file. |
| `prices.js` | Station prices, written by `update_prices.py`. Don't edit it by hand. |
| `update_prices.py` | Downloads the LEA Excel file and writes `prices.js`. Python 3 standard library only. |
| `schedule_prices.sh` | Optional: a macOS job that runs the updater on weekdays at 10:30 and 15:00. |
| `.github/workflows/update-prices.yml` | Runs the updater on GitHub on weekdays and commits new prices. |
| `config.js` | Optional and not in the repository: `window.FC_CONFIG = { cartoKey: "..." }` for a CARTO basemaps key. |

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

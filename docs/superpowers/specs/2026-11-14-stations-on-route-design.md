# Stations on your route: design

Date: 2026-11-14. Status: draft for review.

## Goal

After a route is calculated, show the fuel stations along it with their prices: as price pins on the map, as a list, and as one recommended stop that can be added to the route. This combines options 1, 2 and 3 from the UX discussion.

## What we know (tested 2026-11-14)

- LEA's file has an address for each station (756 stations, 755 unique addresses), but no coordinates.
- I geocoded a random sample of 40 addresses:
  - Photon placed 38 on a building, after retrying 2 without their postcode.
  - Nominatim's reverse lookup confirmed 37 of those 38 were in the station's own municipality. The other was a same-named village elsewhere, and that check catches it.
  - 2 addresses only matched an area or postcode.
- So expect about 90% of stations to get a reliable position. The rest have no pin but still appear in the list.
- Nominatim's free-text search failed on these addresses (1 of 40), so it's only used for the municipality check.

## Constraints (unchanged from the app)

- No build step, no server, and it works from `file://`. Data loads through `<script>`, not `fetch`.
- Leaflet 1.9.4 stays, with no new map libraries.
- The browser sends no new data anywhere: geocoding happens when prices are built, not on the user's device.
- Attribution stays visible. Light and dark mode, 360 px phones, keyboard and screen readers all work.
- Existing behaviour, IDs and `localStorage` keys are unchanged. New keys are listed below.

## Part 1: Station positions (data)

**Where they live:** each station in `prices.js` gets an optional `g: [lat, lng]`, rounded to 5 decimals (about 1 m). Stations without a reliable position have no `g`. This adds about 15 KB to `prices.js`.

**Cache:** `station-coords.json`, committed next to `prices.js`, maps each address to:
- `{"g": [lat, lng], "checked": "YYYY-MM-DD"}` when found, or
- `{"g": null, "checked": "YYYY-MM-DD"}` when not found. Not-found addresses are retried after 30 days.

So after the first run, only new or changed addresses are looked up.

**Lookup, in `update_prices.py` with the standard library only:**
1. Photon search for `address + ", Lithuania"`, limited to Lithuania's bounding box.
2. If that isn't a building, retry without the trailing 5-digit postcode.
3. Accept only results of type `house`.
4. Check the municipality with Nominatim's reverse lookup at zoom 8, converting the name as the app already does. If it doesn't equal the station's LEA municipality, treat the address as not found.
5. Rate limits:
   - Photon: one request per 0.5 s.
   - Nominatim: one request per 1.1 s, with a `User-Agent` naming the app and its repository URL, as Nominatim's policy asks.
   - At most 900 lookups per run. The first run takes about 20 minutes on GitHub; later runs take seconds.
6. A failing lookup service never fails the price job. It logs the problem and keeps the cache.

**Command:** `update_prices.py --no-geocode` skips lookups, for hand runs and tests. The GitHub job geocodes, and the Mac job is unaffected because it only pulls.

**Workflow:**
- Commits `station-coords.json` together with `prices.js`.
- The job's timeout goes to 45 minutes.
- Unchanged rule: a commit happens only when the price date moves forward. On the first run after merging, I'll trigger the job by hand so positions arrive the same day.

## Part 2: Stations along the route (app)

**When it appears:** only after a route is calculated, which is when the route line exists. It's hidden when there's no route, when the distance is typed in by hand, or when the route fails.

**Which stations:**
- Stations with a position that sell the selected car's fuel.
- Matching the Station network filter. The Municipality and Average/Cheapest filters don't apply, because the route defines the area.
- Within the **"Off route"** distance: **1, 2 or 5 km**, default 2 km, remembered in `fc.detourKm`.

**Distances:**
- "Off route" is the straight-line distance from the station to the nearest point of the route line. It uses a flat-earth approximation, which is accurate to well under 1% at Lithuania's size.
- "At N km" is how far along the route that nearest point is.
- These are estimates, labelled as such ("about 1.2 km off route").

## Part 3: Recommended stop

The **reference price** is the average of the stations in the list.

The **fill** is the selected car's tank size in litres.

**Net saving** for each station:

```
(reference - price) * fill  -  detour cost
detour cost = 2 * off-route km * mixed consumption / 100 * price
```

**What's shown:**
- The station with the highest net saving, if that saving is at least 0.50 EUR:
  "Cheapest stop on your way: Jozita, Garliava. 1.650 EUR/l, about 1.2 km off route. A 50 L fill saves about 5.60 EUR against the average on your route."
- Otherwise: "Prices on your route are within a few cents of each other, so any station will do."

**Add as stop:**
- Inserts the station as a stop at the right place in the trip, by its position along the route, then recalculates the route. The trip cost and drive time update.
- Disabled when the trip already has 8 stops. It says why ("A trip can have up to 8 stops"), rather than failing silently.

## Part 4: Map pins

- A pin for each listed station, showing its price, such as "1.72".
- **Shading:** three shades of the app's accent blue, darkest for the cheapest third. There's no red or green.
- **Recommended stop:** its pin has a ring and is drawn on top.
- **Zoomed out (Leaflet zoom below 10):** pins show as small dots without labels, except the recommended stop, so long routes stay readable.
- **Tapping a pin:** a popup shows the network, address, price and price date, with an "Add as stop" button. The matching list row is highlighted.
- Pins are cleared and redrawn on every recalculation. They're never drawn without a route.

## Part 5: List

- A **"Stations on your route"** section in the results column, between the results card and the map. On phones that puts it before the map.
- **Header:** a count ("14 stations within 2 km"), the "Off route" control and a sort switch, **Price | Along the route**, defaulting to Price and remembered in `fc.stationSort`.
- **Each row:** the price, the network, the address, and "at 34 km, about 1.2 km off route".
- **Clicking a row:** pans the map to that pin and opens its popup. Rows are buttons, so this works with the keyboard and screen readers.
- **Length:** the first 10 rows show, with a "Show all N" button.
- **Empty state:** "No stations with a known position within 2 km of this route. Try 5 km." The empty state has a button that switches to 5 km.
- **Coverage note** under the list: "Positions are looked up from addresses, so a few stations can't be shown."

## Error handling

- A `prices.js` without `g` fields (older files, or the bundled fallback): the section says positions aren't available yet. Nothing breaks.
- Offline: saved trips don't keep the route line, so the section only appears for a route calculated in this visit, as when there's no route.

## Testing

**Python (`tests/test_update_prices.py`), with no network:**
- Accepting a result.
- Retrying without the postcode.
- Rejecting a result that isn't a building.
- Rejecting a result in the wrong municipality.
- Cache hits, and retrying not-found addresses after 30 days.
- The lookup limit.
- A failing service not failing the run.
- `--no-geocode`.
- Rounding.
- `g` being merged into the stations.

**Browser (`tests/test_app.py`), with the fixture stations given positions on a mocked route:**
- Hidden without a route.
- The corridor filter for 1, 2 and 5 km.
- Fuel and network filtering.
- Both sort orders, and "at N km" being correct.
- Recommendation and saving numbers, including the no-recommendation case.
- Add as stop inserting at the right position, and the 8-stop limit.
- Pin count, labels and shades, and dots when zoomed out.
- Row and pin cross-highlighting, and the keyboard.
- Show all, the empty state and its 5 km button.
- An old `prices.js` without positions.
- No sideways scroll at 360 px.
- Dark mode.

**Manual:**
- A real route, Vilnius to Kaunas, with real data after the first geocoding run, with screenshots in light and dark mode and on a phone.

## Out of scope

- Exact detours by routing to each station: too many requests for the free service.
- Opening hours, brands' loyalty prices, and live prices.
- Showing stations without a route. The municipality list already covers that.
- Clustering libraries.

## New storage keys

`fc.detourKm`, `fc.stationSort`.

## Open questions for review

1. The **fill size for savings** is the car's full tank (50 L by default). The alternative is just the fuel this trip needs, which gives smaller, maybe more realistic numbers.
2. The **default "Off route" distance** is 2 km.
3. The **minimum saving worth recommending** is 0.50 EUR.

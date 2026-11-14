# Plan ride view: design (short)

Date: 2026-11-15. Status: draft for review.

## Why

The calculator page is getting too crowded. The stations-on-your-route feature (price pins, station list, recommended stop) moves out of it into its own view, called **Plan ride** for now. Nothing about how the feature works changes.

## Approaches

- **A. Two views in the same app, switched from the header (chosen).** The route, car and stops are shared, so nothing is typed twice and "Add as stop" still updates the trip cost. This is the least new code.
- B. A separate `plan-ride.html` with its own From/To, car and map. Rejected because it duplicates address search, routing, cars and the map, and a trip planned there has no cost.
- C. A separate page opened from a button that passes the route over. Rejected because stops added there don't come back to the calculator, and the page can't be bookmarked without a trip.

## Design

**Switch:** a two-option switch in the header, "Trip cost | Plan ride". It's a link pair, so it works with the keyboard and screen readers, and the current option is marked `aria-current`.
- Trip cost is `#` (no hash) and Plan ride is `#plan`.
- The back button and bookmarks work. It works from `file://` and offline.
- The app opens on whichever view the address says. No new storage key.

**Trip cost view:** the page as it was before stations. Everything stays except the "Stations on your route" section and the pins on the map.

**Plan ride view:**
```
 [Trip: From / stops / To, Calculate route]   [Stations on your route]
 [Car: Vehicle]                               [Map with price pins   ]
```
- **Left column:**
  - The route part of Trip: saved trips, From, stops, To, "Add a stop", "Calculate route" and its message.
  - The Car section, because the car decides the fuel and the tank size.
- **Right column:** the "Stations on your route" section, then the map with pins.
- **Hidden in this view:** the trip result card, distance and drive time, legs, driving type, round trip, trips per week, saving a trip, routing options, Fuel price, and Measure consumption.
- **Station network:** a "Station network" select in the stations section. It is the same setting as the one in Fuel price, so changing either changes both.
- **Before there's a route:** the section says "Enter From and To and press Calculate route to see the stations on your way." That replaces today's hidden section. It says the same when the distance was typed by hand.
- **On phones:** the same order, one column, with the stations before the map.

**Shared between views:**
- One route, one map and one set of stops.
- Switching views never recalculates anything. It only shows or hides sections, and adds or removes the pin layer.
- "Add as stop" in Plan ride adds the stop and recalculates, so the trip cost is right when you switch back.

## Unchanged

- The corridor, recommendation and pin behaviour, all IDs, and all `localStorage` keys.
- `route-stations.js` and the price and position pipeline.

## Testing

- The existing station tests run in the Plan ride view.
- New tests:
  - The Trip cost view has no stations section and no pins.
  - Switching keeps the route and stops.
  - Opening `#plan` directly.
  - The back button.
  - The empty state before a route.
  - The shared network select.
  - No sideways scroll at 360 px in either view.
  - Dark mode.

## Left to the builder

- The exact look of the switch, within the app's existing segmented-control style.

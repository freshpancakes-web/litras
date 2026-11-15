# Car section upgrade: design (short)

Date: 2026-11-15. Status: approved.

## Why

The Car section takes a lot of room for something set once. Cars can't be edited (apart from consumption) or deleted. The City/Mixed/Highway choice is a guess the route itself can answer.

## Approaches

Options 1 (manage cars), 3 (driving type from the route) and 5 (compact car card) were chosen from a list of six. The others were set aside for now:
- a fill-up log;
- a starter list of cars;
- moving cars and trips between devices.

For option 3, the route's own speed data was chosen over asking the person. Both routers return per-stretch distance and time:
- OSRM through `annotations=distance,duration`;
- OpenRouteService through segment steps.

## Design

**Compact car card:**
- The Vehicle select stays.
- One summary line: "Petrol 95 · 50 l tank · 9.2 / 7.0 / 6.0 l/100 km (city / mixed / highway)".
- Two buttons: **Edit car** and **+ Add a car**.

**Car form (one form, used for both buttons):**
- Fields: Name, Year (optional), Fuel, Tank (l), City, Mixed and Highway (l/100 km).
- Buttons: **Save** and **Cancel**. Edit also has **Delete car**.
- Delete asks for confirmation and is hidden when only one car is left. After a delete, the first remaining car is selected.
- The "Starting values are estimates…" hint moves into the form.
- The form starts closed.
- The current always-visible consumption inputs go away. Consumption is edited in the form.
- "Use as my mixed value" in Measure consumption keeps working.

**Driving type:** `Auto | City | Mixed | Highway`, with Auto as the default.
- **How Auto works:** each stretch of the route is classed by its average speed.
  - Below 60 km/h is city.
  - From 60 to 85 km/h is mixed.
  - Above 85 km/h is highway.
- **Fuel:** litres are the sum of each part's km × that part's consumption.
- **Effective consumption:** the shown l/100 km (and per-100-km cost) is the weighted result.
- **Split line under the control:** "Auto: 72 km highway, 21 km mixed, 8 km city".
- **No speed data:** if a leg has no speed details, the leg's own average speed classes the whole leg.
- **No calculated route** (typed distance, or a saved trip opened offline): Auto uses Mixed, and the line says "Auto: no route yet, using Mixed".
- **Legs list:** each leg uses its own split.
- **Saved trips:** they keep `cycle: "auto"` and each leg's split, and are priced with them.
- **Old saved choice:** a saved `cycle` of city, mixed or highway still works.

## Unchanged

- Storage keys `fc.cars` and `fc.carId`.
- The car data shape: `{id, name, year, fuel, tank, cons: {city, mixed, highway}}`.
- Station recommendation maths: it keeps using mixed consumption for the detour.

## Left to the builder

- Exact styling, within the app's existing look.
- Whether the speed classing lives in a small separate script (like `route-stations.js`). If it does, add it to `sw.js` and bump `CACHE_NAME`.

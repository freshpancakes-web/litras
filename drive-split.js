// Litras: how much of a route is city, mixed and highway driving, from the router's per-stretch speeds.
// Pure functions, no DOM. A "split" is { city, mixed, highway } in metres.
(function () {
  "use strict";

  const CITY_BELOW_KMH = 60;     // below 60 km/h: city
  const HIGHWAY_ABOVE_KMH = 85;  // above 85 km/h: highway; 60 to 85 inclusive: mixed

  const empty = () => ({ city: 0, mixed: 0, highway: 0 });

  // pieces: [{ meters, seconds }]
  function classify(pieces) {
    const split = empty();
    (pieces || []).forEach((p) => {
      const m = Number(p.meters) || 0;
      if (m <= 0) return;
      const s = Number(p.seconds) || 0;
      const kmh = s > 0 ? m / s * 3.6 : NaN;
      if (kmh < CITY_BELOW_KMH) split.city += m;
      else if (kmh > HIGHWAY_ABOVE_KMH) split.highway += m;
      else split.mixed += m;   // includes unknown speed
    });
    return split;
  }

  // l/100 km for the split, weighted by distance; the mixed value when the split is empty.
  function consumption(split, cons) {
    const total = split ? split.city + split.mixed + split.highway : 0;
    if (!(total > 0)) return cons.mixed;
    return (split.city * cons.city + split.mixed * cons.mixed + split.highway * cons.highway) / total;
  }

  function add(a, b) {
    return { city: a.city + b.city, mixed: a.mixed + b.mixed, highway: a.highway + b.highway };
  }

  window.DriveSplit = { classify, consumption, add, empty };
})();

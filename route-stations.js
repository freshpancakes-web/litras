/* Route maths for "stations on your route": which stations lie along a route and which one to recommend.
   Pure functions, no DOM. Routes and points are [lat, lng]. Defines only window.RouteStations. */
(function () {
  "use strict";
  var KM_LNG = 111.32, KM_LAT = 110.57, MIN_SAVING = 0.5;

  function project(route, point) {
    var meanLat = 0, i;
    for (i = 0; i < route.length; i++) meanLat += route[i][0];
    meanLat /= route.length || 1;
    var kx = Math.cos(meanLat * Math.PI / 180) * KM_LNG;
    function xy(p) { return [p[1] * kx, p[0] * KM_LAT]; }
    var pt = xy(point), best = { offKm: Infinity, alongKm: 0 }, run = 0, prev = route.length ? xy(route[0]) : null;
    if (route.length === 1) return { offKm: Math.hypot(pt[0] - prev[0], pt[1] - prev[1]), alongKm: 0 };
    for (i = 1; i < route.length; i++) {
      var cur = xy(route[i]), dx = cur[0] - prev[0], dy = cur[1] - prev[1], len2 = dx * dx + dy * dy, len = Math.sqrt(len2);
      var t = len2 ? ((pt[0] - prev[0]) * dx + (pt[1] - prev[1]) * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var off = Math.hypot(pt[0] - (prev[0] + t * dx), pt[1] - (prev[1] + t * dy));
      if (off < best.offKm) best = { offKm: off, alongKm: run + t * len };
      run += len;
      prev = cur;
    }
    return best;
  }

  function byPrice(a, b) {
    return a.price - b.price || a.alongKm - b.alongKm || String(a.station.a).localeCompare(String(b.station.a));
  }

  function corridor(stations, route, opts) {
    var field = opts.field, out = [];
    stations.forEach(function (s) {
      if (!s.g || s[field] == null) return;
      if (opts.network && s.c !== opts.network) return;
      var p = project(route, s.g);
      if (p.offKm <= opts.maxOffKm) out.push({ station: s, price: s[field], offKm: p.offKm, alongKm: p.alongKm });
    });
    return out.sort(byPrice);
  }

  function sortItems(items, by) {
    var copy = items.slice();
    return copy.sort(by === "along"
      ? function (a, b) { return a.alongKm - b.alongKm || byPrice(a, b); }
      : byPrice);
  }

  function recommend(items, opts) {
    if (!items.length) return null;
    var ref = items.reduce(function (s, i) { return s + i.price; }, 0) / items.length, best = null;
    items.forEach(function (it) {
      var saving = (ref - it.price) * opts.fillL - 2 * it.offKm * opts.consPer100 / 100 * it.price;
      if (!best || saving > best.saving || (saving === best.saving && it.alongKm < best.item.alongKm)) {
        best = { item: it, saving: saving, reference: ref };
      }
    });
    return best && best.saving >= MIN_SAVING ? best : null;
  }

  function insertIndex(alongKm, stops) {
    return stops.filter(function (s) { return s < alongKm; }).length;
  }

  function shade(price, min, max) {
    if (max === min) return 0;
    var f = (price - min) / (max - min);
    return f < 1 / 3 ? 0 : f < 2 / 3 ? 1 : 2;
  }

  window.RouteStations = { project: project, corridor: corridor, sortItems: sortItems, recommend: recommend, insertIndex: insertIndex, shade: shade };
})();

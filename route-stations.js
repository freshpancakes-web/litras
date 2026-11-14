/* Route maths for "stations on your route": which stations lie along a route and which one to recommend.
   Pure functions, no DOM. Routes and points are [lat, lng]. Defines only window.RouteStations. */
(function () {
  "use strict";
  var KM_LNG = 111.32, KM_LAT = 110.57, MIN_SAVING = 0.5;

  // Projects the route once (flat x/y in km, running length, bounding box) so every station reuses it.
  function prepare(route) {
    var n = route.length, meanLat = 0, i;
    for (i = 0; i < n; i++) meanLat += route[i][0];
    meanLat /= n || 1;
    var kx = Math.cos(meanLat * Math.PI / 180) * KM_LNG;
    var xs = new Float64Array(n), ys = new Float64Array(n), cum = new Float64Array(n);
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (i = 0; i < n; i++) {
      xs[i] = route[i][1] * kx; ys[i] = route[i][0] * KM_LAT;
      if (xs[i] < minX) minX = xs[i];
      if (xs[i] > maxX) maxX = xs[i];
      if (ys[i] < minY) minY = ys[i];
      if (ys[i] > maxY) maxY = ys[i];
      if (i) cum[i] = cum[i - 1] + Math.sqrt((xs[i] - xs[i - 1]) * (xs[i] - xs[i - 1]) + (ys[i] - ys[i - 1]) * (ys[i] - ys[i - 1]));
    }
    return { n: n, kx: kx, xs: xs, ys: ys, cum: cum, minX: minX, maxX: maxX, minY: minY, maxY: maxY };
  }

  function projectOn(r, point) {
    var px = point[1] * r.kx, py = point[0] * KM_LAT, xs = r.xs, ys = r.ys, i;
    if (r.n === 1) return { offKm: Math.sqrt((px - xs[0]) * (px - xs[0]) + (py - ys[0]) * (py - ys[0])), alongKm: 0 };
    var bestOff2 = Infinity, bestI = 0, bestT = 0;
    for (i = 1; i < r.n; i++) {
      var ax = xs[i - 1], ay = ys[i - 1], dx = xs[i] - ax, dy = ys[i] - ay, len2 = dx * dx + dy * dy;
      var t = len2 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var ex = px - (ax + t * dx), ey = py - (ay + t * dy), off2 = ex * ex + ey * ey;
      if (off2 < bestOff2) { bestOff2 = off2; bestI = i; bestT = t; }
    }
    if (!bestI) return { offKm: Infinity, alongKm: 0 };
    var sx = xs[bestI] - xs[bestI - 1], sy = ys[bestI] - ys[bestI - 1];
    return { offKm: Math.sqrt(bestOff2), alongKm: r.cum[bestI - 1] + bestT * Math.sqrt(sx * sx + sy * sy) };
  }

  function project(route, point) {
    return projectOn(prepare(route), point);
  }

  function byPrice(a, b) {
    return a.price - b.price || a.alongKm - b.alongKm || String(a.station.a).localeCompare(String(b.station.a));
  }

  function corridor(stations, route, opts) {
    var field = opts.field, out = [], r = prepare(route), pad = opts.maxOffKm;
    stations.forEach(function (s) {
      if (!s.g || s[field] == null) return;
      if (opts.network && s.c !== opts.network) return;
      if (r.n) {   // outside the route's box widened by maxOffKm means too far from every segment
        var x = s.g[1] * r.kx, y = s.g[0] * KM_LAT;
        if (x < r.minX - pad || x > r.maxX + pad || y < r.minY - pad || y > r.maxY + pad) return;
      }
      var p = projectOn(r, s.g);
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

#!/usr/bin/env python3
"""Builds prices.js for fuel-calculator.html from the Lithuanian Energy Agency (LEA) daily fuel price file.

Usage:
    python3 update_prices.py                 download the LEA Excel file, write prices.js next to this script
    python3 update_prices.py FILE.xlsx       use a file you already downloaded
    python3 update_prices.py FILE.xlsx OUT   also choose where prices.js is written

Needs only Python 3.8+ (standard library). Source: LEA (Lietuvos energetikos agentūra) and the companies
that operate the stations. Prices are collected every working day around 10:00.
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX_URL = "https://ltenergagen.sharepoint.com/:x:/s/intra/doc/IQBfrNG1U7XYR5LAZBxiytLDARSs2Dah4n5ehD0IaSg0dUs?e=7t6GjA"
LOCAL_XLSX = os.path.join(HERE, "DK-2026.xlsx")
DEFAULT_OUT = os.path.join(HERE, "prices.js")

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
FUELS = {"95 benzinas": "petrol95", "Dyzelinas": "diesel", "SND": "lpg"}
MIN_PRICE, MAX_PRICE = 0.3, 5.0          # EUR/l, anything outside is treated as a typing error
MIN_STATIONS_PER_NETWORK = 5
HISTORY_DAYS = 30


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M"), msg), flush=True)


# ---------- Getting the file ----------

def download(url, dest):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(url + sep + "download=1", headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=180) as resp, open(dest, "wb") as out:
        head = resp.read(4)
        if head != b"PK\x03\x04":
            raise RuntimeError("the server did not return an Excel file (link expired or needs sign-in)")
        out.write(head)
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


# ---------- Reading the Excel file (standard library only) ----------

def read_shared_strings(z):
    strings = []
    with z.open("xl/sharedStrings.xml") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == NS + "si":
                strings.append("".join(t.text or "" for t in el.iter(NS + "t")))
                el.clear()
    return strings


def column_of(ref):
    return re.match(r"[A-Z]+", ref).group(0)


def read_rows(z, strings):
    sheet = "xl/worksheets/sheet1.xml"
    if sheet not in z.namelist():
        sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
    with z.open(sheet) as f:
        for _, row in ET.iterparse(f, events=("end",)):
            if row.tag != NS + "row":
                continue
            if int(row.get("r")) > 7:          # rows 1-7 are title, notes and the column headers
                cells = {}
                for c in row.findall(NS + "c"):
                    v = c.find(NS + "v")
                    if v is None or v.text is None:
                        continue
                    cells[column_of(c.get("r"))] = strings[int(v.text)] if c.get("t") == "s" else v.text
                yield cells
            row.clear()


def parse(xlsx_path):
    rows = []
    with zipfile.ZipFile(xlsx_path) as z:
        strings = read_shared_strings(z)
        for cells in read_rows(z, strings):
            fuel = FUELS.get((cells.get("D") or "").strip())
            if not fuel:
                continue
            try:
                day = dt.date(1899, 12, 30) + dt.timedelta(days=int(float(cells["F"])))
            except (KeyError, ValueError):
                continue
            try:
                price = float(cells["E"])
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    price = None
            except (KeyError, ValueError):
                price = None                    # "neprekiauja" (not sold) or "nepateikė" (not reported)
            rows.append((day, clean(cells.get("A")), clean(cells.get("B")), clean(cells.get("C")), fuel, price))
    return rows


# ---------- Numbers ----------

def clean(text):
    return " ".join((text or "").split())      # also turns non-breaking spaces into normal ones


def short_name(company):
    return re.sub(r"^(UAB|AB|MB|IĮ|VšĮ|ŽŪB|KB)\s+", "", company).strip()


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"avg": round(sum(values) / len(values), 3), "min": min(values), "max": max(values), "n": len(values)}


def build(rows):
    if not rows:
        raise RuntimeError("no price rows found in the file")
    latest = max(r[0] for r in rows)

    stations = {}
    for day, company, muni, addr, fuel, price in rows:
        if day != latest:
            continue
        s = stations.setdefault((company, addr), {"c": short_name(company), "m": muni, "a": addr,
                                                  "petrol95": None, "diesel": None, "lpg": None})
        if price is not None:
            s[fuel] = price
    station_list = sorted(stations.values(), key=lambda s: (s["c"], s["a"]))

    national = {f: stats(s[f] for s in station_list) for f in FUELS.values()}

    by_network = defaultdict(list)
    for s in station_list:
        by_network[s["c"]].append(s)
    networks = []
    for name, group in sorted(by_network.items(), key=lambda kv: -len(kv[1])):
        if len(group) < MIN_STATIONS_PER_NETWORK:
            continue
        entry = {"name": name, "stations": len(group)}
        for f in FUELS.values():
            entry[f] = stats(s[f] for s in group)
        networks.append(entry)

    per_day = defaultdict(lambda: defaultdict(list))
    for day, _, _, _, fuel, price in rows:
        if price is not None:
            per_day[day][fuel].append(price)
    history = []
    for day in sorted(per_day)[-HISTORY_DAYS:]:
        point = {"date": day.isoformat()}
        for f in FUELS.values():
            vals = per_day[day][f]
            point[f] = round(sum(vals) / len(vals), 3) if vals else None
        history.append(point)

    return {
        "date": latest.isoformat(),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Lietuvos energetikos agentūra (LEA), prices from the companies operating the stations",
        "national": national,
        "networks": networks,
        "stations": [{"c": s["c"], "m": s["m"], "a": s["a"], "p": s["petrol95"], "d": s["diesel"], "l": s["lpg"]}
                     for s in station_list],
        "history": history,
    }


def write_js(data, out_path):
    text = "window.FUEL_PRICES = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, out_path)


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else None
    out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    tmp_file = None
    try:
        if xlsx is None:
            tmp_file = os.path.join(tempfile.gettempdir(), "lea-fuel-prices.xlsx")
            try:
                log("Downloading the LEA price file...")
                download(XLSX_URL, tmp_file)
                xlsx = tmp_file
            except Exception as e:
                log("Download failed: %s" % e)
                if os.path.exists(LOCAL_XLSX):
                    log("Using the file next to this script instead: %s" % LOCAL_XLSX)
                    xlsx = LOCAL_XLSX
                else:
                    log("Download the Excel file by hand from https://www.ena.lt/dk-pr-pr-duomenys/, save it as "
                        "DK-2026.xlsx next to this script and run it again.")
                    return 1
        log("Reading %s ..." % xlsx)
        data = build(parse(xlsx))
        write_js(data, out)
        n = data["national"]
        log("Wrote %s" % out)
        log("Prices for %s, %d stations." % (data["date"], len(data["stations"])))
        for key, label in (("petrol95", "Petrol 95"), ("diesel", "Diesel"), ("lpg", "LPG")):
            s = n[key]
            if s:
                log("  %-10s average %.3f, cheapest %.3f, highest %.3f (%d stations)" % (label, s["avg"], s["min"], s["max"], s["n"]))
        return 0
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""RG Pick-A-Part BMW 3 Series watcher.

Fetches the junkyard inventory, isolates every BMW 3 SERIES row, classifies each
by chassis generation (derived from model year), diffs the set of stock numbers
against the saved snapshot, updates the snapshot, and prints a report. Stock
numbers (STKxxxxx) are unique per vehicle and roughly chronological, so a stock
number not seen before = a newly intook car.
"""
import urllib.request, re, json, os, sys
from datetime import datetime
from collections import Counter

URL = "https://www.rgpick-a-part.com/inventory.php"
DIR = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(DIR, "snapshot.json")
LOG = os.path.join(DIR, "history.log")

# BMW 3 Series generations by US-market model year. Boundaries are chosen so each
# year maps to exactly one generation. Edit the ranges if needed.
GENERATIONS = [
    (0,    1991, "E30"),
    (1992, 1998, "E36"),
    (1999, 2005, "E46"),
    (2006, 2011, "E90"),   # E90/E91/E92/E93
    (2012, 2018, "F30"),   # F30/F31/F34 -- the user's car
    (2019, 9999, "G20"),   # G20/G21 and later
]
MY_GEN = "F30"  # generation the user owns -> highest-priority alert
GEN_ORDER = [g[2] for g in GENERATIONS] + ["?"]


def generation(v):
    try:
        y = int(v["year"])
    except (ValueError, TypeError, KeyError):
        return "?"
    for lo, hi, name in GENERATIONS:
        if lo <= y <= hi:
            return name
    return "?"


def gen_key(name):
    return GEN_ORDER.index(name) if name in GEN_ORDER else 99


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")


def parse_bmw3(html):
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<.*?>", "", c).strip()
                 for c in re.findall(r"<td.*?>(.*?)</td>", row, re.S)]
        if len(cells) >= 4 and cells[1].upper() == "BMW" and "3 SERIES" in cells[2].upper():
            stk = cells[3]
            out[stk] = {"year": cells[0], "model": cells[2], "stock": stk,
                        "row": cells[4] if len(cells) > 4 else ""}
    return out


def main():
    html = fetch()
    total_rows = len(re.findall(r"<tr>(.*?)</tr>", html, re.S))
    # Guard: a healthy page has ~3000 rows. A near-empty result means the fetch or
    # page changed -- abort WITHOUT clobbering the snapshot so we never emit a
    # false "everything removed / everything new".
    if total_rows < 100:
        print("WARNING: inventory page returned only %d rows -- likely a fetch or "
              "page-structure failure. Snapshot left untouched." % total_rows)
        sys.exit(1)

    current = parse_bmw3(html)
    prev = {}
    if os.path.exists(SNAP):
        try:
            with open(SNAP) as f:
                prev = json.load(f).get("vehicles", {})
        except (ValueError, OSError):
            prev = {}

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    today = now.split(" ")[0]
    # Per-car first-seen date + chassis generation.
    for stk, v in current.items():
        v["first_seen"] = (prev.get(stk) or {}).get("first_seen") or today
        v["gen"] = generation(v)

    new_keys = sorted(k for k in current if k not in prev)
    gone_keys = sorted(k for k in prev if k not in current)
    gen_counts = Counter(current[k]["gen"] for k in current)
    new_by_gen = Counter(current[k]["gen"] for k in new_keys)
    new_mygen = [k for k in new_keys if current[k]["gen"] == MY_GEN]
    mygen_keys = sorted((k for k in current if current[k]["gen"] == MY_GEN),
                        key=lambda x: (current[x]["first_seen"], current[x]["stock"]))

    breakdown = "  ".join("%s:%d" % (g, gen_counts[g]) for g in sorted(gen_counts, key=gen_key))
    hr = "-" * 64

    def row(v, tag=""):
        return "  %-6s %-10s Row %-5s first seen %s%s" % (
            v["year"], v["stock"], v["row"], v.get("first_seen", "?"), tag)

    def header(title):
        print("\n" + hr)
        print(title)
        print(hr)

    print("=" * 64)
    print(" RG Pick-A-Part -- BMW 3 Series Watch")
    print(" %s" % now)
    print("=" * 64)
    print("In stock: %d total   |  %s" % (len(current), breakdown))

    # Machine markers consumed by the scheduled task to decide the phone push.
    # Exactly one push fires per run: F30 priority > new-by-gen > plain status.
    if new_mygen:
        print("\nPUSH_PRIORITY_F30: %d new %s (your generation)!" % (len(new_mygen), MY_GEN))
    if new_keys:
        print("PUSH_NEW_BY_GEN: " + ", ".join(
            "%s=%d" % (g, new_by_gen[g]) for g in sorted(new_by_gen, key=gen_key)))
    else:
        gone_note = (", %d removed since last check" % len(gone_keys)) if gone_keys else ""
        print("\nPUSH_STATUS: %d 3-series in stock [%s] -- F30(yours)=%d, no new arrivals%s"
              % (len(current), breakdown, len(mygen_keys), gone_note))

    if new_keys:
        header("NEW SINCE LAST CHECK (%d)" % len(new_keys))
        for k in new_keys:
            v = current[k]
            tag = "  <== YOUR GEN" if v["gen"] == MY_GEN else "  [%s]" % v["gen"]
            print(row(v, tag))
    else:
        print("\nNew arrivals: none")

    if gone_keys:
        header("REMOVED / CRUSHED SINCE LAST CHECK (%d)" % len(gone_keys))
        for k in gone_keys:
            v = prev[k]
            print(row(v, "  [%s]" % v.get("gen", "?")))

    header("YOUR GENERATION -- %s (%d in stock)" % (MY_GEN, len(mygen_keys)))
    for k in mygen_keys:
        print(row(current[k]))

    header("FULL INVENTORY (%d)" % len(current))
    for k in sorted(current, key=lambda x: (gen_key(current[x]["gen"]), current[x]["stock"])):
        v = current[k]
        print(row(v, "  [%s]" % v["gen"]))

    with open(SNAP, "w") as f:
        json.dump({"updated": now, "count": len(current), "vehicles": current}, f, indent=2)
    with open(LOG, "a") as f:
        ng = ",".join("%s=%d" % (g, new_by_gen[g]) for g in sorted(new_by_gen, key=gen_key))
        f.write("%s\tcount=%d\tnew=%d\tgone=%d\tnew_gens=%s\tnew_ids=%s\n"
                % (now, len(current), len(new_keys), len(gone_keys), ng or "-", ",".join(new_keys)))


if __name__ == "__main__":
    main()

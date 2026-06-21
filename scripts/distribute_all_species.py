#!/usr/bin/env python

"""Place every National Dex species (1-493) into wild grass encounters.

Two layouts:

  spread (default): even round-robin across the Johto land maps. Species are
    striped (map k gets dex k, k+N, k+2N, ...) so adjacent routes hold
    different parts of the dex and the whole region feels populated. ~7
    distinct species per map.

  frontload: fill the earliest land maps first, 36 distinct species each
    (12 slots x morn/day/nite), so the dex is catchable within the first
    several routes.

Johto land maps are the contiguous block from R29 through R48 (the Kanto
block follows). Per-slot levels and encounter rates are preserved; only the
species are rewritten.

Usage:
    distribute_all_species.py                 # spread across Johto (apply)
    distribute_all_species.py --mode frontload
    distribute_all_species.py --report        # show the plan without writing
"""

import argparse
import json
import pathlib
import re

project_root = pathlib.Path(__file__).parent.parent
json_path = project_root / "files" / "fielddata" / "encountdata" / "gs_enc_data.json"

DEX_MAX = 493
SLOTS = 12
TIMES = ("morn", "day", "nite")
PER_MAP = SLOTS * len(TIMES)  # 36


def dex_list():
    num2name = {}
    with (project_root / "include" / "constants" / "species.h").open() as fp:
        for line in fp:
            m = re.match(r"#define (SPECIES_\w+)\s+(\d+)\b", line)
            if m:
                num2name.setdefault(int(m.group(2)), m.group(1))
    missing = [n for n in range(1, DEX_MAX + 1) if n not in num2name]
    if missing:
        raise SystemExit(f"species.h missing dex numbers: {missing[:10]}")
    return [num2name[n] for n in range(1, DEX_MAX + 1)]  # index 0 == dex #1


def johto_land_maps(encounters):
    land = [m for m in encounters if m.get("land", {}).get("mons")]
    names = [m["map"] for m in land]
    end = names.index("R48")  # last Johto route; Kanto block starts after
    return land[: end + 1]


def set_slots(land_map, species_for_slot):
    """species_for_slot(slot_index, time) -> SPECIES_ name."""
    for i, slot in enumerate(land_map["land"]["mons"]):
        slot["species"] = {t: species_for_slot(i, t) for t in TIMES}


def plan_spread(dex, maps):
    """Round-robin stripe species across maps; return per-map species lists."""
    n = len(maps)
    buckets = [[] for _ in range(n)]
    for idx, name in enumerate(dex):
        buckets[idx % n].append(name)
    return buckets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("spread", "frontload"), default="spread")
    ap.add_argument("--report", action="store_true", help="print the plan without writing")
    args = ap.parse_args()

    dex = dex_list()
    data = json.loads(json_path.read_text())
    johto = johto_land_maps(data["encounters"])

    if args.mode == "frontload":
        n_maps = -(-DEX_MAX // PER_MAP)
        targets = johto[:n_maps]
        for k, m in enumerate(targets):
            chunk = dex[k * PER_MAP : k * PER_MAP + PER_MAP]
            lo, hi = k * PER_MAP + 1, k * PER_MAP + len(chunk)
            print(f"{m['map']:>12}: dex #{lo}-{hi} ({chunk[0]} .. {chunk[-1]})")
            if not args.report:
                set_slots(m, lambda i, t, c=chunk: c[(TIMES.index(t) * SLOTS + i) % len(c)])
    else:  # spread
        buckets = plan_spread(dex, johto)
        for m, names in zip(johto, buckets):
            print(f"{m['map']:>12}: {len(names):>2} species  ({names[0]} .. {names[-1]})")
            if not args.report:
                # fill 12 slots; each slot cycles this map's species across the day
                set_slots(m, lambda i, t, c=names: c[(i + SLOTS * TIMES.index(t)) % len(c)])

    if args.report:
        return

    json_path.write_text(json.dumps(data, indent=1) + "\n")
    label = "front-loaded into earliest maps" if args.mode == "frontload" else "spread across Johto"
    print(f"\nwrote all {DEX_MAX} species {label} in {json_path.name}")


if __name__ == "__main__":
    main()

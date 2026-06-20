#!/usr/bin/env python

"""Dump or edit move data in files/poketool/waza/waza_tbl.narc.

The NARC stores one 16-byte MoveTbl entry per member (see include/move.h).
Member index == move ID, so file 0 is MOVE_NONE, file 1 is MOVE_POUND, etc.

Usage:
    waza_tbl.py dump                 # pretty table to stdout
    waza_tbl.py dump -o moves.json   # write editable JSON
    waza_tbl.py apply moves.json     # write JSON edits back into the NARC
"""

import argparse
import json
import pathlib
import struct

project_root = pathlib.Path(__file__).parent.parent
narc_path = project_root / "files" / "poketool" / "waza" / "waza_tbl.narc"

# MoveTbl layout from include/move.h (16 bytes, little-endian).
ENTRY_FMT = "<HBBBBBBHbBBBH"
ENTRY_SIZE = struct.calcsize(ENTRY_FMT)
assert ENTRY_SIZE == 16
FIELDS = (
    "effect",
    "category",
    "power",
    "type",
    "accuracy",
    "pp",
    "effectChance",
    "range",
    "priority",
    "unkB",
    "unkC",
    "contestType",
    "unkE",
)


def parse_defines(header, prefix, skip=()):
    """Map integer #define values under a prefix back to their names.

    The headers reuse these prefixes for unrelated constants that collide on
    value (e.g. MOVE_ATTRIBUTE_*, TYPE_MUL_*). The real move/type names come
    first in the file, so we keep the first definition seen for each value and
    skip names containing any substring in `skip`.
    """
    names = {}
    with (project_root / "include" / "constants" / header).open() as fp:
        for line in fp:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "#define" and parts[1].startswith(prefix):
                if any(s in parts[1] for s in skip):
                    continue
                try:
                    value = int(parts[2], 0)
                except ValueError:
                    continue  # skip non-numeric (expression) defines
                names.setdefault(value, parts[1])
    return names


MOVE_NAMES = parse_defines("moves.h", "MOVE_", skip=("ATTRIBUTE",))
CATEGORY_NAMES = parse_defines("moves.h", "CATEGORY_")
TYPE_NAMES = parse_defines("pokemon.h", "TYPE_", skip=("MUL", "FORESIGHT", "ENDTABLE"))


def read_narc():
    """Return (raw bytes, data_start, [(start, end), ...]) for the NARC members."""
    data = narc_path.read_bytes()
    if data[:4] != b"NARC":
        raise ValueError(f"{narc_path} is not a NARC file")
    off = 0x10  # skip NARC header
    if data[off : off + 4] != b"BTAF":
        raise ValueError("expected BTAF block")
    btaf_size = struct.unpack_from("<I", data, off + 4)[0]
    nfiles = struct.unpack_from("<H", data, off + 8)[0]
    allocs = []
    base = off + 0xC
    for i in range(nfiles):
        allocs.append(struct.unpack_from("<II", data, base + i * 8))
    # BTAF -> BTNF -> GMIF; member offsets are relative to GMIF's data.
    gmif = off + btaf_size
    gmif += struct.unpack_from("<I", data, gmif + 4)[0]  # skip BTNF
    if data[gmif : gmif + 4] != b"GMIF":
        raise ValueError("expected GMIF block")
    return data, gmif + 8, allocs


def decode(entry):
    values = struct.unpack(ENTRY_FMT, entry)
    return dict(zip(FIELDS, values))


def encode(move):
    return struct.pack(ENTRY_FMT, *(move[f] for f in FIELDS))


def cmd_dump(args):
    data, data_start, allocs = read_narc()
    moves = []
    for i, (start, end) in enumerate(allocs):
        entry = data[data_start + start : data_start + end]
        move = {"id": i, "name": MOVE_NAMES.get(i, f"MOVE_{i}")}
        move.update(decode(entry))
        moves.append(move)

    if args.output:
        args.output.write_text(json.dumps({"moves": moves}, indent=2) + "\n")
        print(f"wrote {len(moves)} moves to {args.output}")
        return

    header = f"{'ID':>3}  {'NAME':<20} {'CAT':<9} {'TYPE':<10} {'PWR':>3} {'ACC':>3} {'PP':>3} {'PRI':>3}"
    print(header)
    print("-" * len(header))
    for m in moves:
        cat = CATEGORY_NAMES.get(m["category"], str(m["category"])).replace("CATEGORY_", "")
        typ = TYPE_NAMES.get(m["type"], str(m["type"])).replace("TYPE_", "")
        print(
            f"{m['id']:>3}  {m['name']:<20} {cat:<9} {typ:<10} "
            f"{m['power']:>3} {m['accuracy']:>3} {m['pp']:>3} {m['priority']:>3}"
        )


def cmd_apply(args):
    moves = json.loads(args.input.read_text())["moves"]
    data, data_start, allocs = read_narc()
    buf = bytearray(data)
    for m in moves:
        i = m["id"]
        start, end = allocs[i]
        if end - start != ENTRY_SIZE:
            raise ValueError(f"move {i} member is {end - start} bytes, expected {ENTRY_SIZE}")
        buf[data_start + start : data_start + end] = encode(m)
    narc_path.write_bytes(buf)
    print(f"applied {len(moves)} moves to {narc_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("dump", help="print moves, or write them to JSON with -o")
    d.add_argument("-o", "--output", type=pathlib.Path, help="write editable JSON here")
    d.set_defaults(func=cmd_dump)

    a = sub.add_parser("apply", help="write JSON edits back into the NARC")
    a.add_argument("input", type=pathlib.Path, help="JSON file produced by 'dump -o'")
    a.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

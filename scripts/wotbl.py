#!/usr/bin/env python

"""Dump or edit level-up learnsets in files/poketool/personal/wotbl.narc.

Each NARC member is one species' learnset: a list of u16 entries, each packing
a move ID (low 9 bits) and the level it is learned at (high 7 bits), terminated
by 0xFFFF (see LEVEL_UP_LEARNSET_* in include/pokemon.h). Member index == species
ID; indices past the named species range are alternate-form learnsets.

Unlike waza_tbl, learnsets are variable length, so adding or removing a move
changes a member's size. 'apply' therefore rebuilds the NARC's allocation table
and size fields rather than patching in place.

Usage:
    wotbl.py dump                    # readable listing to stdout
    wotbl.py dump -o learnsets.json  # write editable JSON
    wotbl.py apply learnsets.json    # write JSON edits back into the NARC
"""

import argparse
import json
import pathlib
import struct

project_root = pathlib.Path(__file__).parent.parent
narc_path = project_root / "files" / "poketool" / "personal" / "wotbl.narc"

# include/pokemon.h
LEARNSET_END = 0xFFFF
MOVE_MASK = 0x01FF
LEVEL_SHIFT = 9
LEVEL_MAX = 0x7F  # 7 bits
MAX_ENTRIES = 21  # LEVEL_UP_LEARNSET_MAX, including the terminator
MAX_MOVES = MAX_ENTRIES - 1


def parse_defines(header, prefix, skip=()):
    """Map integer #define values under a prefix back to their first name."""
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
                    continue
                names.setdefault(value, parts[1])
    return names


MOVE_NAMES = parse_defines("moves.h", "MOVE_", skip=("ATTRIBUTE",))
MOVE_IDS = {name: value for value, name in MOVE_NAMES.items()}
SPECIES_NAMES = parse_defines("species.h", "SPECIES_")


def read_narc():
    """Return (raw bytes, header dict) describing the NARC blocks."""
    data = narc_path.read_bytes()
    if data[:4] != b"NARC":
        raise ValueError(f"{narc_path} is not a NARC file")
    btaf = 0x10
    if data[btaf : btaf + 4] != b"BTAF":
        raise ValueError("expected BTAF block")
    btaf_size = struct.unpack_from("<I", data, btaf + 4)[0]
    nfiles = struct.unpack_from("<H", data, btaf + 8)[0]
    allocs = [struct.unpack_from("<II", data, btaf + 0xC + i * 8) for i in range(nfiles)]

    btnf = btaf + btaf_size
    btnf_size = struct.unpack_from("<I", data, btnf + 4)[0]
    btnf_block = data[btnf : btnf + btnf_size]

    gmif = btnf + btnf_size
    if data[gmif : gmif + 4] != b"GMIF":
        raise ValueError("expected GMIF block")
    info = {
        "allocs": allocs,
        "data_start": gmif + 8,
        "btaf_off": btaf,
        "btnf_block": btnf_block,
    }
    return data, info


def cmd_dump(args):
    data, info = read_narc()
    learnsets = []
    for i, (start, end) in enumerate(info["allocs"]):
        raw = data[info["data_start"] + start : info["data_start"] + end]
        moves = []
        for j in range(0, len(raw), 2):
            entry = struct.unpack_from("<H", raw, j)[0]
            if entry == LEARNSET_END:
                break
            move_id = entry & MOVE_MASK
            moves.append({"level": entry >> LEVEL_SHIFT, "move": MOVE_NAMES.get(move_id, move_id)})
        learnsets.append({"id": i, "name": SPECIES_NAMES.get(i, f"MEMBER_{i}"), "moves": moves})

    if args.output:
        args.output.write_text(json.dumps({"learnsets": learnsets}, indent=2) + "\n")
        print(f"wrote {len(learnsets)} learnsets to {args.output}")
        return

    for ls in learnsets:
        if not ls["moves"]:
            continue
        print(f"[{ls['id']:>3}] {ls['name']}")
        for m in ls["moves"]:
            name = m["move"] if isinstance(m["move"], str) else f"MOVE_{m['move']}"
            print(f"        Lv {m['level']:>3}  {name}")


def resolve_move(move):
    """Accept a move name or raw int and return its numeric ID."""
    if isinstance(move, int):
        return move
    if move in MOVE_IDS:
        return MOVE_IDS[move]
    raise ValueError(f"unknown move {move!r}")


def cmd_apply(args):
    learnsets = json.loads(args.input.read_text())["learnsets"]
    data, info = read_narc()
    nfiles = len(info["allocs"])

    # Rebuild each member's bytes (preserve any not present in the JSON).
    members = [None] * nfiles
    for ls in learnsets:
        i = ls["id"]
        if len(ls["moves"]) > MAX_MOVES:
            raise ValueError(
                f"{ls['name']} (id {i}) has {len(ls['moves'])} moves; "
                f"the game supports at most {MAX_MOVES}"
            )
        entries = bytearray()
        for m in ls["moves"]:
            move_id = resolve_move(m["move"])
            level = m["level"]
            if not 0 <= move_id <= MOVE_MASK:
                raise ValueError(f"move id {move_id} out of range in {ls['name']}")
            if not 0 <= level <= LEVEL_MAX:
                raise ValueError(f"level {level} out of range in {ls['name']}")
            entries += struct.pack("<H", (level << LEVEL_SHIFT) | move_id)
        entries += struct.pack("<H", LEARNSET_END)
        if len(entries) % 4:  # pad to a 4-byte boundary as the original does
            entries += b"\x00\x00"
        members[i] = bytes(entries)
    # Members not overridden keep their original bytes.
    for i, (start, end) in enumerate(info["allocs"]):
        if members[i] is None:
            members[i] = data[info["data_start"] + start : info["data_start"] + end]

    # Recompute BTAF allocations (members stay contiguous, no padding).
    btaf = info["btaf_off"]
    btaf_size = struct.unpack_from("<I", data, btaf + 4)[0]
    out = bytearray(data[: btaf + 0xC])  # NARC header + BTAF header
    offset = 0
    for member in members:
        out += struct.pack("<II", offset, offset + len(member))
        offset += len(member)
    assert len(out) == btaf + btaf_size, "BTAF size changed unexpectedly"

    out += info["btnf_block"]

    file_data = b"".join(members)
    out += b"GMIF" + struct.pack("<I", 8 + len(file_data)) + file_data

    struct.pack_into("<I", out, 8, len(out))  # NARC total size field
    narc_path.write_bytes(out)
    print(f"applied {sum(1 for m in learnsets)} learnsets to {narc_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("dump", help="print learnsets, or write them to JSON with -o")
    d.add_argument("-o", "--output", type=pathlib.Path, help="write editable JSON here")
    d.set_defaults(func=cmd_dump)

    a = sub.add_parser("apply", help="write JSON edits back into the NARC")
    a.add_argument("input", type=pathlib.Path, help="JSON file produced by 'dump -o'")
    a.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python

"""Inspect or edit a Pokemon's shiny palette in files/poketool/pokegra.

In this decomp the shiny palette is the indexed palette embedded in a species'
male/back.png (see the -05.NCLR rule in pokegra.mk); the normal palette comes
from male/front.png. Sprite tile indices are shared, so editing only the
back.png palette RGB values recolors the shiny form without touching artwork.

Usage:
    shiny_palette.py dump 224                       # normal vs shiny, per index
    shiny_palette.py set 224 2=214,150,224 3=176,96,200 ...   # recolor shiny entries

Only palette colors change; pixel indices, image size and mode are preserved,
so the .png.key sprite encryption stays valid.
"""

import argparse
import pathlib
import sys

from PIL import Image

project_root = pathlib.Path(__file__).parent.parent
sprites_dir = project_root / "files" / "poketool" / "pokegra" / "pokegra"


def species_dir(species):
    return sprites_dir / f"{species:04d}"


def front_png(species):
    return species_dir(species) / "male" / "front.png"


def back_png(species):
    # The shiny palette (-05.NCLR) is extracted from male/back.png.
    return species_dir(species) / "male" / "back.png"


def palette(path):
    pal = Image.open(path).getpalette() or []
    return [tuple(pal[i * 3 : i * 3 + 3]) for i in range(len(pal) // 3)]


def cmd_dump(args):
    normal = palette(front_png(args.species))
    shiny = palette(back_png(args.species))
    width = max(len(normal), len(shiny))
    print(f"species {args.species:04d}")
    print(f"{'idx':>3} | {'NORMAL (front)':<16} | {'SHINY (back)':<16}")
    for i in range(width):
        n = normal[i] if i < len(normal) else None
        s = shiny[i] if i < len(shiny) else None
        print(f"{i:>3} | {str(n):<16} | {str(s):<16}")


def parse_assignment(token):
    idx, _, rgb = token.partition("=")
    r, g, b = (int(c) for c in rgb.split(","))
    for c in (r, g, b):
        if not 0 <= c <= 255:
            raise ValueError(f"channel out of range in {token!r}")
    return int(idx), (r, g, b)


def cmd_set(args):
    path = back_png(args.species)
    im = Image.open(path)
    if im.mode != "P":
        sys.exit(f"{path} is not a paletted image")
    before = list(im.getdata())
    pal = im.getpalette()
    for token in args.assignments:
        idx, rgb = parse_assignment(token)
        if idx * 3 + 2 >= len(pal):
            sys.exit(f"index {idx} out of palette range")
        pal[idx * 3 : idx * 3 + 3] = list(rgb)
        print(f"  index {idx} -> {rgb}")
    im.putpalette(pal)
    im.save(path)

    # Safety: confirm we only changed colors, not the artwork.
    after = list(Image.open(path).getdata())
    if after != before:
        sys.exit("ERROR: pixel indices changed; aborting would have corrupted the sprite")
    print(f"updated shiny palette in {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    d = sub.add_parser("dump", help="show normal vs shiny palette")
    d.add_argument("species", type=int)
    d.set_defaults(func=cmd_dump)

    s = sub.add_parser("set", help="recolor shiny palette entries (idx=R,G,B ...)")
    s.add_argument("species", type=int)
    s.add_argument("assignments", nargs="+", help="e.g. 3=176,96,200")
    s.set_defaults(func=cmd_set)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

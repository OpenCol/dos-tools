"""coldos -- the command line."""
import argparse
import json
import os
import sys

from . import __version__
from .formats import mapfile
from .madspack import Madspack, MadspackError, is_madspack, STORED
from .mapview import MapviewError, render_file
from .workspace import Workspace, WorkspaceError

EPILOG = """\
typical session:
  coldos extract ~/games/COLONIZE --out=ws
  ... edit ws/sprites/**/*.png in an indexed-mode paint program ...
  coldos status  ws
  coldos build   ws --out=patched
  coldos map-preview COLONY00.SAV ~/games/COLONIZE --out=map.png
"""

NATIONS = ("english", "french", "spanish", "dutch")


def cmd_list(args):
    if os.path.isdir(args.target):
        paths = [os.path.join(args.target, f) for f in sorted(os.listdir(args.target))]
    else:
        paths = [args.target]
    n = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as f:
            data = f.read()
        if not is_madspack(data):
            continue
        pack = Madspack.parse(data, path)
        n += 1
        line = "%-13s %7d bytes, %d entries" % (os.path.basename(path), len(data), len(pack.entries))
        if pack.trailing:
            line += ", %d trailing" % len(pack.trailing)
        print(line)
        if args.verbose:
            for i, e in enumerate(pack.entries):
                print("    %d  %-6s flag %02x  %7d -> %7d bytes"
                      % (i, "stored" if e.type == STORED else "FAB", e.flag, len(e.raw), e.size))
    if not n:
        print("no MADSPACK files in %s" % args.target)
    return 0


def cmd_extract(args):
    ws, counts = Workspace.extract(args.game, args.out)
    print("extracted to %s" % args.out)
    for k, n in sorted(counts.items()):
        print("    %-5s %4d file(s)" % (k, n))
    print("\n%s says what is there and how to edit it." % os.path.join(args.out, "README.md"))
    return 0


def cmd_status(args):
    ws = Workspace.open(args.workspace)
    changed = ws.changed()
    if not changed:
        print("no changes: every file matches what extract wrote")
        return 0
    for name, rec, why in changed:
        print("%-8s %s  (%s)" % (why, rec["file"], name))
    print("\n%d changed file(s); everything else goes back byte for byte." % len(changed))
    return 0


def cmd_build(args):
    ws = Workspace.open(args.workspace)
    written = ws.build(args.out, args.game, nearest=args.nearest, changed_only=args.changed_only)
    print("\n%d file(s) rebuilt into %s" % (len(written), args.out))
    if not args.changed_only:
        print("the rest of the game was copied alongside, so %s is a complete game "
              "directory." % args.out)
    return 0


def cmd_verify(args):
    ws = Workspace.open(args.workspace)
    same, total, tally, failures = ws.verify(args.game, repack=args.repack)
    print("untouched workspace rebuild: %d/%d files byte-identical\n" % (same, total))
    print("every extracted file forced back through its encoder%s:\n"
          % (", every entry re-packed" if args.repack else ""))
    print("  %-6s %7s %8s %6s" % ("kind", "exact", "content", "FAIL"))
    tot = [0, 0, 0]
    for k, t in sorted(tally.items()):
        print("  %-6s %7d %8d %6d" % (k, t["exact"], t["content"], t["fail"]))
        tot = [tot[0] + t["exact"], tot[1] + t["content"], tot[2] + t["fail"]]
    print("  %-6s %7d %8d %6d" % ("total", tot[0], tot[1], tot[2]))
    print("\n  exact   = the same bytes as the game's file")
    print("  content = the same entries once unpacked; FAB packed them differently")
    for name, why in failures[:20]:
        print("    FAIL %s: %s" % (name, why))
    if len(failures) > 20:
        print("    ... and %d more" % (len(failures) - 20))
    return 1 if failures else 0


def cmd_unpack(args):
    pack = Madspack.load(args.file)
    os.makedirs(args.out, exist_ok=True)
    meta = {"source": os.path.basename(args.file), "entries": [],
            "head": pack.head.hex(), "trailing": pack.trailing.hex()}
    for i, e in enumerate(pack.entries):
        name = "%02d.bin" % i
        with open(os.path.join(args.out, name), "wb") as f:
            f.write(e.data)
        meta["entries"].append({"file": name, "type": e.type, "flag": e.flag})
    with open(os.path.join(args.out, "madspack.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("%d entries of %s unpacked to %s" % (len(pack.entries), args.file, args.out))
    return 0


def cmd_pack(args):
    with open(os.path.join(args.dir, "madspack.json")) as f:
        meta = json.load(f)
    pack = Madspack(bytes.fromhex(meta["head"]), [], bytes.fromhex(meta.get("trailing", "")))
    from .madspack import Entry
    for rec in meta["entries"]:
        with open(os.path.join(args.dir, rec["file"]), "rb") as f:
            data = f.read()
        pack.entries.append(Entry(rec["type"], rec["flag"], 0, b""))
        pack.replace(len(pack.entries) - 1, data)
    with open(args.out, "wb") as f:
        f.write(pack.to_bytes())
    print("packed %d entries into %s" % (len(pack.entries), args.out))
    return 0


def _nation(s):
    if s is None:
        return None
    if s.isdigit() and int(s) < 4:
        return int(s)
    s = s.lower()
    for i, n in enumerate(NATIONS):
        if n.startswith(s):
            return i
    raise SystemExit("--seen-by takes english, french, spanish, dutch or 0-3")


def cmd_map_preview(args):
    r = render_file(args.map, args.game, args.out, zoom=args.zoom,
                    nation=_nation(args.seen_by), scenery=not args.plain, seed=args.seed)
    print("%s: a %dx%d %s map, planes at %#06x"
          % (os.path.basename(args.map), r["width"], r["height"], r["kind"], r["map_start"]))
    if r["kind"] == "SAV":
        print("    %d colonies, %d settlements, %d units (not drawn: draw_square does "
              "not draw them)" % (r["colonies"], r["settlements"], r["units"]))
    if args.plain:
        print("    --plain: no prime resources or rumours")
    elif r["seed"]:
        print("    scenery seed %d: %d prime resource(s), %d rumour(s) drawn"
              % (r["seed"], r["resources"], r["rumours"]))
    else:
        print("    no scenery seed: a .MP has no resources until a game starts on it "
              "(--seed=N to see one)")
    print("\nwrote %s, %dx%d pixels at %d px a square"
          % (args.out, r["image"][0], r["image"][1], r["tile"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="coldos", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Read and write the assets of Colonization for DOS (1994).")
    ap.add_argument("--version", action="version", version="coldos " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="the MADSPACK files in a game directory, or one file")
    p.add_argument("target")
    p.add_argument("-v", "--verbose", action="store_true", help="show every entry")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("extract", help="write every asset out as editable files")
    p.add_argument("game", help="the DOS game directory (the one with VICEROY.EXE)")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("status", help="what changed in a workspace")
    p.add_argument("workspace")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("build", help="put a workspace back into game files")
    p.add_argument("workspace")
    p.add_argument("--out", required=True)
    p.add_argument("--game", help="the game directory (default: the one extracted from)")
    p.add_argument("--nearest", action="store_true",
                   help="map colours outside the palette to the nearest entry")
    p.add_argument("--changed-only", action="store_true",
                   help="write only the files that changed, not a whole game directory")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("verify", help="re-encode a workspace and compare with the game")
    p.add_argument("workspace")
    p.add_argument("--game")
    p.add_argument("--repack", action="store_true",
                   help="also pack every entry again (slower; an edit re-packs only what changed)")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("unpack", help="dump a MADSPACK file's entries as raw files")
    p.add_argument("file")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_unpack)

    p = sub.add_parser("pack", help="pack a directory written by unpack")
    p.add_argument("dir")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("map-preview", help="draw a .MP or .SAV as one PNG")
    p.add_argument("map")
    p.add_argument("game", help="the DOS game directory, for the art")
    p.add_argument("--out", required=True)
    p.add_argument("--zoom", type=int, default=0,
                   help="the game's zoom level: 0-3 = 16, 8, 4, 2 px a square")
    p.add_argument("--seen-by", help="draw only what this nation has seen (a .SAV's plane 3)")
    p.add_argument("--seed", type=int, help="draw a .MP's resources as if this were its seed")
    p.add_argument("--plain", action="store_true", help="leave out resources and rumours")
    p.set_defaults(fn=cmd_map_preview)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (WorkspaceError, MadspackError, MapviewError, mapfile.MapError,
            OSError, ValueError) as e:
        print("coldos: %s" % e, file=sys.stderr)
        return 1

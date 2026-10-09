# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`coldos` extracts the assets of *Sid Meier's Colonization* for DOS (1994) out
of their MADSPACK containers into editable files (indexed PNGs, JASC `.pal`
palettes, UTF-8 text), puts them back, and draws maps and saves by replaying
the game's own square renderer. The repository does **not** contain the game;
the DOS game directory (the one with `VICEROY.EXE`) is supplied by path.

It is the DOS sibling of `../win-tools` (`colwin`), and deliberately shaped
like it: same invariants, same house style, same command names where the job
is the same. Source files cite evidence in `VICEROY.EXE` by **file offset**
and routine name (`draw_square`, file 0x681a8). Do not cite private research
repositories by name or path in this repository.

## Commands

```sh
python3 coldos.py list GAME [-v]                 # MADSPACK files and entries
python3 coldos.py extract GAME --out=ws
python3 coldos.py status ws
python3 coldos.py build ws --out=patched         # --changed-only, --nearest, --game
python3 coldos.py verify ws [--repack]           # rebuild + forced re-encode vs the game
python3 coldos.py map-preview MAP GAME --out=map.png   # --zoom 0-3, --seen-by, --seed, --plain
python3 coldos.py unpack FILE --out=dir / pack dir --out=FILE

python3 tests/test_roundtrip.py /path/to/COLONIZE           # 22 tests
python3 tests/test_map.py /path/to/COLONIZE [saves dir]     # 10 tests
```

Both test scripts take the game directory as `argv[1]` or `$COLDOS_GAME`
(and `test_map.py` a saves directory as `argv[2]` or `$COLDOS_SAVES`);
without them, the asset tests skip and the codec tests still run. That is
what CI does ([.github/workflows/test.yml](.github/workflows/test.yml)), so a
change that only passes with a game is not covered by CI. Run both suites
with the game before any commit.

## Layout

| | |
| --- | --- |
| [coldos/madspack.py](coldos/madspack.py) | the container: parse, replace an entry, write back |
| [coldos/fab.py](coldos/fab.py) | FAB decompress / compress |
| [coldos/formats/](coldos/formats/) | `ss` sprites, `pik` pictures, `ff` fonts, `text`, `mapfile` (.MP/.SAV) |
| [coldos/palette.py](coldos/palette.py) | VGA palettes, 6↔8 bit, the injectivity rule |
| [coldos/png.py](coldos/png.py) | PNG read/write, stdlib only (shared with win-tools) |
| [coldos/workspace.py](coldos/workspace.py) | extract / status / build / verify and the manifest |
| [coldos/mapview.py](coldos/mapview.py) | `map-preview`: `draw_square` replayed on every square |
| [coldos/cli.py](coldos/cli.py) | argparse front end; [coldos.py](coldos.py) runs it uninstalled |
| [docs/formats.md](docs/formats.md) | the formats and their evidence, in one page |

## Invariants to preserve

**Stdlib only, Python 3.9+.** No dependencies, ever.

**Unedited data is never re-encoded.** `coldos.json` records the SHA-256 of
each source file and of every file extract wrote. On `build` a source with no
changed file is copied verbatim; inside a changed source only the changed
parts are re-encoded, and a MADSPACK entry whose unpacked bytes did not change
keeps its packed bytes. The FAB packer is valid but not MicroProse's (479/793
identical), so routing unchanged entries through it would make every file
differ.

**Indices are the data; a palette is a way of looking at them.** PNG pixel
values are the game's bytes; view palettes are the file's own palette made
injective (`Palette.uniquify`). Sprite index 253 (0xFD) is transparent.

**UNKNOWN means carried, not computed.** The MADSPACK header slack and flag
byte, every `.SS` header byte but the count and size, the `.PIK` header's
last word, the sprite table's x/y, `VICEROY.PAL`'s last 256 bytes and
WIN-FWRK.SS's 104-byte palette entry are preserved verbatim. Do not infer a
meaning for them in code or docs — state the evidence or say UNKNOWN.

**Refuse rather than mangle.** Resizing a sprite or picture, a colour outside
the palette (`--nearest` overrides), index 255 in a sprite, a glyph pixel
above 3, a character outside cp437 all raise with an explanation naming the
file.

**The map preview replays, it does not invent.** `mapview.py` follows
`draw_square` / `draw_seams` / `GenerateTerrainMapRegion` statement for
statement, including their quirks (edge squares drawn hidden, pointers pinned
at the edges, `draw_map_tile2` filling every 0 pixel). A visual "improvement"
that departs from the routine is a bug. The one deliberate addition, clearing
owners for `--seed` on a `.MP`, is commented with why.

## Numbers are tested

Counts in the docs and docstrings (1,517 sprites, 793 FAB streams, 479
identical, 246 containers, 4 with trailing bytes, ...) are asserted by the
tests against a real install. Change a figure in prose only together with the
measurement.

## Style

`%` formatting, no f-strings, no type annotations. Module docstrings carry the
format layout and the evidence for it; keep that convention when adding a
format.

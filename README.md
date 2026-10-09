# dos-tools — read and write the assets of *Colonization* for DOS (1994)

`coldos` extracts every asset of the DOS game into files you can edit —
indexed PNGs, JASC `.pal` palettes, UTF-8 text — puts them back into the
game's own files afterwards, and draws `.MP` maps and `.SAV` saves as PNGs in
the game's own art. It is pure Python 3, stdlib only, no dependencies.

It is the DOS counterpart of
[win-tools](https://github.com/colonization-re/win-tools), which does the same
for the 1995 Windows release. The two games share their rules and their save
layout but not their asset formats: the DOS art lives in **MADSPACK**
containers from MicroProse's MADS engine, not in Win16 resources.

It does **not** contain the game. Bring your own copy.

## Install and run

There is nothing to install. You need **Python 3.9 or newer** and the DOS
game directory — the one holding `VICEROY.EXE` (in the GOG release, the
`COLONIZE` folder).

```sh
git clone https://github.com/OpenCol/dos-tools
cd dos-tools
python3 coldos.py --version
```

`coldos.py` runs the package straight out of the checkout, from any directory,
and `python3 -m coldos` does the same wherever the checkout is importable.

Then:

```sh
python3 coldos.py extract ~/games/COLONIZE --out=ws
#  ... edit ws/sprites/**/*.png in any paint program ...
python3 coldos.py status ws
python3 coldos.py build  ws --out=patched        # a complete, playable game directory
```

And to look at a map or a saved game — no workspace needed:

```sh
python3 coldos.py map-preview COLONY00.SAV ~/games/COLONIZE --out=map.png
```

## What comes out

| | |
| --- | --- |
| `sprites/<SHEET>/<nnn>.png` | 1,498 sprites from the 206 `.SS` sheets (19 more are 0×0 and have nothing to draw) |
| `pictures/<NAME>.png` | the 35 `.PIK` backdrops, mostly 320×200 |
| `fonts/<FONT>/<nnn>.png` | every glyph of the 5 `.FF` fonts, one file each |
| `palettes/<NAME>.pal` | `VICEROY.PAL`, the game's master palette, and every palette a sheet or picture carries |
| `text/<NAME>` | the 20 `.TXT` and `.DB` files, as UTF-8 |

`coldos verify ws` is the standing proof that the round trip is exact: an
untouched workspace rebuilds all 267 files byte for byte, and forcing every
extracted file back through its encoder — the path an edit takes —
reproduces the game's bytes too, including all 1,517 sprites' RLE.

**Indices are the data; a palette is a way of looking at them.** The PNGs are
indexed and their pixel values are the game's palette indices, viewed through
the file's own palette. That view palette is made injective — duplicate
colours nudged one step apart — so even a paint program that saves
truecolour maps every colour back to exactly one index. Sprite index 253 is
transparent, as it is in the game's RLE.

**Unedited files are never re-encoded.** `build` copies a file none of whose
parts changed, and inside a changed file re-encodes only the changed parts: a
sheet with one edited sprite keeps every other sprite's bytes. The FAB
compressor here makes valid streams that decode identically, but it does not
reproduce MicroProse's packer everywhere (479 of 793 streams come out
identical), so nothing is re-packed that does not have to be.

Edits that cannot be represented are refused with a message naming the file:
resizing a sprite or picture, a colour outside the palette (`--nearest`
overrides), palette index 255 in a sprite (the game's RLE cannot hold it), a
character outside code page 437. Glyphs may change width freely.

## Drawing a map

```
COLONY00.SAV: a 58x72 SAV map, planes at 0x25e7
    18 colonies, 27 settlements, 92 units (not drawn: draw_square does not draw them)
    scenery seed 19129: 298 prime resource(s), 9 rumour(s) drawn

wrote map.png, 928x1152 pixels at 16 px a square
```

**It has no renderer of its own.** It replays `draw_square`, the routine in
`VICEROY.EXE` that paints one map square, once per square, in the order
`GenerateTerrainMapRegion` walks them: the base tile, the seams against each
differently-classed neighbour (a mask icon, then the neighbour's tile drawn
only into the pixels the mask left at 0), forest, plowing, hills and
mountains, rivers, roads, the coastline's corner pieces with the water drawn
underneath them, prime resources and lost-city rumours hashed out of the
save's scenery seed. The tiles are `TERRAIN.SS`, the icons `PHYS0.SS`, the
colours `VICEROY.PAL` — the sheets and palette the game itself loads.

| | |
| --- | --- |
| `--zoom=0..3` | the game's own zoom levels: 16, 8, 4 or 2 px a square, shrunk the way the game shrinks them |
| `--seen-by=english` | only what that nation has seen (a save's plane 3); the rest is drawn hidden |
| `--seed=N` | draw a `.MP` as if a game had started on it with that scenery seed |
| `--plain` | leave out resources and rumours |

What it does not draw is what `draw_square` does not draw: units and
settlements, which the game paints in a separate pass.

## Everything else

```sh
python3 coldos.py list ~/games/COLONIZE -v        # every MADSPACK file and entry
python3 coldos.py unpack TERRAIN.SS --out=raw     # raw entries, for format work
python3 coldos.py pack raw --out=TERRAIN.SS
python3 coldos.py verify ws --repack              # also re-pack every entry (~10 s)
```

The formats, with the evidence for each, are in [docs/formats.md](docs/formats.md)
and in each module's docstring under [coldos/](coldos/).

## Tests

```sh
python3 tests/test_roundtrip.py ~/games/COLONIZE
python3 tests/test_map.py ~/games/COLONIZE [directory of COLONYnn.SAV]
```

Without a game directory the codec tests still run and the rest skip, which
is what CI does.

See [NOTICE.md](NOTICE.md) for what this repository is and is not.

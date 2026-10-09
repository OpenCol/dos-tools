# The DOS asset formats

Every claim here is either read from the code in `VICEROY.EXE` (addresses are
file offsets in the shipped 494,910-byte executable) or measured over every
shipped file, and the tests re-measure it. Anything not established is
carried through untouched and called UNKNOWN.

## MADSPACK 2.0 — the container

All 206 `.SS`, 35 `.PIK` and 5 `.FF` files are MADSPACK containers, the
format of MicroProse's MADS adventure engine.

```
0x00  13    "MADSPACK 2.0\x1a"
0x0d  BYTE  0
0x0e  WORD  entry count (1-16)
0x10  16 x 10-byte slots: BYTE type, BYTE flag, DWORD size, DWORD packed
0xb0  the entries' packed bytes, in order
....  (4 files) trailing bytes
```

Type 0 is stored, type 1 is FAB-packed. `ff_open` (0x76e50) and `ff_read`
(0x77100) read it. The slots past the last used one are not zeroed — they hold
what looks like leftover memory, x86 code among it — so the whole 0xb0-byte
header is carried verbatim, as are the flag byte and any trailing bytes. Module: [coldos/madspack.py](../coldos/madspack.py).

## FAB — the compression

An LZ77 variant with a 4,096-byte window: literals cost 9 bits, copies of
2–5 bytes within 256 cost 12, copies of 3–17 cost 18 and up to 256 cost 26.
Flag bits come LSB-first from 16-bit words interleaved with the data, and a
new word is fetched the moment the old one's 16th bit is asked for. All 793
shipped streams decode to exactly their declared size and end exactly at
their packed size. The packer here produces valid streams; 479 of the 793
come out byte-identical to MicroProse's. Module: [coldos/fab.py](../coldos/fab.py).

## `.SS` — sprite sheets

| entry | contents |
| --- | --- |
| 0 | 0x98-byte header: sprite count at +0x26, pixel-data size at +0x94, the rest carried |
| 1 | 16 bytes a sprite: offset, size, x, y, w, h |
| 2 | 0x300-byte VGA palette (WIN-FWRK.SS: 104 bytes of something else, carried) |
| 3 | the sprites' RLE |

The RLE is `draw_icon`'s (0xe76a): per row `FF` for an empty row, `FD`
followed by (count, colour) runs, or a plain row of colours with `FE count
colour` runs; colour `FD` is transparent; `FC` after the last row. The shipped
encoder's rules were measured: trailing transparency cut, runs from 4 pixels,
runs-only rows when strictly shorter, runs capped at 252. With those, all
1,517 sprites re-encode byte for byte. The game numbers sprites from 1
(`tiles_load` draws icon i+1 into tile i). Module:
[coldos/formats/ss.py](../coldos/formats/ss.py).

## `.PIK` — pictures

Entry 0 is `height, width, 0, UNKNOWN` as four words; entry 1 is
height×width raw pixels; entry 2 (34 of 35) a VGA palette. `load_picture`
(0x76aec) reads the first two entries and never the palette. Module:
[coldos/formats/pik.py](../coldos/formats/pik.py).

## `.FF` — fonts

Height, widest width, 128 widths, 128 offsets, then glyphs of ceil(w/4)
bytes a row at two bits a pixel; slot s is character s+1. In all five fonts
every byte is accounted for. Module: [coldos/formats/ff.py](../coldos/formats/ff.py).

## `VICEROY.PAL`

1,024 bytes; `load_palette_file` (0x781de) reads the first 0x300 as the
master palette at start-up. The last 256 bytes are never read and are carried.

## `.MP` and `.SAV`

A `.MP` is `width, height, version (must be 4)` then planes 0–2
(`load_map_file`, 0x71106). A DOS save starts `COLONIZE\0\x1a`, a version
word (73 in the 1994 saves) and the map size; its planes start at
`3005 + 18·settlements + 28·units + 202·colonies` and are followed by exactly
1,502 bytes, the little-endian scenery seed 890 from the end
(`save_game`, 0x734f8). Module: [coldos/formats/mapfile.py](../coldos/formats/mapfile.py).

## The text files

Plain code page 437 with CRLF, read line by line through stdio
(`text_open`, 0x6f8fa). The workspace holds them as UTF-8.

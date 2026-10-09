"""`.FF` fonts: one MADSPACK entry.

    0x000  BYTE   height of every glyph
    0x001  BYTE   width of the widest glyph
    0x002  BYTE   width[128]
    0x082  WORD   offset[128], from the start of the entry
    0x182  glyph rows, back to back in slot order

Slot s draws character s + 1: slot 31 is the space (no ink in any font) and
slot 64 is "A". A glyph is `height` rows of ceil(width / 4) bytes,
two bits a pixel, the leftmost pixel in the top two bits. A pixel is 0 (paper)
or 1-3, one of three ink colours the drawing code chooses.

That layout is the MADS engine's font format. What makes it established for
these files rather than borrowed is a set of checks (tests/test_roundtrip.py
re-runs them): in all five shipped fonts
each glyph starts exactly where the one before it ends, the last ends exactly
at the end of the entry, byte 1 is the largest width, and no row has a bit set
past its glyph's width. So every byte of every font is accounted for.

`dos_181f_2a86` (VICEROY.EXE overlay 27, file 0x76c70) loads the whole file
into memory under a tag of its name; `game_main` loads "fontintr" with it.
"""
import struct

SLOTS = 128
DATA = 2 + SLOTS + 2 * SLOTS          # 0x182


class FontError(Exception):
    pass


def row_bytes(w):
    return (w + 3) // 4


class Font:
    def __init__(self, data, name="font"):
        if len(data) < DATA:
            raise FontError("%s: %d bytes is shorter than a font header" % (name, len(data)))
        self.name = name
        self.height = data[0]
        self.max_width = data[1]
        self.widths = list(data[2:2 + SLOTS])
        offs = struct.unpack_from("<%dH" % SLOTS, data, 2 + SLOTS)
        self.glyphs = []
        for s in range(SLOTS):
            n = self.height * row_bytes(self.widths[s])
            if offs[s] + n > len(data):
                raise FontError("%s: glyph %d runs past the end" % (name, s))
            self.glyphs.append(decode_glyph(data[offs[s]:offs[s] + n],
                                            self.widths[s], self.height))
        self.raw = data

    def to_bytes(self):
        out = bytearray([self.height, max(self.widths)])
        out += bytes(self.widths)
        body, offs = bytearray(), []
        for s in range(SLOTS):
            offs.append(DATA + len(body))
            body += encode_glyph(self.glyphs[s], self.widths[s], self.height)
        out += struct.pack("<%dH" % SLOTS, *offs)
        return bytes(out + body)


def decode_glyph(data, w, h):
    """w*h pixel values 0-3."""
    rb = row_bytes(w)
    px = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            px[y * w + x] = (data[y * rb + x // 4] >> (6 - 2 * (x % 4))) & 3
    return bytes(px)


def encode_glyph(px, w, h):
    if len(px) != w * h:
        raise FontError("%d pixels for a %dx%d glyph" % (len(px), w, h))
    rb = row_bytes(w)
    out = bytearray(rb * h)
    for y in range(h):
        for x in range(w):
            v = px[y * w + x]
            if v > 3:
                raise FontError("pixel value %d at (%d,%d); a glyph has 0-3" % (v, x, y))
            out[y * rb + x // 4] |= v << (6 - 2 * (x % 4))
    return bytes(out)

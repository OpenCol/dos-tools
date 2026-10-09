"""`.SS` sprite sheets: four MADSPACK entries.

    entry 0   0x98-byte header
                0x00  BYTE   0 in every shipped sheet: the pixels are RLE
                             (non-zero would mean FAB-packed frames; refused)
                0x26  WORD   count of sprites
                0x94  DWORD  bytes in entry 3
                everything else carried verbatim (see below)
    entry 1   16 bytes per sprite
                DWORD  offset into entry 3
                DWORD  size in entry 3
                WORD   x, y   carried: the loader copies them, `draw_icon`
                              never reads them (they look like positions
                              on the artist's original sheet)
                WORD   w, h
    entry 2   the palette: 0x300 bytes of 6-bit VGA RGB (one sheet,
              WIN-FWRK.SS, has 104 bytes of something else; carried)
    entry 3   the sprites' RLE, back to back

The RLE, per row, as `draw_icon` (VICEROY.EXE file 0xe76a) reads it:

    FF                 an empty row: all transparent
    FD (n c)* FF       runs only: n copies of colour c
    xx (...)* FF       anything else leads a plain row, whose bytes are
                       colours, except FE n c, a run
    after the last row, one FC

Colour FD is transparent wherever it appears. The drawer skips a row it has
clipped by scanning for the next FF byte, so FF can never appear inside a
row: index 255 cannot be drawn, and no count is ever FF.

`draw_icon` takes 1-based numbers (`tiles_load` draws icon i + 1 into tile
i), so sprite k here is icon k + 1 in the game's code.

How the shipped sheets were packed, measured over all 1,517 sprites rather
than assumed: trailing transparent pixels are cut from each row; a plain row
leads with FE and writes a run only for 4 or more equal pixels; a runs-only
row is used exactly when it is strictly shorter than the plain one; no run
is longer than 252. `encode_sprite` follows those rules and reproduces every
shipped sprite byte for byte -- `coldos verify` checks that.

Header bytes other than the count and the size are carried. The sheet loader
(`dos_181f_2372`, overlay 27, file 0x76642) does read words at +2, +4, +6..0x25
and +0x90/+0x92, but what the game does with them is not established here.
"""
import struct

HEADER = 0x98
RECORD = 16
TRANSPARENT = 0xFD
MAX_RUN = 252
MIN_RUN = 4


class SheetError(Exception):
    pass


class Sprite:
    def __init__(self, x, y, w, h, rle):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.rle = rle

    def pixels(self):
        return decode_sprite(self.rle, self.w, self.h)


class Sheet:
    """A parsed sheet. Holds the container so it can be written back."""

    def __init__(self, pack, name="sheet"):
        if len(pack.entries) != 4:
            raise SheetError("%s: a sheet has 4 entries, this has %d" % (name, len(pack.entries)))
        self.pack = pack
        self.name = name
        self.header = bytearray(pack.entries[0].data)
        if len(self.header) != HEADER:
            raise SheetError("%s: header is %d bytes, not 0x98" % (name, len(self.header)))
        if self.header[0] != 0:
            raise SheetError("%s: FAB-packed frames (header byte 0 = %d) are not "
                             "shipped and not supported" % (name, self.header[0]))
        count = struct.unpack_from("<H", self.header, 0x26)[0]
        table = pack.entries[1].data
        pix = pack.entries[3].data
        if len(table) != count * RECORD:
            raise SheetError("%s: %d sprites but a %d-byte table" % (name, count, len(table)))
        if struct.unpack_from("<I", self.header, 0x94)[0] != len(pix):
            raise SheetError("%s: header says %d pixel bytes, entry 3 has %d"
                             % (name, struct.unpack_from("<I", self.header, 0x94)[0], len(pix)))
        self.sprites = []
        for i in range(count):
            off, size, x, y, w, h = struct.unpack_from("<IIhhHH", table, RECORD * i)
            if off + size > len(pix):
                raise SheetError("%s: sprite %d runs past the pixel data" % (name, i))
            self.sprites.append(Sprite(x, y, w, h, pix[off:off + size]))
        self.palette = pack.entries[2].data

    def rebuild(self):
        """Write the sprites back into the container, packing what changed."""
        table, pix = bytearray(), bytearray()
        for s in self.sprites:
            table += struct.pack("<IIhhHH", len(pix), len(s.rle), s.x, s.y, s.w, s.h)
            pix += s.rle
        hdr = bytearray(self.header)
        struct.pack_into("<H", hdr, 0x26, len(self.sprites))
        struct.pack_into("<I", hdr, 0x94, len(pix))
        for i, data in ((0, hdr), (1, table), (2, self.palette), (3, pix)):
            if bytes(data) != self.pack.entries[i].data:
                self.pack.replace(i, bytes(data))
        return self.pack


def decode_sprite(rle, w, h):
    """w*h colour indices; transparent pixels are TRANSPARENT."""
    px = bytearray([TRANSPARENT]) * (w * h)
    p = 0
    try:
        for y in range(h):
            x = 0
            base = y * w
            lead = rle[p]
            p += 1
            if lead == 0xFF:
                continue
            if lead == 0xFD:
                while True:
                    n = rle[p]
                    if n == 0xFF:
                        p += 1
                        break
                    c = rle[p + 1]
                    p += 2
                    for _ in range(n):
                        if x < w:
                            px[base + x] = c
                        x += 1
                continue
            while True:
                c = rle[p]
                p += 1
                if c == 0xFF:
                    break
                n = 1
                if c == 0xFE:
                    n, c = rle[p], rle[p + 1]
                    p += 2
                for _ in range(n):
                    if x < w:
                        px[base + x] = c
                    x += 1
    except IndexError:
        raise SheetError("RLE ends inside row %d of a %dx%d sprite" % (y, w, h))
    return bytes(px)


def _groups(row):
    out, k = [], 0
    while k < len(row):
        j = k
        while j < len(row) and row[j] == row[k] and j - k < MAX_RUN:
            j += 1
        out.append((j - k, row[k]))
        k = j
    return out


def encode_sprite(px, w, h):
    """The RLE for w*h indices, packed the way the shipped sheets were."""
    if len(px) != w * h:
        raise SheetError("%d pixels for %dx%d" % (len(px), w, h))
    out = bytearray()
    for y in range(h):
        row = bytes(px[y * w:(y + 1) * w]).rstrip(bytes([TRANSPARENT]))
        if 0xFF in row:
            raise SheetError("row %d uses index 255, which the RLE cannot hold "
                             "(the game's drawer would read it as end-of-row)" % y)
        if not row:
            out.append(0xFF)
            continue
        g = _groups(row)
        plain = bytearray([0xFE])
        for n, c in g:
            if n >= MIN_RUN:
                plain += bytes([0xFE, n, c])
            else:
                plain += bytes([c]) * n
        plain.append(0xFF)
        runs = bytearray([0xFD])
        for n, c in g:
            runs += bytes([n, c])
        runs.append(0xFF)
        out += runs if len(runs) < len(plain) else plain
    out.append(0xFC)
    return bytes(out)

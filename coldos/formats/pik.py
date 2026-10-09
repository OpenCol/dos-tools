"""`.PIK` pictures: two or three MADSPACK entries.

    entry 0   8 bytes: WORD height, WORD width, WORD 0, WORD UNKNOWN
    entry 1   height * width bytes, one colour index a pixel, rows top down
    entry 2   (34 of the 35 files) 0x300 bytes of 6-bit VGA RGB

Evidence: `load_picture` (VICEROY.EXE overlay 27, file 0x76aec) reads the
8-byte header, takes its first two words as height and width, and reads
height * width bytes of entry 1 straight into a port. It never reads entry 2,
so the palette is carried and used here only as the way to look at the
picture. The last two header words are carried: the third is 0 in every
file, the fourth varies (8110-9540) with no reader found.

Most pictures are 320 x 200, a full mode-13h screen. COLONY.PIK is 320 x 72
and has no palette; OPENING.PIK is 960 x 132.
"""
import struct


class PictureError(Exception):
    pass


class Picture:
    def __init__(self, pack, name="picture"):
        n = len(pack.entries)
        if n not in (2, 3):
            raise PictureError("%s: a picture has 2 or 3 entries, this has %d" % (name, n))
        self.pack = pack
        self.name = name
        self.header = pack.entries[0].data
        if len(self.header) != 8:
            raise PictureError("%s: header is %d bytes, not 8" % (name, len(self.header)))
        self.height, self.width = struct.unpack_from("<HH", self.header, 0)
        self.pixels = pack.entries[1].data
        if len(self.pixels) != self.width * self.height:
            raise PictureError("%s: %dx%d but %d pixel bytes"
                               % (name, self.width, self.height, len(self.pixels)))
        self.palette = pack.entries[2].data if n == 3 else None

    def rebuild(self, pixels=None, palette=None):
        if pixels is not None:
            if len(pixels) != self.width * self.height:
                raise PictureError("%s: %d pixels for %dx%d"
                                   % (self.name, len(pixels), self.width, self.height))
            if bytes(pixels) != self.pixels:
                self.pack.replace(1, bytes(pixels))
        if palette is not None and self.palette is not None and bytes(palette) != self.palette:
            self.pack.replace(2, bytes(palette))
        return self.pack

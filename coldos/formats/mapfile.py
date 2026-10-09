"""`.MP` maps and the map region of a DOS `.SAV`, as byte planes.

    .MP                                   .SAV (COLONYnn.SAV)
    0x00  WORD  width                     0x00  "COLONIZE\\0" 0x1a
    0x02  WORD  height                    0x0a  WORD  version
    0x04  WORD  version, must be 4        0x0c  WORD  width, WORD height
    0x06  plane 0, 1, 2 (w*h each)        0x2a  WORD  settlements (18 bytes each)
                                          0x2c  WORD  units (28 bytes each)
                                          0x2e  WORD  colonies (202 bytes each)
                                          ....  planes 0, 1, 2, 3 (w*h each)
                                          ....  1,502 bytes, the scenery seed
                                                among them (below)

**.MP.** `load_map_file` (VICEROY.EXE overlay 25, file 0x71106) reads the
size, then a version word it refuses unless it is 4, then exactly three
planes into planes 0, 1 and 2. Plane 3 -- who has seen each square -- is not
in a map file. A map of more than 12,000 squares is refused (`map_check`).

**.SAV.** `save_game` (overlay 26, file 0x734f8) writes the magic with
`save_string` (string, NUL, then 0x1a), a version word, the map size, then
fixed blocks and three record arrays whose counts are words of the game
state, then the four planes, then 1,502 more bytes. So the planes start at

    map_start = 3005 + 18*settlements + 28*units + 202*colonies

and the file is exactly `map_start + 4*w*h + 1502` bytes. That closure is
checked, not trusted. It is the same arithmetic as the Windows save, but
the DOS game swaps no bytes: the **scenery seed** -- which squares carry a
prime resource or a rumour (`resource_at`, `lost_city_at`) -- is a
little-endian word 890 bytes from the end (it is followed by the 888-byte
route table).

What the planes hold is drawn by `mapview.py`; this module only cuts them out.
"""
import struct

SAV_MAGIC = b"COLONIZE\0\x1a"
SAV_FIXED_BEFORE_MAP = 3005
SAV_FIXED_AFTER_MAP = 1502
SAV_RECORDS = ((0x2a, 18), (0x2c, 28), (0x2e, 202))
SAV_DIMS = 0x0c
SAV_SEED_FROM_END = 890
SAV_PLANES = 4
MP_PLANES = 3
MP_HEADER = 6
MP_VERSION = 4
MAX_SQUARES = 12000


class MapError(Exception):
    pass


def _planes(data, start, n, count):
    return [bytes(data[start + i * count:start + (i + 1) * count]) for i in range(n)]


def decode_mp(data):
    if len(data) < MP_HEADER:
        raise MapError("too short for a .MP header: %d bytes" % len(data))
    w, h, version = struct.unpack_from("<HHH", data, 0)
    if not w or not h:
        raise MapError("a %dx%d map has no squares" % (w, h))
    n = w * h
    if MP_HEADER + MP_PLANES * n != len(data):
        raise MapError("not a .MP: 6 + 3*%d*%d = %d but the file is %d bytes"
                       % (w, h, MP_HEADER + MP_PLANES * n, len(data)))
    planes = _planes(data, MP_HEADER, MP_PLANES, n)
    planes.append(bytes(n))                       # plane 3: nothing seen yet
    return {"kind": "MP", "width": w, "height": h, "version": version,
            "planes": planes, "map_start": MP_HEADER, "seed": 0}


def decode_sav(data):
    if data[:len(SAV_MAGIC)] != SAV_MAGIC:
        raise MapError("not a DOS save: it does not start COLONIZE\\0\\x1a")
    w, h = struct.unpack_from("<HH", data, SAV_DIMS)
    counts = {size: struct.unpack_from("<H", data, off)[0] for off, size in SAV_RECORDS}
    start = SAV_FIXED_BEFORE_MAP + sum(size * n for size, n in counts.items())
    n = w * h
    if start + SAV_PLANES * n + SAV_FIXED_AFTER_MAP != len(data):
        raise MapError("the save's layout does not close: %d + 4*%d*%d + %d = %d, "
                       "but the file is %d bytes"
                       % (start, w, h, SAV_FIXED_AFTER_MAP,
                          start + SAV_PLANES * n + SAV_FIXED_AFTER_MAP, len(data)))
    seed = struct.unpack_from("<H", data, len(data) - SAV_SEED_FROM_END)[0]
    return {"kind": "SAV", "width": w, "height": h,
            "version": struct.unpack_from("<H", data, 0x0a)[0],
            "planes": _planes(data, start, SAV_PLANES, n), "map_start": start,
            "seed": seed, "settlements": counts[18], "units": counts[28],
            "colonies": counts[202]}


def load(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:len(SAV_MAGIC)] == SAV_MAGIC:
        m = decode_sav(data)
    else:
        m = decode_mp(data)
    if m["width"] * m["height"] > MAX_SQUARES:
        raise MapError("%dx%d is %d squares; the DOS game refuses more than %d"
                       % (m["width"], m["height"], m["width"] * m["height"], MAX_SQUARES))
    return m

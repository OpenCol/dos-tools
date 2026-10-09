"""`map-preview`: a .MP or .SAV drawn by replaying the DOS game's own renderer.

There is no renderer of its own here. `render` walks the map the way
`GenerateTerrainMapRegion` (VICEROY.EXE overlay 21, file 0x685dc) walks a
region, and for every square does what `draw_square` (file 0x681a8) does, in
its order, with its masks and its arithmetic, onto one canvas:

    base tile       TERRAIN.SS, through `tile_index`: terrains 0-7 are tiles
                    0-7, 9 and 0x11 share tile 8, arctic/ocean/sea lane 9-11
    seams           for each of the 4 neighbours of another class, a mask icon
                    (0x69 + side), then the neighbour's tile drawn only into
                    pixels that are still 0 (`draw_seams`, file 0x67f50)
    forest          icon 0x41 + a 4-bit code of forested neighbours
                    (N 8, S 4, W 2, E 1)
    plowed          plane-1 bit 0x40 (MAP1_PLOWED): icon 0x96
    hills/mountains plane-0 bit 0x20: 0x21/0x31 + neighbour code
    rivers          plane-0 bit 0x40: 0x01/0x11 + neighbour code
    resources       `resource_at`: 0x5a + the terrain's bonus, from the seed
    rumours         `lost_city_at`: icon 0x68, from the seed, on unowned land
    roads           plane-1 bits 0x0a (MAP1_ROAD, MAP1_SETTLEMENT): 0x52 +
                    direction, 8 ways, or 0x51 alone
    coast           water with land around it: 4 corner pieces (0x6d + 4*code
                    + corner), or one of 4 whole-edge pieces (0x97..0x9a), then
                    the water tile drawn underneath, then the hills' shoreline
                    (0x8d/0x91 + side)
    hidden          icon 0x95, plus the seams of any visible neighbours

Icons come from PHYS0.SS, the sheet `pool_setup` loads as the map icons, and
are numbered from 1 as `draw_icon` numbers them. The colours are the first
0x300 bytes of VICEROY.PAL, the palette `game_main` loads.

The map's outer ring is drawn hidden, because `GenerateTerrainMapRegion`
treats squares on the edge as hidden whatever plane 3 says; the game's view
never shows that ring, but this draws the whole map.

What is NOT drawn: units and settlements. `draw_square` does not draw them --
another layer does -- and this module replays `draw_square` only.

The plane-1 names are the ones the Windows decomp established for the same
bits; the plane-0 ones (rivers, hills) are what the icons show. Either way
the code is the routine's, bit for bit.
"""
import os

from . import png as pnglib
from .formats import mapfile, ss
from .madspack import Madspack
from .palette import Palette, VGA_BYTES

TILE = 16
HIDDEN_ICON = 0x95
TERRAIN_BONUS_FILE = "VICEROY.EXE"
MAP1_SETTLEMENT = 0x02
MAP1_DEPLETED = 0x04

# Directions as the game tables them: g_dir_dx/dy (DS:0x00b4/0x00be), 8 ways
# clockwise from north; g_ortho_dx/dy (DS:0x00a8/0x00ae), N, E, S, W.
DIR_DX = (0, 1, 1, 1, 0, -1, -1, -1)
DIR_DY = (-1, -1, 0, 1, 1, 1, 0, -1)
ORTHO_DX = (0, 1, 0, -1)
ORTHO_DY = (-1, 0, 1, 0)


class MapviewError(Exception):
    pass


def tile_index(t):
    """`tile_index` (VICEROY.EXE file 0x3436)."""
    if t == 0x11 or t == 9:
        return 8
    if t >= 8:
        return t - 0x0F
    return t


def terrain_class(t, frame=0):
    """`dos_181f_06aa` (file 0x6204): the terrain a square shows in a map frame."""
    t &= 0x1F
    if frame == 2 and 8 <= t < 0x18:
        t = (t & 7) | 8
    elif frame == 3 and t < 0x18:
        t &= 7
    return t


def terrain_type(b):
    """`terrain_type` (file 0x624e)."""
    if b & 0x20:
        return 0x1B if b & 0x80 else 0x1C
    return b & 0x1F


class Art:
    """The tiles, the icons and the palette, read from a game directory."""

    def __init__(self, game_dir):
        def need(name):
            path = os.path.join(game_dir, name)
            if not os.path.exists(path):
                raise MapviewError("%s is not in %s -- is this the DOS game directory?"
                                   % (name, game_dir))
            return path

        icons = ss.Sheet(Madspack.load(need("PHYS0.SS")), "PHYS0.SS")
        self.icons = [None] + [(s.w, s.h, s.pixels()) for s in icons.sprites]
        terrain = ss.Sheet(Madspack.load(need("TERRAIN.SS")), "TERRAIN.SS")
        if len(terrain.sprites) < 12:
            raise MapviewError("TERRAIN.SS has %d sprites; the tile set needs 12"
                               % len(terrain.sprites))
        # `tiles_load` (file 0x72b9a) draws icons 1..12 into 12 fresh 16x16
        # blocks. The blocks are not cleared first, but every shipped terrain
        # sprite is a full opaque 16x16, so nothing of that memory shows.
        self.tiles = []
        for s in terrain.sprites[:12]:
            px = bytearray(TILE * TILE)
            _blit(px, TILE, TILE, s.w, s.h, s.pixels(), 0, 0)
            self.tiles.append(bytes(px))
        with open(need("VICEROY.PAL"), "rb") as f:
            self.palette = Palette.from_vga(f.read(VGA_BYTES), "VICEROY.PAL")
        self.bonus = _terrain_bonus(need(TERRAIN_BONUS_FILE))


# DGROUP's place in VICEROY.EXE: the 0x2400-byte MZ header, then paragraph
# 0x1b5a of the load image. Two of its literals pin it for the check below.
VICEROY_DGROUP = 0x2400 + 0x1B5A * 16
DGROUP_ANCHORS = ((0x2166, b"AMER2.MP\0"), (0x217A, b"COLONIZE\0"))
BONUS_AT = 0x0192
TERRAINS = 29


def _terrain_bonus(exe_path):
    """g_terrain_bonus (DS:0x0192): the prime-resource icon for each terrain.

    Read out of VICEROY.EXE's DGROUP rather than copied into this source, so
    the tool carries no game data. Refuses a build whose DGROUP is elsewhere.
    """
    with open(exe_path, "rb") as f:
        data = f.read()
    for at, lit in DGROUP_ANCHORS:
        o = VICEROY_DGROUP + at
        if data[o:o + len(lit)] != lit:
            raise MapviewError("%s: DS:%04x does not hold %r -- not the VICEROY.EXE "
                               "build this tool knows" % (exe_path, at, lit))
    off = VICEROY_DGROUP + BONUS_AT
    return [int.from_bytes(data[off + 2 * i:off + 2 * i + 2], "little", signed=True)
            for i in range(TERRAINS)]


def _blit(dst, dw, dh, w, h, px, x, y, under=False, mirror=False):
    """`draw_icon` / `draw_icon_under`: transparent is FD; `under` paints 0s only."""
    for r in range(h):
        yy = y + r
        if yy < 0 or yy >= dh:
            continue
        row = yy * dw
        src = r * w
        for c in range(w):
            v = px[src + c]
            if v == ss.TRANSPARENT:
                continue
            xx = x + c
            if xx < 0 or xx >= dw:
                continue
            if under and dst[row + xx] != 0:
                continue
            dst[row + xx] = v


def _keep(scale, n):
    """`draw_icon_scaled`'s table: which of n source lines survive."""
    acc, keep = 50, []
    for i in range(n):
        acc += scale
        if acc >= 100:
            keep.append(i)
            acc -= 100
    return keep


class Canvas:
    def __init__(self, art, cols, rows, zoom):
        self.art = art
        self.zoom = zoom
        self.tw = TILE >> zoom
        self.scale = 100 >> zoom
        self.w = cols * self.tw
        self.h = rows * self.tw
        self.px = bytearray(self.w * self.h)
        self.dx = 0                        # g_icon_dx / g_icon_dy
        self.dy = 0
        self.cx = 0                        # g_cur_px / g_cur_py
        self.cy = 0

    def icon(self, n, under=False):
        """`draw_map_icon` / `draw_map_icon2`."""
        if n <= 0 or n >= len(self.art.icons):
            return
        w, h, px = self.art.icons[n]
        if self.scale >= 100:
            _blit(self.px, self.w, self.h, w, h, px,
                  self.dx + self.cx - 8, self.dy + self.cy - 15, under)
            return
        kept = _keep(self.scale, max(w, h))
        cols = [i for i in kept if i < w]
        rows = [i for i in kept if i < h]
        x = self.cx - (len(cols) >> 1)
        y = self.cy - len(rows) + 1
        small = bytearray(len(cols) * len(rows))
        for j, r in enumerate(rows):
            for i, c in enumerate(cols):
                small[j * len(cols) + i] = px[r * w + c]
        _blit(self.px, self.w, self.h, len(cols), len(rows), small, x, y, under)

    def tile(self, t, under=False):
        """`draw_map_tile` / `draw_map_tile2` (dos_181f_025e/0268/0272/0286)."""
        src = self.art.tiles[tile_index(t)]
        if self.zoom == 0:
            x, y = self.dx + self.cx - 8, self.dy + self.cy - 15
            n, step, half = TILE, 1, 0
        else:
            n = TILE >> self.zoom
            step = 1 << self.zoom
            half = step >> 1
            x, y = self.cx - (n >> 1), self.cy - (n - 1)
        for r in range(n):
            yy = y + r
            if yy < 0 or yy >= self.h:
                continue
            for c in range(n):
                xx = x + c
                if xx < 0 or xx >= self.w:
                    continue
                o = yy * self.w + xx
                if under and self.px[o] != 0:
                    continue
                self.px[o] = src[(half + r * step) * TILE + half + c * step]


class Map:
    def __init__(self, m):
        self.w = m["width"]
        self.h = m["height"]
        self.p0, self.p1, self.p2, self.p3 = m["planes"]
        self.seed = m["seed"]

    def at(self, plane, off):
        # Edge squares read past their plane in the game; what they read
        # there is never used, but a Python index must stay in range.
        return plane[off] if 0 <= off < len(plane) else 0

    def on_map(self, x, y):
        return 1 <= x < self.w - 1 and 1 <= y < self.h - 1

    def map_get(self, x, y):
        return self.p0[y * self.w + x]

    def owner_of(self, x, y):
        n = self.p2[y * self.w + x] >> 4
        return -1 if n == 0xF else n

    def is_village(self, x, y):
        """`is_village` (file 0x5f82): a settlement owned by a tribe (4 and up)."""
        if not self.on_map(x, y):
            return False
        return bool(self.p1[y * self.w + x] & MAP1_SETTLEMENT) and self.owner_of(x, y) >= 4

    def terrain_at(self, x, y):
        return terrain_type(self.map_get(x, y)) if self.on_map(x, y) else 0x19


class Renderer:
    """One pass of `GenerateTerrainMapRegion` over the whole map."""

    def __init__(self, art, m, zoom=0, nation=None, scenery=True, frame=0):
        self.art = art
        self.m = Map(m)
        self.c = Canvas(art, self.m.w, self.m.h, zoom)
        self.zoom = zoom
        self.vis = 0 if nation is None else 1 << (nation + 4)
        self.seed = self.m.seed if scenery else 0
        self.frame = frame
        self.resources = 0
        self.rumours = 0

    # -- the map plane helpers (root_037f, overlay 21) ------------------- #

    def cls(self, t):
        return terrain_class(t, self.frame)

    def nb(self, plane, mask, maxzoom):
        """nb_mask_p0 / nb_mask_p1: N 8, S 4, W 2, E 1."""
        if self.zoom > maxzoom:
            return 0
        o, w, at = self.off, self.m.w, self.m.at
        n = 0
        if at(plane, o - w) & mask:
            n += 8
        if at(plane, o + w) & mask:
            n += 4
        if at(plane, o - 1) & mask:
            n += 2
        if at(plane, o + 1) & mask:
            n += 1
        return n

    def nb_match_p0(self, val, maxzoom):
        if self.zoom > maxzoom:
            return 0
        o, w, at, p = self.off, self.m.w, self.m.at, self.m.p0
        n = 0
        for d, bit in ((-w, 8), (w, 4), (-1, 2), (1, 1)):
            if at(p, o + d) & 0xA0 == val:
                n += bit
        return n

    def nb_land_seam(self, maxzoom):
        if self.zoom > maxzoom:
            return 0
        o, w = self.off, self.m.w
        n = 0
        for d, bit in ((-w, 8), (w, 4), (-1, 2), (1, 1)):
            t = self.m.at(self.m.p0, o + d) & 0x1F
            if t < 0x18 and (t & 7) != 1 and t > 7:
                n += bit
        return n

    def nb8_mask_p1(self, mask, maxzoom):
        if self.zoom > maxzoom:
            return 0
        res, bit = 0, 1
        for i in range(8):
            d = DIR_DX[i] + (0 if DIR_DY[i] == 0 else (-self.m.w if DIR_DY[i] < 0 else self.m.w))
            if self.m.at(self.m.p1, self.off + d) & mask:
                res |= bit
            bit <<= 1
        return res

    def dir_off(self, dx, dy):
        return dx + (-self.m.w if dy < 0 else 0) + (self.m.w if dy > 0 else 0)

    def coast_scan(self):
        self.coast_mask = 0
        count = 0
        self.corner = [0, 0, 0, 0]
        if self.zoom == 0:
            for i in range(8):
                ter = self.m.at(self.m.p0, self.off + self.dir_off(DIR_DX[i], DIR_DY[i])) & 0x1F
                if ter < 0x18:
                    ter &= 7
                c = self.cls(ter)
                if c in (0x19, 0x1A):
                    continue
                self.coast_mask |= 1 << i
                count += 1
                if i & 1:
                    self.corner[((i + 1) & 6) >> 1] |= 2
                else:
                    self.sq_terr = ter
                    j = i >> 1
                    self.corner[j] |= 4
                    self.corner[(j + 1) & 3] |= 1
        self.sq_class = self.cls(self.sq_terr)
        return count

    def resource_at(self, x, y):
        """`resource_at` (file 0x60a0). DOS hashes (x>>2) + (y>>2)*3."""
        if self.seed == 0:
            return -1
        if self.m.is_village(x, y):
            return -1
        terrain = self.m.map_get(x, y) & 0xFF3F
        forested = 1 if 8 <= terrain < 0x18 else 0
        nhash = ((y >> 2) * 3 + (x >> 2) - forested + self.seed) & 0xF
        h = ((x & 3) << 2) + (y & 3)
        if nhash != h and (nhash ^ 0xA) != h:
            return -1
        r = self.art.bonus[self.m.terrain_at(x, y)]
        if r == 0:
            r = 6
        if self.m.p1[y * self.m.w + x] & MAP1_DEPLETED:
            r = 0 if r == 12 else -1
        return r

    def lost_city_at(self, x, y):
        """`lost_city_at` (file 0x6188)."""
        if self.seed == 0:
            return False
        t = self.m.terrain_at(x, y)
        if t in (0x19, 0x1A, 0x18):
            return False
        if self.m.owner_of(x, y) >= 0:
            return False
        hsh = (y >> 2) * 19 + (x >> 2) * 17 + self.seed + 8
        return ((x & 3) << 2) + (y & 3) == (hsh & 0x1F)

    # -- draw_seams / draw_square ---------------------------------------- #

    def draw_seams(self, hidden_only, no_scan, always):
        c = self.c
        for i in range(4):
            dx, dy = ORTHO_DX[i], ORTHO_DY[i]
            nx, ny = dx + self.x, dy + self.y
            out = not self.m.on_map(nx, ny)
            off = self.off + self.dir_off(dx, dy)
            t = self.m.at(self.m.p0, off) & 0x1F
            if t < 0x18:
                t &= 7
            cls_i = self.cls(t)
            seen = self.m.at(self.m.p3, off)
            hid = (self.vis != 0 and not (self.vis & seen)) or out
            if hidden_only and hid:
                continue
            if cls_i in (0x19, 0x1A) and not no_scan:
                k = 7
                while cls_i in (0x19, 0x1A) and k >= 0:
                    sx, sy = DIR_DX[k] + nx, DIR_DY[k] + ny
                    if not (k & 1) and 0 <= sx < self.m.w and 0 <= sy < self.m.h:
                        tt = self.m.map_get(sx, sy) & 0x1F
                        if tt < 0x18:
                            tt &= 7
                        cls_i = self.cls(tt)
                    k -= 1
                if cls_i in (0x19, 0x1A):
                    continue
            if cls_i in (0x19, 0x1A) and not always and not hidden_only and not hid:
                continue
            cc = self.sq_class & 0x1F
            if cc < 0x18:
                cc &= 7
            cc = self.cls(cc)
            if cc == cls_i and not hidden_only and not hid:
                continue
            c.icon(i + 0x69)
            c.tile(cls_i, under=True)

    def draw_square(self, hidden):
        c, m, o = self.c, self.m, self.off
        count = 0
        self.sq_feat = m.at(m.p1, o)
        self.sq_terr = m.at(m.p0, o)
        site = m.at(m.p3, o)
        self.sq_class = self.cls(self.sq_terr)
        hide = (self.vis != 0 and not (site & self.vis)) or hidden
        hill = self.sq_terr & 0xC0
        if hide:
            c.icon(HIDDEN_ICON)
            if self.zoom != 0:
                return
            self.draw_seams(1, 1 if self.sq_class in (0x19, 0x1A) else 0, 0)
            return
        coastal = False
        water = 0x19
        if self.sq_class in (0x19, 0x1A):
            water = self.sq_class
            count = self.coast_scan()
            coastal = True
        if coastal and count == 0:
            c.tile(water)
            if self.zoom != 0:
                return
            self._resource()
            self.draw_seams(0, 1, 1)
            return
        base = self.sq_class & 7 if self.sq_class < 0x18 else self.sq_class
        forest = 8 <= self.sq_class < 0x18
        if base != 1 or not forest:
            c.tile(base)
        else:
            c.tile(0x11)
        if self.zoom == 0:
            self.draw_seams(0, 1 if coastal else 0, 0)
        if base != 1 and forest:
            c.icon(self.nb_land_seam(3) + 0x41)
        if self.sq_feat & 0x40:
            c.icon(0x96)
        if (self.sq_terr & 0x20) and not coastal:
            n = self.nb_match_p0(self.sq_terr & 0xA0, 2)
            c.icon(n + 0x21 if self.sq_terr & 0x80 else n + 0x31)
        if (self.sq_terr & 0x40) and not coastal:
            k = 1 if self.sq_terr & 0x80 else 0x11
            n = self.nb(m.p0, 0x40, 3)
            if n == 0:
                n = 0xF
            c.icon(k + n)
        if self.zoom == 0 and self.frame == 0:
            self._resource()
            if self.lost_city_at(self.x, self.y):
                c.icon(0x68)
                self.rumours += 1
        if (self.sq_feat & 0x0A) and not coastal and self.frame == 0:
            n = self.nb8_mask_p1(0x0A, 1)
            if n == 0:
                c.icon(0x51)
            else:
                for j in range(8):
                    if n & (1 << j):
                        c.icon(j + 0x52)
        if not coastal:
            return
        mf = -1
        cm = self.coast_mask
        if cm & 0xDD == 0xC1:
            mf = 0
        if cm & 0x77 == 0x07:
            mf = 1
        if cm & 0x77 == 0x70:
            mf = 2
        if cm & 0xDD == 0x1C:
            mf = 3
        if mf < 0:
            for i in range(4):
                k2 = (i + 1) & 3
                c.dx = (k2 >> 1) * 8
                c.dy = (i >> 1) * 8
                c.icon(self.corner[i] * 4 + i + 0x6D)
            c.dx = c.dy = 0
        else:
            c.dx = c.dy = 0
            c.icon(mf + 0x97)
        c.tile(water, under=True)
        if hill:
            k2 = 0x8D if hill & 0x80 else 0x91
            for i in range(4):
                ub = m.at(m.p0, o + self.dir_off(ORTHO_DX[i], ORTHO_DY[i]))
                if ub & 0x40 and self.cls(ub) not in (0x19, 0x1A):
                    c.icon(k2 + i)
        if self.zoom == 0:
            self._resource()

    def _resource(self):
        r = self.resource_at(self.x, self.y)
        if r != -1:
            self.c.icon(r + 0x5A)
            self.resources += 1

    def run(self):
        m, c = self.m, self.c
        tw = c.tw
        row_off = 1 * m.w + 1                           # map_loc(max(x, 1), max(y, 1))
        c.cy = tw - 1
        for y in range(m.h):
            self.y = y
            ey = 0 < y < m.h - 1
            off = row_off
            c.cx = (tw >> 1)
            for x in range(m.w):
                self.x = x
                ex = 0 < x < m.w - 1
                self.off = off
                self.draw_square(not ex or not ey)
                c.cx += tw
                if ex and ey:
                    off += 1
            c.cy += tw
            if ey:
                row_off += m.w
        return c


def render(m, art, zoom=0, nation=None, scenery=True):
    if not 0 <= zoom <= 3:
        raise MapviewError("zoom %d: the game's levels are 0-3 (16, 8, 4, 2 px a square)" % zoom)
    r = Renderer(art, m, zoom, nation, scenery)
    canvas = r.run()
    return canvas, r


def render_file(map_path, game_dir, out_path, zoom=0, nation=None, scenery=True, seed=None):
    m = mapfile.load(map_path)
    if seed is not None:
        m["seed"] = seed
        if m["kind"] == "MP":
            # A .MP's plane 2 has 0 in every owner nibble, which `lost_city_at`
            # reads as "owned by nation 0", so no rumour would ever show. Mark
            # every square unowned, as `clear_owners` (file 0x6892e) does --
            # which is what a game starting on the map must do, although the
            # call site that does it at the start of a game is not established.
            p2 = m["planes"][2]
            m["planes"][2] = bytes((b & 0x0F) | 0xF0 for b in p2)
    art = Art(game_dir)
    canvas, r = render(m, art, zoom, nation, scenery)
    pnglib.write_indexed(out_path, canvas.w, canvas.h, bytes(canvas.px),
                         art.palette.entries)
    info = dict(m)
    del info["planes"]
    info.update({"image": (canvas.w, canvas.h), "resources": r.resources,
                 "rumours": r.rumours, "tile": canvas.tw})
    return info

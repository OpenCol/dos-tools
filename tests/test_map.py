#!/usr/bin/env python3
"""Map files and the map preview.

    python3 tests/test_map.py /path/to/COLONIZE [/path/to/saves]

The format and arithmetic tests run without a game. With the game directory
the preview is rendered from the shipped art; with a directory of DOS saves
(COLONYnn.SAV, or $COLDOS_SAVES) every save's layout is checked to close.
"""
import hashlib
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coldos import mapview                                         # noqa: E402
from coldos.formats import mapfile, ss                             # noqa: E402
from coldos.madspack import Madspack                               # noqa: E402

GAME = os.environ.get("COLDOS_GAME")
SAVES = os.environ.get("COLDOS_SAVES")


def game_or_skip(t):
    if not GAME or not os.path.isdir(GAME):
        t.skipTest("set COLDOS_GAME (or pass the game directory) to run this")
    return GAME


def saves_or_skip(t):
    if not SAVES or not os.path.isdir(SAVES):
        t.skipTest("set COLDOS_SAVES (or pass a directory of DOS saves) to run this")
    found = sorted(f for f in os.listdir(SAVES) if f.upper().endswith(".SAV"))
    if not found:
        t.skipTest("no .SAV files in %s" % SAVES)
    return [os.path.join(SAVES, f) for f in found]


def fake_sav(w, h, s18=2, s28=3, s202=1, seed=0x1234):
    start = 3005 + 18 * s18 + 28 * s28 + 202 * s202
    data = bytearray(start + 4 * w * h + 1502)
    data[:10] = b"COLONIZE\0\x1a"
    struct.pack_into("<HHH", data, 0x0a, 73, w, h)
    struct.pack_into("<HHH", data, 0x2a, s18, s28, s202)
    struct.pack_into("<H", data, len(data) - 890, seed)
    return bytes(data), start


class MapFiles(unittest.TestCase):
    def test_mp_closes(self):
        data = struct.pack("<HHH", 4, 3, 4) + bytes(range(36))
        m = mapfile.decode_mp(data)
        self.assertEqual((m["width"], m["height"], m["version"]), (4, 3, 4))
        self.assertEqual(m["planes"][1], bytes(range(12, 24)))
        self.assertEqual(m["planes"][3], bytes(12))
        with self.assertRaises(mapfile.MapError):
            mapfile.decode_mp(data + b"\0")

    def test_sav_closes(self):
        data, start = fake_sav(10, 8)
        m = mapfile.decode_sav(data)
        self.assertEqual((m["map_start"], m["seed"]), (start, 0x1234))
        self.assertEqual(len(m["planes"]), 4)
        with self.assertRaises(mapfile.MapError):
            mapfile.decode_sav(data[:-1])


class RendererPieces(unittest.TestCase):
    def test_tile_index(self):
        self.assertEqual([mapview.tile_index(t) for t in (0, 7, 9, 0x11, 0x18, 0x19, 0x1a)],
                         [0, 7, 8, 8, 9, 10, 11])

    def test_terrain_class_frames(self):
        self.assertEqual(mapview.terrain_class(0x4b), 0x0b)
        self.assertEqual(mapview.terrain_class(0x13, 2), 0x0b)
        self.assertEqual(mapview.terrain_class(0x13, 3), 0x03)
        self.assertEqual(mapview.terrain_class(0x19, 3), 0x19)

    def test_scaled_icon_keeps(self):
        self.assertEqual(mapview._keep(100, 16), list(range(16)))
        self.assertEqual(len(mapview._keep(50, 16)), 8)
        self.assertEqual(len(mapview._keep(25, 16)), 4)
        self.assertEqual(mapview._keep(12, 16), [4, 12])


class Preview(unittest.TestCase):
    def test_tables_match_the_exe(self):
        """The direction constants are the game's own tables (DGROUP 0xa8-0xc5)."""
        game = game_or_skip(self)
        with open(os.path.join(game, "VICEROY.EXE"), "rb") as f:
            exe = f.read()
        d = mapview.VICEROY_DGROUP
        self.assertEqual(struct.unpack_from("<8b", exe, d + 0xb4), mapview.DIR_DX)
        self.assertEqual(struct.unpack_from("<8b", exe, d + 0xbe), mapview.DIR_DY)
        self.assertEqual(struct.unpack_from("<4b", exe, d + 0xa8), mapview.ORTHO_DX)
        self.assertEqual(struct.unpack_from("<4b", exe, d + 0xae), mapview.ORTHO_DY)

    def test_art(self):
        game = game_or_skip(self)
        art = mapview.Art(game)
        self.assertEqual(len(art.icons), 155)               # icon 0 is no sprite
        self.assertEqual(len(art.tiles), 12)
        self.assertEqual(len(art.bonus), 29)
        terrain = ss.Sheet(Madspack.load(os.path.join(game, "TERRAIN.SS")))
        for s in terrain.sprites:                           # the "nothing shows" claim
            self.assertEqual((s.w, s.h), (16, 16))
            self.assertNotIn(ss.TRANSPARENT, s.pixels())

    def test_amer2_at_every_zoom(self):
        game = game_or_skip(self)
        art = mapview.Art(game)
        m = mapfile.load(os.path.join(game, "AMER2.MP"))
        want = {0: (928, 1152, "4eafc583501a4dd5"), 1: (464, 576, "2fe17aee2e4b1433"),
                2: (232, 288, "ef69d7c52e9b6660"), 3: (116, 144, "74fba02eee8a8c32")}
        for z, (w, h, digest) in want.items():
            c, r = mapview.render(m, art, zoom=z)
            self.assertEqual((c.w, c.h), (w, h))
            self.assertEqual(hashlib.sha256(bytes(c.px)).hexdigest()[:16], digest, "zoom %d" % z)
            self.assertEqual((r.resources, r.rumours), (0, 0))

    def test_mp_with_a_seed(self):
        game = game_or_skip(self)
        out = tempfile.mktemp(suffix=".png")
        try:
            info = mapview.render_file(os.path.join(game, "AMER2.MP"), game, out, seed=1234)
            self.assertEqual((info["resources"], info["rumours"]), (443, 41))
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_saves(self):
        game = game_or_skip(self)
        art = mapview.Art(game)
        for path in saves_or_skip(self):
            m = mapfile.load(path)
            self.assertEqual(m["version"], 73, path)
            c, r = mapview.render(m, art)
            self.assertEqual((c.w, c.h), (16 * m["width"], 16 * m["height"]))
            seen, r2 = mapview.render(m, art, nation=0)
            self.assertNotEqual(bytes(seen.px), bytes(c.px), path)


def main():
    global GAME, SAVES
    argv = sys.argv[1:]
    if argv and os.path.isdir(argv[0]):
        GAME = argv.pop(0)
    if argv and os.path.isdir(argv[0]):
        SAVES = argv.pop(0)
    unittest.main(argv=[sys.argv[0]] + argv, verbosity=2)


if __name__ == "__main__":
    main()

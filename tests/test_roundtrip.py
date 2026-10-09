#!/usr/bin/env python3
"""End-to-end tests against a real copy of the game.

    python3 tests/test_roundtrip.py /path/to/COLONIZE

Nothing here is mocked: every asset assertion is made against the shipped
bytes. Without a game directory the codec tests still run on synthetic data
and the asset tests skip, so this is usable in CI where the game cannot be
shipped.
"""
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coldos import fab, png as pnglib                               # noqa: E402
from coldos.formats import ff, pik, ss, text                         # noqa: E402
from coldos.madspack import Madspack, Entry, is_madspack, HEAD       # noqa: E402
from coldos.palette import Palette, widen, narrow                    # noqa: E402
from coldos.workspace import Workspace, WorkspaceError               # noqa: E402

GAME = os.environ.get("COLDOS_GAME")
_ws_cache = {}


def game_or_skip(t):
    if not GAME or not os.path.isdir(GAME):
        t.skipTest("set COLDOS_GAME (or pass the game directory) to run this")
    return GAME


def madspack_files(game):
    out = []
    for f in sorted(os.listdir(game)):
        p = os.path.join(game, f)
        with open(p, "rb") as fh:
            data = fh.read()
        if is_madspack(data):
            out.append((f, data))
    return out


# --------------------------------------------------------------------------- #
# codecs, synthetic

class FabCodec(unittest.TestCase):
    def test_round_trip_over_shapes(self):
        random.seed(5)
        for data in (b"", b"a", b"ab" * 3, bytes(70000),
                     bytes(random.randrange(256) for _ in range(9000)),
                     bytes(random.choice(b"\x00\x01\xfd") for _ in range(50000)),
                     bytes((i * 7 // 3) & 0xFF for i in range(66000)),
                     b"".join(bytes([i]) * (i + 1) for i in range(256))):
            packed = fab.compress(data)
            out, used = fab.decompress(packed, len(data))
            self.assertEqual(out, data, "len %d" % len(data))
            self.assertEqual(used, len(packed))

    def test_word_fetch_before_token_bytes(self):
        """The 16th flag bit puts the next word ahead of that token's data."""
        data = bytes(range(40))                     # 40 literals: 2.5 flag words
        packed = fab.compress(data)
        self.assertEqual(fab.decompress(packed, 40)[0], data)
        # word 0, 16 literal bytes... the second word sits after 15 of them
        self.assertEqual(packed[6:6 + 15], data[:15])

    def test_refuses_garbage(self):
        with self.assertRaises(fab.FabError):
            fab.decompress(b"XYZ\x0c\0\0", 1)
        with self.assertRaises(fab.FabError):
            fab.decompress(fab.compress(b"abc"), 4)


class SpriteCodec(unittest.TestCase):
    T = ss.TRANSPARENT

    def round_trip(self, px, w, h):
        rle = ss.encode_sprite(px, w, h)
        self.assertEqual(ss.decode_sprite(rle, w, h), bytes(px))
        return rle

    def test_shapes(self):
        T = self.T
        self.assertEqual(self.round_trip(bytes([T]) * 12, 4, 3), b"\xff\xff\xff\xfc")
        self.assertEqual(self.round_trip(b"\x05" * 4, 4, 1), b"\xfd\x04\x05\xff\xfc")
        self.assertEqual(self.round_trip(b"\x01\x02\x03", 3, 1), b"\xfe\x01\x02\x03\xff\xfc")
        self.round_trip(bytes([1, T, T, 2, 2, 2, 2, 2, T]) * 3, 9, 3)
        self.round_trip(bytes([7]) * 600, 600, 1)                 # runs split at 252
        random.seed(3)
        self.round_trip(bytes(random.choice([0, 1, 2, T, 0xFC]) for _ in range(40 * 30)), 40, 30)

    def test_trailing_transparency_is_cut(self):
        self.assertEqual(ss.encode_sprite(bytes([1, 2, self.T, self.T]), 4, 1),
                         b"\xfe\x01\x02\xff\xfc")

    def test_index_255_is_refused(self):
        with self.assertRaises(ss.SheetError):
            ss.encode_sprite(b"\x01\xff", 2, 1)


class FontCodec(unittest.TestCase):
    def test_glyph_round_trip(self):
        random.seed(9)
        for w in (1, 3, 4, 5, 8, 9, 13, 16):
            px = bytes(random.randrange(4) for _ in range(w * 7))
            self.assertEqual(ff.decode_glyph(ff.encode_glyph(px, w, 7), w, 7), px)
            self.assertEqual(len(ff.encode_glyph(px, w, 7)), 7 * ((w + 3) // 4))


class Containers(unittest.TestCase):
    def test_build_and_parse(self):
        head = bytearray(HEAD)
        head[:13] = b"MADSPACK 2.0\x1a"
        head[0x40:0x48] = b"slackXYZ"
        pack = Madspack(bytes(head), [Entry(1, 0x07, 0, b""), Entry(0, 0x07, 0, b"")], b"tail")
        pack.replace(0, b"hello hello hello")
        pack.replace(1, b"stored")
        data = pack.to_bytes()
        back = Madspack.parse(data)
        self.assertEqual([e.data for e in back.entries], [b"hello hello hello", b"stored"])
        self.assertEqual(back.trailing, b"tail")
        self.assertEqual(back.head[0x40:0x48], b"slackXYZ")
        self.assertEqual(back.to_bytes(), data)


class Palettes(unittest.TestCase):
    def test_six_bit_round_trip(self):
        self.assertEqual([narrow(widen(v)) for v in range(64)], list(range(64)))
        self.assertEqual((widen(0), widen(63)), (0, 255))

    def test_uniquify_makes_an_inverse(self):
        p = Palette([(0, 0, 0)] * 256)
        p.uniquify()
        self.assertEqual(len(set(p.entries)), 256)
        self.assertEqual(p.inverse()[p.entries[200]], 200)


class Text(unittest.TestCase):
    def test_every_byte_round_trips(self):
        data = bytes(range(256))
        self.assertEqual(text.from_utf8(text.to_utf8(data)), data)

    def test_outside_cp437_is_refused(self):
        with self.assertRaises(text.TextError):
            text.from_utf8("café €".encode("utf-8"))


# --------------------------------------------------------------------------- #
# the shipped files

class ShippedFiles(unittest.TestCase):
    def test_every_container_closes_and_rebuilds(self):
        game = game_or_skip(self)
        files = madspack_files(game)
        self.assertEqual(len(files), 246)
        trailing = 0
        for name, data in files:
            pack = Madspack.parse(data, name)
            for e in pack.entries:
                self.assertEqual(len(e.data), e.size, name)
            self.assertEqual(pack.to_bytes(), data, name)
            trailing += bool(pack.trailing)
        self.assertEqual(trailing, 4)

    def test_fab_streams(self):
        """Every type-1 entry: decodes exactly, and our packer's output decodes the same."""
        game = game_or_skip(self)
        n = exact = 0
        for name, data in madspack_files(game):
            for e in Madspack.parse(data, name).entries:
                if e.type != 1:
                    continue
                self.assertEqual(e.raw[3], 12, name)
                packed = fab.compress(e.data)
                self.assertEqual(fab.decompress(packed, e.size)[0], e.data, name)
                n += 1
                exact += packed == e.raw
        self.assertEqual(n, 793)
        self.assertEqual(exact, 479)

    def test_every_sprite_reencodes_byte_for_byte(self):
        game = game_or_skip(self)
        n = empty = 0
        for name, data in madspack_files(game):
            if not name.endswith(".SS"):
                continue
            sheet = ss.Sheet(Madspack.parse(data, name), name)
            for s in sheet.sprites:
                self.assertEqual(ss.encode_sprite(s.pixels(), s.w, s.h), s.rle,
                                 "%s sprite" % name)
                n += 1
                empty += s.w * s.h == 0
            self.assertEqual(sheet.rebuild().to_bytes(), data, name)
        self.assertEqual((n, empty), (1517, 19))

    def test_pictures(self):
        game = game_or_skip(self)
        sizes = {}
        for name, data in madspack_files(game):
            if name.endswith(".PIK"):
                p = pik.Picture(Madspack.parse(data, name), name)
                self.assertEqual(struct.unpack_from("<H", p.header, 4)[0], 0, name)
                sizes[name] = (p.width, p.height, p.palette is not None)
        self.assertEqual(len(sizes), 35)
        self.assertEqual(sizes["COLONY.PIK"], (320, 72, False))
        self.assertEqual(sizes["OPENING.PIK"], (960, 132, True))
        self.assertEqual(sum(1 for v in sizes.values() if v == (320, 200, True)), 33)

    def test_fonts_close_and_reencode(self):
        game = game_or_skip(self)
        for name, data in madspack_files(game):
            if not name.endswith(".FF"):
                continue
            raw = Madspack.parse(data, name).entries[0].data
            font = ff.Font(raw, name)
            self.assertEqual(font.max_width, max(font.widths), name)
            self.assertEqual(font.to_bytes(), raw, name)
            self.assertEqual(font.glyphs[31], bytes(font.height * font.widths[31]), name)


class WorkspaceRoundTrip(unittest.TestCase):
    def workspace(self, game):
        if game not in _ws_cache:
            tmp = tempfile.mkdtemp(prefix="coldos-test-")
            self.addCleanup(lambda: None)
            ws, counts = Workspace.extract(game, os.path.join(tmp, "ws"), log=lambda *a: None)
            _ws_cache[game] = (tmp, ws, counts)
        return _ws_cache[game]

    def test_extract_counts_and_verify(self):
        game = game_or_skip(self)
        tmp, ws, counts = self.workspace(game)
        self.assertEqual(counts, {"ss": 206, "pik": 35, "ff": 5, "pal": 1, "text": 20})
        same, total, tally, failures = ws.verify(game)
        self.assertEqual((same, total, failures), (267, 267, []))
        self.assertTrue(all(t["exact"] and not t["fail"] for t in tally.values()))

    def test_an_edit_lands_and_nothing_else_moves(self):
        game = game_or_skip(self)
        tmp = tempfile.mkdtemp(prefix="coldos-edit-")
        try:
            ws, _ = Workspace.extract(game, os.path.join(tmp, "ws"), log=lambda *a: None)
            p = ws.path("sprites/TERRAIN/004.png")
            img = pnglib.read(p)
            px = bytearray(img["pixels"])
            px[:16] = b"\x0f" * 16
            pnglib.write_indexed(p, img["width"], img["height"], bytes(px), img["palette"],
                                 transparent=ss.TRANSPARENT)
            self.assertEqual([c[0] for c in ws.changed()], ["TERRAIN.SS"])
            out = os.path.join(tmp, "out")
            written = ws.build(out, game, changed_only=True, log=lambda *a: None)
            self.assertEqual(written, ["TERRAIN.SS"])
            new = ss.Sheet(Madspack.load(os.path.join(out, "TERRAIN.SS")))
            old = ss.Sheet(Madspack.load(os.path.join(game, "TERRAIN.SS")))
            self.assertEqual(new.sprites[4].pixels()[:16], b"\x0f" * 16)
            self.assertEqual(new.sprites[4].pixels()[16:], old.sprites[4].pixels()[16:])
            for i in range(12):
                if i != 4:
                    self.assertEqual(new.sprites[i].rle, old.sprites[i].rle)
            self.assertEqual(new.pack.entries[2].raw, old.pack.entries[2].raw)
        finally:
            shutil.rmtree(tmp)

    def test_truecolour_edit_maps_back_exactly(self):
        game = game_or_skip(self)
        tmp = tempfile.mkdtemp(prefix="coldos-rgb-")
        try:
            ws, _ = Workspace.extract(game, os.path.join(tmp, "ws"), log=lambda *a: None)
            p = ws.path("sprites/ICONS/010.png")
            img = pnglib.read(p)
            rgba = bytearray()
            for v in img["pixels"]:
                rgba += bytes(img["palette"][v]) + (b"\x00" if v == ss.TRANSPARENT else b"\xff")
            pnglib.write_rgba(p, img["width"], img["height"], bytes(rgba))
            with open(os.path.join(game, "ICONS.SS"), "rb") as f:
                self.assertEqual(ws.encode("ICONS.SS", game), f.read())
            absent = next(c for c in ((7, 250, 9), (250, 7, 9), (9, 7, 250))
                          if c not in [tuple(e) for e in img["palette"]])
            k = next(i for i, v in enumerate(img["pixels"]) if v != ss.TRANSPARENT)
            rgba[4 * k:4 * k + 4] = bytes(absent) + b"\xff"
            pnglib.write_rgba(p, img["width"], img["height"], bytes(rgba))
            with self.assertRaises(WorkspaceError):
                ws.encode("ICONS.SS", game)
            ws.encode("ICONS.SS", game, nearest=True)
        finally:
            shutil.rmtree(tmp)

    def test_resizing_a_sprite_is_refused(self):
        game = game_or_skip(self)
        tmp = tempfile.mkdtemp(prefix="coldos-size-")
        try:
            ws, _ = Workspace.extract(game, os.path.join(tmp, "ws"), log=lambda *a: None)
            p = ws.path("sprites/TERRAIN/000.png")
            img = pnglib.read(p)
            pnglib.write_indexed(p, 8, 8, bytes(64), img["palette"])
            with self.assertRaises(WorkspaceError) as cm:
                ws.encode("TERRAIN.SS", game)
            self.assertIn("must stay 16x16", str(cm.exception))
        finally:
            shutil.rmtree(tmp)

    def test_glyph_width_and_slots(self):
        game = game_or_skip(self)
        tmp = tempfile.mkdtemp(prefix="coldos-font-")
        try:
            ws, _ = Workspace.extract(game, os.path.join(tmp, "ws"), log=lambda *a: None)
            a = ws.path("fonts/FONTINTR/064.png")
            img = pnglib.read(a)
            w, h = img["width"], img["height"]
            wide = b"".join(img["pixels"][y * w:(y + 1) * w] + b"\x03" for y in range(h))
            pnglib.write_indexed(a, w + 1, h, wide, img["palette"])
            os.remove(ws.path("fonts/FONTINTR/065.png"))                     # empty "B"
            shutil.copy(ws.path("fonts/FONTINTR/066.png"), ws.path("fonts/FONTINTR/000.png"))
            data = ws.encode("FONTINTR.FF", game)
            font = ff.Font(Madspack.parse(data).entries[0].data)
            with open(os.path.join(game, "FONTINTR.FF"), "rb") as f:
                old = ff.Font(Madspack.parse(f.read()).entries[0].data)
            self.assertEqual((font.widths[64], font.widths[65], font.widths[0]),
                             (w + 1, 0, old.widths[66]))
            self.assertEqual(font.glyphs[0], old.glyphs[66])
            self.assertEqual(font.glyphs[64], wide)
        finally:
            shutil.rmtree(tmp)


def main():
    global GAME
    argv = sys.argv[1:]
    if argv and os.path.isdir(argv[0]):
        GAME = argv.pop(0)
    unittest.main(argv=[sys.argv[0]] + argv, verbosity=2)


if __name__ == "__main__":
    main()

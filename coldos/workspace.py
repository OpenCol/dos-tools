"""The workspace: a directory of editable files, and the way back to the game.

    sprites/<SHEET>/<nnn>.png    one per sprite of every .SS (sprite nnn is icon
                                 nnn + 1 in the game's code); index 253 is
                                 transparent
    pictures/<NAME>.png          every .PIK
    fonts/<FONT>/<nnn>.png       one per glyph; slot nnn draws character nnn + 1;
                                 the PNG's width is the glyph's width
    palettes/<NAME>.pal          every stored palette, JASC format, 8-bit values
    text/<NAME>                  the .TXT and .DB files, as UTF-8
    coldos.json                  the manifest

`coldos.json` records, for every file written, where it came from and the
SHA-256 of what was written, plus the SHA-256 of each source file. On `build`
a source none of whose files changed is copied byte for byte from the game,
and inside a changed source only the changed parts are re-encoded: a sheet
with one edited sprite keeps every other sprite's RLE, and its other entries
keep their packed bytes. So an untouched workspace rebuilds every file
identically, and that is what `verify` checks first.

The PNGs are indexed, and their pixel values are the game's bytes. A PNG
that comes back indexed is read by index when its palette is still the one
extract wrote; otherwise -- a paint program that reordered the palette, or
saved truecolour -- each colour is looked up in that same view palette, which
is injective, so the lookup is exact. A colour that is not in it is refused
unless `--nearest` is given.
"""
import datetime
import hashlib
import json
import os
import shutil

from . import __version__, png as pnglib
from .formats import ff, pik, ss, text
from .madspack import Madspack, is_madspack
from .palette import Palette, VGA_BYTES, view

MANIFEST = "coldos.json"
TEXT_EXT = (".TXT", ".DB")
GAME_PALETTE = "VICEROY.PAL"
FONT_VIEW = [(255, 255, 255), (0, 0, 0), (96, 96, 96), (176, 176, 176)]


class WorkspaceError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    with open(path, "rb") as f:
        return sha256(f.read())


def kind_of(name, data):
    up = name.upper()
    if is_madspack(data):
        if up.endswith(".SS"):
            return "ss"
        if up.endswith(".PIK"):
            return "pik"
        if up.endswith(".FF"):
            return "ff"
        return None
    if up == GAME_PALETTE:
        return "pal"
    if up.endswith(TEXT_EXT):
        return "text"
    return None


def game_files(game_dir):
    if not os.path.isdir(game_dir):
        raise WorkspaceError("%s is not a directory" % game_dir)
    names = sorted(f for f in os.listdir(game_dir) if os.path.isfile(os.path.join(game_dir, f)))
    if GAME_PALETTE not in names and GAME_PALETTE.lower() not in [n.lower() for n in names]:
        raise WorkspaceError("%s has no VICEROY.PAL -- is this the DOS game directory "
                             "(the one with VICEROY.EXE)?" % game_dir)
    return names


def own_palette(data):
    """A stored palette entry is a VGA palette when it is 0x300 bytes."""
    return data is not None and len(data) == VGA_BYTES


# --------------------------------------------------------------------------- #
# reading an edited PNG back to indices

def png_indices(path, w, h, pal, transparent=None, nearest=False):
    """The w*h indices a PNG holds, read through view palette `pal`."""
    img = pnglib.read(path)
    if (img["width"], img["height"]) != (w, h):
        raise WorkspaceError("%s is %dx%d; it must stay %dx%d (resizing is not "
                             "supported: the game's records fix the size)"
                             % (path, img["width"], img["height"], w, h))
    if img["mode"] == "P":
        plte = img["palette"]
        used = set(img["pixels"])
        if all(i < len(plte) and tuple(plte[i]) == pal.entries[i] for i in used):
            return img["pixels"]
        trns = img["trns"]
        lut = {}
        for i in used:
            if i >= len(plte):
                raise WorkspaceError("%s: pixel index %d is outside its own palette" % (path, i))
            if transparent is not None and i < len(trns) and trns[i] < 128:
                lut[i] = transparent
            else:
                lut[i] = _lookup(path, tuple(plte[i]), pal, nearest)
        return bytes(lut[i] for i in img["pixels"])
    px = img["pixels"]
    out = bytearray(w * h)
    cache = {}
    for k in range(w * h):
        r, g, b, a = px[4 * k:4 * k + 4]
        if transparent is not None and a < 128:
            out[k] = transparent
            continue
        c = (r, g, b)
        if c not in cache:
            cache[c] = _lookup(path, c, pal, nearest)
        out[k] = cache[c]
    return bytes(out)


def _lookup(path, rgb, pal, nearest):
    i = pal.inverse().get(rgb)
    if i is None:
        if not nearest:
            raise WorkspaceError("%s: colour #%02x%02x%02x is not in its palette; repaint "
                                 "with the palette's colours, or build with --nearest"
                                 % ((path,) + rgb))
        i = pal.nearest(rgb)
    return i


# --------------------------------------------------------------------------- #

class Workspace:
    def __init__(self, root, manifest):
        self.root = root
        self.m = manifest

    def path(self, rel):
        return os.path.join(self.root, rel)

    @classmethod
    def open(cls, root):
        p = os.path.join(root, MANIFEST)
        if not os.path.exists(p):
            raise WorkspaceError("%s: no %s here -- run `coldos extract` first" % (root, MANIFEST))
        with open(p) as f:
            return cls(root, json.load(f))

    def save(self):
        with open(self.path(MANIFEST), "w") as f:
            json.dump(self.m, f, indent=1)

    # -- extract ---------------------------------------------------------- #

    @classmethod
    def extract(cls, game_dir, root, log=print):
        names = game_files(game_dir)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(game_dir, _actual(names, GAME_PALETTE)), "rb") as f:
            game_pal = Palette.from_vga(f.read(VGA_BYTES), GAME_PALETTE)
        ws = cls(root, {
            "coldos_version": __version__,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "game_dir": os.path.abspath(game_dir),
            "sources": {},
        })
        counts = {}
        for name in names:
            with open(os.path.join(game_dir, name), "rb") as f:
                data = f.read()
            kind = kind_of(name, data)
            if kind is None:
                continue
            outs = getattr(ws, "_extract_" + kind)(name, data, game_pal)
            ws.m["sources"][name] = {"kind": kind, "sha256": sha256(data), "files": outs}
            counts[kind] = counts.get(kind, 0) + 1
        ws.save()
        _write_readme(root)
        return ws, counts

    def _record(self, rel, **info):
        info["file"] = rel
        info["sha256"] = file_sha256(self.path(rel))
        return info

    def _mkdir(self, rel):
        os.makedirs(self.path(rel), exist_ok=True)

    def _write_pal(self, stem, data):
        rel = "palettes/%s.pal" % stem
        self._mkdir("palettes")
        Palette.from_vga(data, stem).write_jasc(self.path(rel))
        return self._record(rel, part="palette")

    def _extract_ss(self, name, data, game_pal):
        stem = os.path.splitext(name)[0]
        sheet = ss.Sheet(Madspack.parse(data, name), name)
        pal = Palette.from_vga(sheet.palette) if own_palette(sheet.palette) else game_pal
        v = view(pal)
        outs = []
        self._mkdir("sprites/" + stem)
        for i, s in enumerate(sheet.sprites):
            if s.w == 0 or s.h == 0:
                continue                         # 19 shipped sprites are 0x0
            rel = "sprites/%s/%03d.png" % (stem, i)
            pnglib.write_indexed(self.path(rel), s.w, s.h, s.pixels(), v.entries,
                                 transparent=ss.TRANSPARENT)
            outs.append(self._record(rel, part="sprite", index=i))
        if own_palette(sheet.palette):
            outs.append(self._write_pal(stem, sheet.palette))
        return outs

    def _extract_pik(self, name, data, game_pal):
        stem = os.path.splitext(name)[0]
        pic = pik.Picture(Madspack.parse(data, name), name)
        pal = Palette.from_vga(pic.palette) if own_palette(pic.palette) else game_pal
        rel = "pictures/%s.png" % stem
        self._mkdir("pictures")
        pnglib.write_indexed(self.path(rel), pic.width, pic.height, pic.pixels, view(pal).entries)
        outs = [self._record(rel, part="picture")]
        if own_palette(pic.palette):
            outs.append(self._write_pal(stem, pic.palette))
        return outs

    def _extract_ff(self, name, data, game_pal):
        stem = os.path.splitext(name)[0]
        font = ff.Font(Madspack.parse(data, name).entries[0].data, name)
        self._mkdir("fonts/" + stem)
        outs = []
        for s in range(ff.SLOTS):
            w = font.widths[s]
            if w == 0:
                continue
            rel = "fonts/%s/%03d.png" % (stem, s)
            pnglib.write_indexed(self.path(rel), w, font.height, font.glyphs[s], FONT_VIEW)
            outs.append(self._record(rel, part="glyph", index=s))
        return outs

    def _extract_pal(self, name, data, game_pal):
        return [self._write_pal(os.path.splitext(name)[0], data[:VGA_BYTES])]

    def _extract_text(self, name, data, game_pal):
        rel = "text/" + name
        self._mkdir("text")
        with open(self.path(rel), "wb") as f:
            f.write(text.to_utf8(data))
        return [self._record(rel, part="text")]

    # -- status ----------------------------------------------------------- #

    def changed(self):
        """[(source, record, why)] for every written file that differs."""
        out = []
        for name, src in sorted(self.m["sources"].items()):
            for rec in src["files"]:
                p = self.path(rec["file"])
                if not os.path.exists(p):
                    why = "missing"
                elif file_sha256(p) != rec["sha256"]:
                    why = "edited"
                else:
                    continue
                out.append((name, rec, why))
        for name, rel in self.added_glyphs():
            out.append((name, {"file": rel}, "added"))
        return out

    def added_glyphs(self):
        """Glyph PNGs dropped into a slot that shipped empty."""
        out = []
        for name, src in sorted(self.m["sources"].items()):
            if src["kind"] != "ff":
                continue
            stem = os.path.splitext(name)[0]
            known = {r["file"] for r in src["files"]}
            d = self.path("fonts/" + stem)
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                rel = "fonts/%s/%s" % (stem, f)
                if f.endswith(".png") and f[:3].isdigit() and rel not in known:
                    out.append((name, rel))
        return out

    # -- encoding one source ---------------------------------------------- #

    def encode(self, name, game_dir, force=False, nearest=False):
        """The bytes `name` should have, given the workspace.

        Only files that changed are read back (all of them with `force`, which
        is what `verify` uses to put every file through the encoders).
        """
        src = self.m["sources"][name]
        with open(os.path.join(game_dir, name), "rb") as f:
            orig = f.read()
        if sha256(orig) != src["sha256"]:
            raise WorkspaceError("%s in %s is not the file this workspace was extracted "
                                 "from" % (name, game_dir))
        dirty = {r["file"] for r in src["files"]
                 if force or not os.path.exists(self.path(r["file"]))
                 or file_sha256(self.path(r["file"])) != r["sha256"]}
        added = [rel for n, rel in self.added_glyphs() if n == name]
        if not dirty and not added:
            return orig
        for rel in dirty:
            if not os.path.exists(self.path(rel)) and not rel.startswith("fonts/"):
                raise WorkspaceError("%s is missing; restore it or re-extract (only a "
                                     "glyph can be deleted, which empties its slot)" % rel)
        return getattr(self, "_encode_" + src["kind"])(name, orig, src, dirty, nearest, game_dir)

    def _read_pal(self, rel):
        """The 0x300 VGA bytes of an edited .pal."""
        return Palette.read_jasc(self.path(rel)).vga_bytes()

    def _encode_ss(self, name, orig, src, dirty, nearest, game_dir):
        sheet = ss.Sheet(Madspack.parse(orig, name), name)
        pal = Palette.from_vga(sheet.palette) if own_palette(sheet.palette) \
            else _game_palette(game_dir)
        v = view(pal)
        for rec in src["files"]:
            if rec["file"] not in dirty:
                continue
            if rec["part"] == "sprite":
                s = sheet.sprites[rec["index"]]
                px = png_indices(self.path(rec["file"]), s.w, s.h, v, ss.TRANSPARENT, nearest)
                s.rle = ss.encode_sprite(px, s.w, s.h)
            elif rec["part"] == "palette":
                sheet.palette = self._read_pal(rec["file"])
        return sheet.rebuild().to_bytes()

    def _encode_pik(self, name, orig, src, dirty, nearest, game_dir):
        pic = pik.Picture(Madspack.parse(orig, name), name)
        pal = Palette.from_vga(pic.palette) if own_palette(pic.palette) \
            else _game_palette(game_dir)
        pixels = palette = None
        for rec in src["files"]:
            if rec["file"] not in dirty:
                continue
            if rec["part"] == "picture":
                pixels = png_indices(self.path(rec["file"]), pic.width, pic.height,
                                     view(pal), None, nearest)
            elif rec["part"] == "palette":
                palette = self._read_pal(rec["file"])
        return pic.rebuild(pixels, palette).to_bytes()

    def _encode_ff(self, name, orig, src, dirty, nearest, game_dir):
        pack = Madspack.parse(orig, name)
        font = ff.Font(pack.entries[0].data, name)
        stem = os.path.splitext(name)[0]
        slots = set(r["index"] for r in src["files"] if r["file"] in dirty)
        slots |= set(int(os.path.basename(rel)[:3]) for n, rel in self.added_glyphs() if n == name)
        for s in sorted(slots):
            if s >= ff.SLOTS:
                raise WorkspaceError("fonts/%s/%03d.png: a font has slots 0-127" % (stem, s))
            rel = "fonts/%s/%03d.png" % (stem, s)
            if not os.path.exists(self.path(rel)):
                font.widths[s] = 0                 # deleting a glyph empties its slot
                font.glyphs[s] = b""
                continue
            img = pnglib.read(self.path(rel))
            if img["height"] != font.height:
                raise WorkspaceError("%s is %d pixels high; every glyph of %s is %d"
                                     % (rel, img["height"], name, font.height))
            w = img["width"]
            if w > 255:
                raise WorkspaceError("%s: a glyph width is one byte" % rel)
            font.widths[s] = w
            font.glyphs[s] = png_indices(self.path(rel), w, font.height, _font_palette(),
                                         None, nearest)
            if max(font.glyphs[s] or b"\0") > 3:
                raise WorkspaceError("%s uses palette index %d; a glyph pixel is 0-3"
                                     % (rel, max(font.glyphs[s])))
        data = font.to_bytes()
        if data != pack.entries[0].data:
            pack.replace(0, data)
        return pack.to_bytes()

    def _encode_pal(self, name, orig, src, dirty, nearest, game_dir):
        rec = src["files"][0]
        return self._read_pal(rec["file"]) + orig[VGA_BYTES:]

    def _encode_text(self, name, orig, src, dirty, nearest, game_dir):
        rec = src["files"][0]
        with open(self.path(rec["file"]), "rb") as f:
            return text.from_utf8(f.read(), rec["file"])

    # -- build ------------------------------------------------------------ #

    def build(self, out_dir, game_dir=None, nearest=False, changed_only=False, log=print):
        game_dir = game_dir or self.m["game_dir"]
        if os.path.abspath(out_dir) == os.path.abspath(game_dir):
            raise WorkspaceError("refusing to build over the game itself; pick another --out")
        os.makedirs(out_dir, exist_ok=True)
        written = []
        for name in sorted(self.m["sources"]):
            data = self.encode(name, game_dir, nearest=nearest)
            with open(os.path.join(game_dir, name), "rb") as f:
                same = f.read() == data
            if same and changed_only:
                continue
            with open(os.path.join(out_dir, name), "wb") as f:
                f.write(data)
            if not same:
                written.append(name)
                log("rebuilt %s" % name)
        if not changed_only:
            for f in os.listdir(game_dir):
                p = os.path.join(game_dir, f)
                if f in self.m["sources"] or not os.path.isfile(p):
                    continue
                shutil.copyfile(p, os.path.join(out_dir, f))
        return written

    # -- verify ----------------------------------------------------------- #

    def verify(self, game_dir=None, repack=False):
        """Two checks, both against the game's own bytes.

        1. An untouched workspace rebuilds every source identically.
        2. Forcing every extracted file back through its encoder -- the path an
           edit takes -- gives the same bytes. With `repack`, every entry is
           also packed again, which an edit only does to the entries it
           changes; FAB does not reproduce the shipped packer everywhere, so
           there the check is the same content.
        """
        game_dir = game_dir or self.m["game_dir"]
        same, failures, tally = 0, [], {}
        for name in sorted(self.m["sources"]):
            src = self.m["sources"][name]
            with open(os.path.join(game_dir, name), "rb") as f:
                orig = f.read()
            if self.encode(name, game_dir) == orig:
                same += 1
            else:
                failures.append((name, "untouched rebuild differs"))
            t = tally.setdefault(src["kind"], {"exact": 0, "content": 0, "fail": 0})
            try:
                got = self.encode(name, game_dir, force=True)
                if repack and is_madspack(got):
                    pack = Madspack.parse(got, name)
                    for i, e in enumerate(pack.entries):
                        pack.replace(i, e.data)
                    got = pack.to_bytes()
            except Exception as e:                # noqa: BLE001 -- report, keep going
                t["fail"] += 1
                failures.append((name, "%s: %s" % (type(e).__name__, e)))
                continue
            if got == orig:
                t["exact"] += 1
            elif _same_content(name, got, orig):
                t["content"] += 1
            else:
                t["fail"] += 1
                failures.append((name, "re-encoded content differs"))
        return same, len(self.m["sources"]), tally, failures


def _same_content(name, a, b):
    """Same entries once unpacked, same header slack and trailing bytes."""
    if not (is_madspack(a) and is_madspack(b)):
        return False
    pa, pb = Madspack.parse(a, name), Madspack.parse(b, name)
    if len(pa.entries) != len(pb.entries) or pa.trailing != pb.trailing:
        return False
    if pa.head[0x10 + 10 * len(pa.entries):] != pb.head[0x10 + 10 * len(pb.entries):]:
        return False
    return all(x.type == y.type and x.flag == y.flag and x.data == y.data
               for x, y in zip(pa.entries, pb.entries))


def _actual(names, want):
    for n in names:
        if n.lower() == want.lower():
            return n
    return want


def _game_palette(game_dir):
    names = os.listdir(game_dir)
    with open(os.path.join(game_dir, _actual(names, GAME_PALETTE)), "rb") as f:
        return view(Palette.from_vga(f.read(VGA_BYTES), GAME_PALETTE))


def _font_palette():
    return Palette(FONT_VIEW, "font")


README = """\
# A coldos workspace

Extracted from a copy of *Colonization* for DOS. Edit what is here, then

    coldos status .                  # what changed
    coldos build  . --out=PATCHED    # a complete game directory with the edits

`build` re-encodes only what changed; everything else goes back byte for byte.

| | |
| --- | --- |
| `sprites/<SHEET>/<nnn>.png` | every sprite of every `.SS`; sprite nnn is icon nnn+1 in the game's code. Index 253 is transparent. Keep the size. |
| `pictures/<NAME>.png` | every `.PIK` backdrop. Keep the size. |
| `fonts/<FONT>/<nnn>.png` | one glyph a file, 4 colours (0 paper, 1-3 ink); slot nnn draws character nnn+1. Make it wider or narrower freely, keep the height; delete a file to empty a slot, add one to fill an empty slot. |
| `palettes/<NAME>.pal` | the palettes, JASC format. `VICEROY.pal` is the game's master palette; the others ride along with their sheet or picture. Values are written 8-bit and stored 6-bit (`v >> 2`). |
| `text/<NAME>` | the game's text files, UTF-8 here, code page 437 in the game. |

The PNGs are **indexed**: the pixel values are the game's palette indices.
Paint with the image's own palette -- in an indexed-mode editor (Aseprite,
GraphicsGale, GIMP in Image > Mode > Indexed) this is automatic. A truecolour
save still works as long as every colour is one of the palette's; `build`
names any file where one is not (or maps it to the nearest with `--nearest`).

`coldos.json` is the manifest. Leave it alone: it is how `build` knows what
you changed.
"""


def _write_readme(root):
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write(README)

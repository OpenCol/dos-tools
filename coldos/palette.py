"""Palettes: 256 VGA DAC entries, six bits a channel.

Unlike the Windows build, the DOS game stores its colours: `VICEROY.PAL`'s
first 0x300 bytes are the palette the game loads at start-up
(`load_palette_file`, VICEROY.EXE file 0x781de, reads exactly 0x300 bytes
and copies them to the master palette), and almost every sheet and picture
carries a 0x300-byte palette of its own. So a view palette here is the file's
own colours, not a reconstruction.

The rule from win-tools still holds, because it is what makes editing safe:
**indices are the data, a palette is a way of looking at them.** Extracted
PNGs are indexed and their pixel values are the game's bytes. The view palette
is made *injective* -- duplicate entries nudged one step on one channel -- so a
paint program that saves truecolour still maps every colour back to exactly
one index.

Six bits widen to eight as `v << 2 | v >> 4` (0 -> 0, 63 -> 255), and narrow
back as `v >> 2`, which inverts it exactly for all 64 values.
"""
import os

VGA_BYTES = 0x300


def widen(v):
    return (v << 2 | v >> 4) & 0xFF


def narrow(v):
    return v >> 2


class Palette:
    def __init__(self, entries, name="view"):
        if len(entries) > 256:
            raise ValueError("palette has %d entries" % len(entries))
        self.entries = [tuple(e[:3]) for e in entries]
        while len(self.entries) < 256:
            self.entries.append((0, 0, 0))
        self.name = name
        self._inv = None

    @classmethod
    def from_vga(cls, data, name="view"):
        """0x300 bytes of 6-bit RGB.

        A byte above 63 cannot come from a DAC read; it is widened with its
        high bits dropped, and `vga_bytes` will not reproduce it, so callers
        that need the bytes back keep the original (the workspace does).
        """
        if len(data) < VGA_BYTES:
            raise ValueError("%s: %d bytes is not a VGA palette" % (name, len(data)))
        return cls([tuple(widen(data[i * 3 + k] & 0x3F) for k in range(3))
                    for i in range(256)], name)

    def vga_bytes(self):
        return bytes(narrow(c) for e in self.entries for c in e)

    def copy(self, name=None):
        return Palette(list(self.entries), name or self.name)

    def uniquify(self, priority=()):
        """Make colour -> index total by nudging duplicates a hair.

        Indices in `priority` keep their exact colour. Returns {index: (was, now)}.
        """
        pri = set(priority)
        taken, moved = {}, {}
        order = [i for i in range(256) if i in pri] + [i for i in range(256) if i not in pri]
        for i in order:
            e = self.entries[i]
            if e not in taken:
                taken[e] = i
                continue
            cand = _free_near(e, taken)
            self.entries[i] = cand
            taken[cand] = i
            moved[i] = (e, cand)
        self._inv = None
        return moved

    def inverse(self):
        if self._inv is None:
            self._inv = {}
            for i, e in enumerate(self.entries):
                self._inv.setdefault(e, i)
        return self._inv

    def nearest(self, rgb):
        """Closest entry by a redmean-weighted distance."""
        r, g, b = rgb[:3]
        best, bd = 0, None
        for i, (pr, pg, pb) in enumerate(self.entries):
            rm = (pr + r) // 2
            dr, dg, db = pr - r, pg - g, pb - b
            d = (((512 + rm) * dr * dr) >> 8) + 4 * dg * dg + (((767 - rm) * db * db) >> 8)
            if bd is None or d < bd:
                best, bd = i, d
        return best

    # -- files ------------------------------------------------------------ #

    def write_jasc(self, path):
        with open(path, "w", newline="\n") as f:
            f.write("JASC-PAL\n0100\n%d\n" % len(self.entries))
            for r, g, b in self.entries:
                f.write("%d %d %d\n" % (r, g, b))

    @classmethod
    def read_jasc(cls, path, name=None):
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines or lines[0].upper() != "JASC-PAL":
            raise ValueError("%s: not a JASC .pal" % path)
        n = int(lines[2])
        entries = []
        for l in lines[3:3 + n]:
            parts = l.split()
            rgb = tuple(int(p) for p in parts[:3])
            if not all(0 <= v <= 255 for v in rgb):
                raise ValueError("%s: colour %r is outside 0-255" % (path, rgb))
            entries.append(rgb)
        if n != 256:
            raise ValueError("%s: %d colours; a VGA palette has 256" % (path, n))
        return cls(entries, name or os.path.basename(path))


def _free_near(rgb, taken):
    """The nearest colour to `rgb` that nothing else holds."""
    for delta in range(1, 9):
        for ch in (2, 1, 0):
            for sign in (1, -1):
                c = list(rgb)
                c[ch] += sign * delta
                if 0 <= c[ch] <= 255 and tuple(c) not in taken:
                    return tuple(c)
    for r in range(1, 256):
        for dr in range(-r, r + 1):
            for dg in range(-r, r + 1):
                for db in range(-r, r + 1):
                    if max(abs(dr), abs(dg), abs(db)) != r:
                        continue
                    c = (rgb[0] + dr, rgb[1] + dg, rgb[2] + db)
                    if all(0 <= v <= 255 for v in c) and c not in taken:
                        return c
    raise ValueError("no free colour anywhere near %r" % (rgb,))


def view(pal):
    """An injective copy of `pal`, for writing PNGs."""
    v = pal.copy()
    v.uniquify()
    return v

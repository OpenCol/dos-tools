"""PNG read and write, stdlib only (zlib).

Write side is deliberately narrow: indexed (colour type 3) with an optional
tRNS, plus RGB/RGBA for things that are genuinely truecolour.  Indexed output
is what keeps the export lossless -- the PNG's pixel values ARE the game's
palette indices, so the palette is only a way of looking at them.

Read side has to be wider, because it takes whatever a paint program saved:
colour types 0/2/3/4/6, bit depths 1/2/4/8, tRNS in all its forms.  16-bit and
interlaced files are refused with a message that says what to do instead,
rather than being silently mangled.
"""
import struct
import zlib

__all__ = ["write_indexed", "write_rgb", "write_rgba", "read", "PngError"]

SIG = b"\x89PNG\r\n\x1a\n"


class PngError(Exception):
    pass


# --------------------------------------------------------------------------- #
# writing

def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _write(path, w, h, depth, colour, raw, stride, extra=b"", text=None):
    lines = bytearray()
    for y in range(h):
        lines.append(0)                                # filter 0 (None)
        lines += raw[y * stride:(y + 1) * stride]
    chunks = [SIG, _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, colour, 0, 0, 0))]
    chunks.append(extra)
    for k, v in (text or []):
        chunks.append(_chunk(b"tEXt", k.encode("latin-1") + b"\x00" +
                             v.encode("latin-1", "replace")))
    chunks.append(_chunk(b"IDAT", zlib.compress(bytes(lines), 9)))
    chunks.append(_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(b"".join(chunks))


def write_indexed(path, w, h, indices, palette, transparent=None, text=None):
    """indices: w*h bytes.  palette: <=256 (r,g,b).  transparent: index or None."""
    if len(indices) != w * h:
        raise PngError("%d pixels for %dx%d" % (len(indices), w, h))
    if len(palette) > 256:
        raise PngError("palette has %d entries" % len(palette))
    extra = _chunk(b"PLTE", b"".join(bytes(c[:3]) for c in palette))
    if transparent is not None:
        alpha = bytearray(b"\xff" * (transparent + 1))
        alpha[transparent] = 0
        extra += _chunk(b"tRNS", bytes(alpha))
    _write(path, w, h, 8, 3, indices, w, extra, text)


def write_rgb(path, w, h, rgb, text=None):
    _write(path, w, h, 8, 2, rgb, w * 3, b"", text)


def write_rgba(path, w, h, rgba, text=None):
    _write(path, w, h, 8, 6, rgba, w * 4, b"", text)


# --------------------------------------------------------------------------- #
# reading

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(raw, w, h, bpp_bytes, stride):
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft == 1:
            for i in range(bpp_bytes, stride):
                line[i] = (line[i] + line[i - bpp_bytes]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp_bytes] if i >= bpp_bytes else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp_bytes] if i >= bpp_bytes else 0
                c = prev[i - bpp_bytes] if i >= bpp_bytes else 0
                b = prev[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise PngError("unknown filter type %d on row %d" % (ft, y))
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _expand(row, w, depth):
    """One scanline of sub-byte indices -> one byte per pixel."""
    out = bytearray(w)
    per = 8 // depth
    mask = (1 << depth) - 1
    for x in range(w):
        byte = row[x // per]
        shift = 8 - depth * (x % per + 1)
        out[x] = (byte >> shift) & mask
    return out


def read(path):
    """-> dict(mode, width, height, pixels, palette, trns).

    mode is "P" (pixels are palette indices, palette is a list of (r,g,b),
    trns is a list of per-index alpha), or "RGBA" (pixels are 4 bytes per
    pixel).  Greyscale and RGB are widened to RGBA so callers handle two cases,
    not five.
    """
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != SIG:
        raise PngError("%s: not a PNG" % path)
    pos, idat, plte, trns = 8, bytearray(), None, None
    w = h = depth = colour = interlace = None
    while pos + 8 <= len(data):
        ln, tag = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, depth, colour, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            plte = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if w is None:
        raise PngError("%s: no IHDR" % path)
    if interlace:
        raise PngError("%s: interlaced (Adam7) PNGs are not read; re-save it "
                       "without interlacing" % path)
    if depth == 16:
        raise PngError("%s: 16 bits per channel; re-save it as 8-bit" % path)
    if colour not in _CHANNELS:
        raise PngError("%s: colour type %d" % (path, colour))

    ch = _CHANNELS[colour]
    bits = w * ch * depth
    stride = (bits + 7) // 8
    bpp_bytes = max(1, ch * depth // 8)
    raw = _unfilter(zlib.decompress(bytes(idat)), w, h, bpp_bytes, stride)

    if colour == 3:
        if plte is None:
            raise PngError("%s: indexed but no PLTE" % path)
        px = bytearray()
        for y in range(h):
            row = raw[y * stride:(y + 1) * stride]
            px += _expand(row, w, depth) if depth < 8 else row[:w]
        alpha = list(trns) if trns else []
        return {"mode": "P", "width": w, "height": h, "pixels": bytes(px),
                "palette": plte, "trns": alpha}

    # everything else -> RGBA
    out = bytearray(w * h * 4)
    if depth < 8:                                     # greyscale 1/2/4
        scale = 255 // ((1 << depth) - 1)
    for y in range(h):
        row = raw[y * stride:(y + 1) * stride]
        if depth < 8:
            row = bytes(v * scale for v in _expand(row, w, depth))
            step = 1
        else:
            step = ch
        for x in range(w):
            s = row[x * step:x * step + step]
            if colour == 0:
                r = g = b = s[0]
                a = 255
            elif colour == 4:
                r = g = b = s[0]
                a = s[1]
            elif colour == 2:
                r, g, b = s[0], s[1], s[2]
                a = 255
            else:
                r, g, b, a = s[0], s[1], s[2], s[3]
            o = (y * w + x) * 4
            out[o] = r
            out[o + 1] = g
            out[o + 2] = b
            out[o + 3] = a
    if trns and colour in (0, 2):
        key = ((trns[1],) if colour == 0 else (trns[1], trns[3], trns[5]))
        key = key * 3 if len(key) == 1 else key
        for i in range(0, len(out), 4):
            if tuple(out[i:i + 3]) == key:
                out[i + 3] = 0
    return {"mode": "RGBA", "width": w, "height": h, "pixels": bytes(out),
            "palette": None, "trns": None}

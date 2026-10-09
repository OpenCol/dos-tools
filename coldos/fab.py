"""FAB: the LZ77 codec inside a MADSPACK entry of type 1.

    0x00  3     "FAB"
    0x03  BYTE  shift (12 in every shipped stream; 10-13 decode)
    0x04  WORD  the first word of the flag bit stream
    0x06  ...   tokens, with further flag words interleaved

Flag bits are taken least significant first from 16-bit little-endian words.
A word is fetched the moment the previous one's sixteenth bit is asked for --
so it sits in the byte stream *before* the data bytes of the token whose flag
bit emptied the old word, which is what an encoder has to reproduce:

    1                 literal: one byte follows
    0 0 a b           short copy: length 2 + (a<<1 | b), distance 256 - next byte
    0 1               long copy: two bytes L, H follow
                        distance = 0x10000 - ((H >> (16-shift) | 0xff << (shift-8)) << 8 | L)
                        length   = H & ((1 << (16-shift)) - 1)
                        length 0 -> one more byte n: 0 ends the stream,
                                    1 is a no-op, otherwise length n + 1
                        length k -> k + 2

With shift 12 that is a 4096-byte window, copies of 2-5 bytes reachable 256
back for 12 bits, of 3-17 bytes for 18 bits and of up to 256 bytes for 26.

Evidence: the decoder is `ff_decode`'s type-1 branch in VICEROY.EXE (overlay
28, file 0x772fa), the same codec the MADS engine's own games use. Every type-1
entry in the 246 shipped MADSPACK files decodes to exactly its declared size
and ends exactly at its declared packed size, with no byte left over.

The shipped packer seems to work in 40,960-byte blocks: the no-op token turns
up 44 times, every time within 223 bytes after the output passes a multiple
of 0xa000, and nowhere else. `compress` does not imitate that packer: its
output is valid and decodes to the same bytes, and for 479 of the 793 shipped
streams it is also the same bytes. That is why an unedited entry is never
re-packed.
"""
import struct

MAGIC = b"FAB"
SHIFT = 12


class FabError(Exception):
    pass


def decompress(src, size):
    """The `size` bytes a FAB stream decodes to."""
    if src[:3] != MAGIC:
        raise FabError("not a FAB stream (starts %r)" % bytes(src[:4]))
    shift = src[3]
    if not 10 <= shift <= 13:
        raise FabError("FAB shift %d is outside 10-13" % shift)
    ofs_shift = 16 - shift
    ofs_mask = (0xFF << (shift - 8)) & 0xFF
    len_mask = (1 << ofs_shift) - 1
    n_src = len(src)
    out = bytearray()
    p = 6
    left = 16
    buf = src[4] | src[5] << 8

    while True:
        # Inlined bit reader: three of these per token is the hot path.
        left -= 1
        if left == 0:
            buf = ((src[p] | src[p + 1] << 8) << 1) | (buf & 1)
            p += 2
            left = 16
        b = buf & 1
        buf >>= 1
        if b:
            if p >= n_src:
                raise FabError("FAB stream ends inside a literal")
            out.append(src[p])
            p += 1
            continue
        left -= 1
        if left == 0:
            buf = ((src[p] | src[p + 1] << 8) << 1) | (buf & 1)
            p += 2
            left = 16
        b = buf & 1
        buf >>= 1
        if not b:
            n = 0
            for _ in range(2):
                left -= 1
                if left == 0:
                    buf = ((src[p] | src[p + 1] << 8) << 1) | (buf & 1)
                    p += 2
                    left = 16
                n = n << 1 | (buf & 1)
                buf >>= 1
            n += 2
            dist = 256 - src[p]
            p += 1
        else:
            lo, hi = src[p], src[p + 1]
            p += 2
            dist = 0x10000 - ((((hi >> ofs_shift) | ofs_mask) << 8) | lo)
            n = hi & len_mask
            if n == 0:
                n = src[p]
                p += 1
                if n == 0:
                    break
                if n == 1:
                    continue
                n += 1
            else:
                n += 2
        start = len(out) - dist
        if start < 0:
            raise FabError("FAB copy reaches %d bytes before the start" % -start)
        if dist >= n:
            out += out[start:start + n]
        else:                                   # overlapping: a run
            for i in range(n):
                out.append(out[start + i])
        if len(out) > size:
            raise FabError("FAB stream decodes past its declared %d bytes" % size)
    if len(out) != size:
        raise FabError("FAB stream decodes to %d bytes, declared %d" % (len(out), size))
    return bytes(out), p


class _Writer:
    """Flag bits into reserved word slots, data bytes in between."""

    def __init__(self):
        self.out = bytearray(MAGIC + bytes([SHIFT]) + b"\0\0")
        self.slot = 4
        self.word = 0
        self.nbits = 0

    def bit(self, b):
        self.word |= (b & 1) << self.nbits
        self.nbits += 1
        if self.nbits == 16:
            struct.pack_into("<H", self.out, self.slot, self.word)
            # The decoder fetches the next word when it asks for this bit,
            # i.e. before the data bytes of the current token.
            self.slot = len(self.out)
            self.out += b"\0\0"
            self.word = 0
            self.nbits = 0

    def finish(self):
        struct.pack_into("<H", self.out, self.slot, self.word)
        return bytes(self.out)


WINDOW = 1 << SHIFT          # 4096: what a long copy's 12 bits can reach
MAX_LEN = 253                # the longest copy in any shipped stream
SHORT_REACH = 255            # a short copy at exactly 256 is never shipped


def _longest(data, i, end):
    """(length, distance) of the longest earlier match at i, or (0, 0).

    Ties go to the NEAREST occurrence. The shipped packer breaks ties some
    other way -- sometimes nearest, sometimes farthest, which looks like
    hash-chain order -- and that is most of why only about half of the
    shipped streams come back byte for byte. `bytes.rfind` does the
    scanning in C; each hit is then extended
    forwards, which may run past i -- an overlapping copy is how a run is
    written, and the decoder copies byte by byte.
    """
    lo = max(0, i - WINDOW)
    best_n, best_d = 0, 0
    n = 2
    while n <= MAX_LEN and i + n <= end:
        j = data.rfind(data[i:i + n], lo, i + n - 1)
        if j < 0:
            break
        m = n
        while m < MAX_LEN and i + m < end and data[j + m] == data[i + m]:
            m += 1
        best_n, best_d = m, i - j
        n = m + 1
    return best_n, best_d


def compress(data):
    """A FAB stream that decodes to `data`.  Valid, not always the shipped bytes."""
    data = bytes(data)
    w = _Writer()
    i, end = 0, len(data)
    while i < end:
        n, d = _longest(data, i, end)
        if 2 <= n <= 5 and d <= SHORT_REACH:
            w.bit(0)
            w.bit(0)
            k = n - 2
            w.bit(k >> 1)
            w.bit(k & 1)
            w.out.append(256 - d)
        elif n >= 3:
            w.bit(0)
            w.bit(1)
            v = 0x10000 - d                     # 0xf000..0xffff
            hi_ofs = (v >> 8) & 0x0F
            if n <= 17:
                w.out += bytes([v & 0xFF, hi_ofs << 4 | (n - 2)])
            else:
                w.out += bytes([v & 0xFF, hi_ofs << 4, n - 1])
        else:
            n = 1
            w.bit(1)
            w.out.append(data[i])
        i += n
    w.bit(0)
    w.bit(1)
    w.out += b"\0\0\0"                          # long copy, length 0, n = 0: end
    return w.finish()

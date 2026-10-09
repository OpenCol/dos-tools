"""MADSPACK 2.0: the container every .SS, .PIK and .FF file is.

    0x00  13    "MADSPACK 2.0\\x1a"
    0x0d  BYTE  0
    0x0e  WORD  count of entries (1-16)
    0x10  16 x 10-byte entry slots:
            BYTE  type    0 stored, 1 FAB (see fab.py)
            BYTE  flag    carried; identical across one file's entries
            DWORD size    bytes after unpacking
            DWORD packed  bytes in the file
    0xb0  the entries' data, back to back, in entry order
    ....  sometimes more bytes after the last entry (4 of the 246 files)

Evidence: `ff_open` (VICEROY.EXE overlay 28, file 0x76e50) reads the
16-byte head, checks the magic and reads `count` entries; `ff_read` (file
0x77100) takes the entries in order, treating type 0 as a stored copy and
any other type as packed. Every shipped file closes on that arithmetic:
0xb0 + the sum of `packed` is the file size, or the start of the trailing
bytes.

**Carried, not computed.** The slots past `count` are not zeroed in the
shipped files -- they hold whatever was in the packer's memory -- and the
`flag` byte is not what `ff_read` decides anything on. Both go back
exactly as they came, as do the trailing bytes. That is what lets a file
with one edited entry differ from the original in that entry and its sizes
only.
"""
import struct

from . import fab

MAGIC = b"MADSPACK 2.0\x1a"
HEAD = 0xB0
SLOTS = 16
SLOT = 10
STORED, FAB = 0, 1


class MadspackError(Exception):
    pass


def is_madspack(data):
    return data[:12] == MAGIC[:12]


class Entry:
    def __init__(self, etype, flag, size, raw):
        self.type = etype
        self.flag = flag
        self.size = size
        self.raw = raw                  # the bytes as they sit in the file
        self._data = None

    @property
    def data(self):
        if self._data is None:
            if self.type == STORED:
                if len(self.raw) != self.size:
                    raise MadspackError("stored entry is %d bytes, declared %d"
                                        % (len(self.raw), self.size))
                self._data = bytes(self.raw)
            else:
                out, used = fab.decompress(self.raw, self.size)
                if used != len(self.raw):
                    raise MadspackError("FAB entry stops %d bytes short of its "
                                        "packed size" % (len(self.raw) - used))
                self._data = out
        return self._data


class Madspack:
    def __init__(self, head, entries, trailing=b""):
        self.head = bytearray(head)     # all 0xb0 bytes, slack included
        self.entries = entries
        self.trailing = trailing

    @classmethod
    def parse(cls, data, name="file"):
        if not is_madspack(data):
            raise MadspackError("%s: not a MADSPACK file" % name)
        if len(data) < HEAD:
            raise MadspackError("%s: %d bytes is shorter than the header" % (name, len(data)))
        count = struct.unpack_from("<H", data, 0x0E)[0]
        if not 1 <= count <= SLOTS:
            raise MadspackError("%s: %d entries" % (name, count))
        pos, entries = HEAD, []
        for i in range(count):
            etype, flag, size, packed = struct.unpack_from("<BBII", data, 0x10 + SLOT * i)
            if pos + packed > len(data):
                raise MadspackError("%s: entry %d runs past the end of the file" % (name, i))
            entries.append(Entry(etype, flag, size, data[pos:pos + packed]))
            pos += packed
        return cls(data[:HEAD], entries, data[pos:])

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls.parse(f.read(), path)

    def replace(self, i, data, etype=None):
        """Put new contents into entry i, packed the way the old ones were."""
        e = self.entries[i]
        t = e.type if etype is None else etype
        raw = data if t == STORED else fab.compress(data)
        ne = Entry(t, e.flag, len(data), raw)
        ne._data = bytes(data)
        self.entries[i] = ne

    def to_bytes(self):
        head = bytearray(self.head)
        struct.pack_into("<H", head, 0x0E, len(self.entries))
        for i, e in enumerate(self.entries):
            struct.pack_into("<BBII", head, 0x10 + SLOT * i, e.type, e.flag, e.size, len(e.raw))
        return bytes(head) + b"".join(bytes(e.raw) for e in self.entries) + bytes(self.trailing)

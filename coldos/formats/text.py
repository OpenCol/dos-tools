"""The game's text files: plain DOS text, code page 437, CRLF.

`GAME.TXT`, `PEDIA.TXT`, `MENU.TXT` and the rest are read line by line by
`text_open` / `text_get` (VICEROY.EXE overlay 24, file 0x6f8fa) through the C
runtime's stdio, so they need no decoding -- only a character set. Every
shipped file is ASCII except one byte of `PEDIA.TXT` (0xF9, cp437's "∙").

The workspace holds them as UTF-8 so any editor shows that byte as the
character it is. cp437 assigns a character to all 256 bytes, so the trip is
exact both ways; a character cp437 does not have is refused, by name.
"""

CODEPAGE = "cp437"


class TextError(Exception):
    pass


def to_utf8(data):
    return data.decode(CODEPAGE).encode("utf-8")


def from_utf8(data, name="text"):
    try:
        s = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise TextError("%s: not UTF-8 (%s)" % (name, e))
    out = bytearray()
    for n, ch in enumerate(s):
        try:
            out += ch.encode(CODEPAGE)
        except UnicodeEncodeError:
            line = s.count("\n", 0, n) + 1
            raise TextError("%s line %d: %r (U+%04X) is not in code page 437, "
                            "which is all the DOS game can show" % (name, line, ch, ord(ch)))
    return bytes(out)

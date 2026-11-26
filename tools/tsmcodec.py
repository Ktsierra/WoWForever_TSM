"""Read and write TradeSkillMaster 4 group export strings.

TSM export strings are:
    LibDeflate.EncodeForPrint( raw DEFLATE( LibSerialize.Serialize(...) ) )

This is a small pure-Python port of those three pieces, written so the export
strings can be edited without running WoW. Lua tables become `LuaTable`
objects (an ordered dict), Lua strings stay as `bytes`.
"""

import math
import struct
import zlib

# --------------------------------------------------------------------------
# LibDeflate EncodeForPrint / DecodeForPrint
# --------------------------------------------------------------------------

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()"
_CHAR_TO_6BIT = {c: i for i, c in enumerate(_ALPHABET)}


def decode_for_print(text: str) -> bytes:
    text = text.strip(" \t\r\n\x00")
    if len(text) == 1:
        raise ValueError("string too short")
    out = bytearray()
    i, n = 0, len(text)
    while i <= n - 4:
        v = 0
        for k in range(4):
            v |= _CHAR_TO_6BIT[text[i + k]] << (6 * k)
        out += bytes((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
        i += 4
    cache, bits = 0, 0
    while i < n:
        cache |= _CHAR_TO_6BIT[text[i]] << bits
        bits += 6
        i += 1
    while bits >= 8:
        out.append(cache & 0xFF)
        cache >>= 8
        bits -= 8
    return bytes(out)


def encode_for_print(data: bytes) -> str:
    out = []
    i, n = 0, len(data)
    while i <= n - 3:
        v = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
        out.append("".join(_ALPHABET[(v >> (6 * k)) & 63] for k in range(4)))
        i += 3
    cache, bits = 0, 0
    while i < n:
        cache |= data[i] << bits
        bits += 8
        i += 1
    while bits > 0:
        out.append(_ALPHABET[cache & 63])
        cache >>= 6
        bits -= 6
    return "".join(out)


def inflate(data: bytes) -> bytes:
    d = zlib.decompressobj(-15)
    out = d.decompress(data) + d.flush()
    return out


def deflate(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


# --------------------------------------------------------------------------
# LibSerialize (format version 1)
# --------------------------------------------------------------------------

class LuaTable(dict):
    """A Lua table. Keys are int/float/bytes/bool, insertion order kept."""


# Reader indices (type code stored in the upper 5 bits of the type byte).
NIL, N16P, N16N, N24P, N24N, N32P, N32N, N64P, N64N = range(9)
NFLOAT, NFLOATSTR, NFLOATSTR_NEG, BOOL_T, BOOL_F = 9, 10, 11, 12, 13
STR8, STR16, STR24 = 14, 15, 16
TAB8, TAB16, TAB24 = 17, 18, 19
ARR8, ARR16, ARR24 = 20, 21, 22
MIX8, MIX16, MIX24 = 23, 24, 25
SREF8, SREF16, SREF24 = 26, 27, 28
TREF8, TREF16, TREF24 = 29, 30, 31

# Embedded-count types (bits 3-4 of the type byte).
E_STRING, E_TABLE, E_ARRAY, E_MIXED = 0, 1, 2, 3


def _norm_number(x):
    if isinstance(x, float) and math.isfinite(x) and x == int(x):
        return int(x)
    return x


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.srefs = []
        self.trefs = []

    def at_end(self):
        return self.pos >= len(self.data)

    def bytes_(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("unexpected end of data")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def int_(self, n):
        return int.from_bytes(self.bytes_(n), "big")

    def byte(self):
        return self.int_(1)

    def string(self, length):
        s = self.bytes_(length)
        if length > 2:
            self.srefs.append(s)
        return s

    def table(self, count, t=None):
        if t is None:
            t = LuaTable()
            self.trefs.append(t)
        for _ in range(count):
            k = self.obj()
            v = self.obj()
            t[k] = v
        return t

    def array(self, count, t=None):
        if t is None:
            t = LuaTable()
            self.trefs.append(t)
        for i in range(1, count + 1):
            v = self.obj()
            if v is not None:
                t[i] = v
        return t

    def mixed(self, acount, mcount):
        t = LuaTable()
        self.trefs.append(t)
        self.array(acount, t)
        self.table(mcount, t)
        return t

    def obj(self):
        v = self.byte()
        if v % 2 == 1:
            return (v - 1) // 2
        if v % 4 == 2:
            typ = (v - 2) // 4
            count = typ // 4
            typ %= 4
            if typ == E_STRING:
                return self.string(count)
            if typ == E_TABLE:
                return self.table(count)
            if typ == E_ARRAY:
                return self.array(count)
            return self.mixed(count % 4 + 1, count // 4 + 1)
        if v % 8 == 4:
            packed = self.byte() * 256 + v
            if v % 16 == 12:
                return -((packed - 12) // 16)
            return (packed - 4) // 16
        typ = v // 8
        if typ == NIL:
            return None
        if typ in (N16P, N16N, N24P, N24N, N32P, N32N, N64P, N64N):
            size = {N16P: 2, N16N: 2, N24P: 3, N24N: 3, N32P: 4, N32N: 4, N64P: 7, N64N: 7}[typ]
            n = self.int_(size)
            return -n if typ in (N16N, N24N, N32N, N64N) else n
        if typ == NFLOAT:
            return _norm_number(struct.unpack(">d", self.bytes_(8))[0])
        if typ in (NFLOATSTR, NFLOATSTR_NEG):
            s = self.bytes_(self.byte()).decode("ascii")
            n = _norm_number(float(s))
            return -n if typ == NFLOATSTR_NEG else n
        if typ == BOOL_T:
            return True
        if typ == BOOL_F:
            return False
        if typ in (STR8, STR16, STR24):
            return self.string(self.int_(typ - STR8 + 1))
        if typ in (TAB8, TAB16, TAB24):
            return self.table(self.int_(typ - TAB8 + 1))
        if typ in (ARR8, ARR16, ARR24):
            return self.array(self.int_(typ - ARR8 + 1))
        if typ in (MIX8, MIX16, MIX24):
            size = typ - MIX8 + 1
            a = self.int_(size)
            m = self.int_(size)
            return self.mixed(a, m)
        if typ in (SREF8, SREF16, SREF24):
            return self.srefs[self.int_(typ - SREF8 + 1) - 1]
        if typ in (TREF8, TREF16, TREF24):
            return self.trefs[self.int_(typ - TREF8 + 1) - 1]
        raise ValueError(f"unknown type byte {v}")


def _req_bytes(n):
    if n < 256:
        return 1
    if n < 65536:
        return 2
    if n < 16777216:
        return 3
    raise ValueError("object limit exceeded")


def _req_bytes_number(n):
    for size, limit in ((1, 256), (2, 65536), (3, 16777216), (4, 4294967296)):
        if n < limit:
            return size
    return 7


def _lua_tostring_number(x):
    # Lua 5.1 uses "%.14g" for numbers.
    return "%.14g" % x


class _Writer:
    def __init__(self):
        self.out = bytearray()
        self.srefs = {}
        self.trefs = {}

    def byte(self, b):
        self.out.append(b)

    def int_(self, n, size):
        self.out += int(n).to_bytes(size, "big")

    def obj(self, v):
        if v is None:
            self.byte(NIL * 8)
        elif isinstance(v, bool):
            self.byte((BOOL_T if v else BOOL_F) * 8)
        elif isinstance(v, (int, float)):
            self.number(v)
        elif isinstance(v, (bytes, str)):
            self.string(v.encode("utf-8") if isinstance(v, str) else v)
        elif isinstance(v, dict):
            self.table(v)
        else:
            raise TypeError(f"cannot serialize {type(v)}")

    def number(self, num):
        num = _norm_number(num)
        is_float = isinstance(num, float)
        if not is_float and abs(num) >= 72057594037927936:
            is_float, num = True, float(num)
        if is_float:
            sign = 0
            num_abs = num
            if num < 0:
                sign, num_abs = 8, -num
            as_str = _lua_tostring_number(num_abs)
            if len(as_str) < 7 and math.isfinite(num_abs) and float(as_str) == num_abs:
                self.byte(sign + NFLOATSTR * 8)
                self.byte(len(as_str))
                self.out += as_str.encode("ascii")
            else:
                self.byte(NFLOAT * 8)
                self.out += struct.pack(">d", num)
        elif -4096 < num < 4096:
            if 0 <= num < 128:
                self.byte(num * 2 + 1)
            else:
                sign = 0
                if num < 0:
                    sign, num = 8, -num
                num = num * 16 + sign + 4
                self.byte(num % 256)
                self.byte(num // 256)
        else:
            sign = 0
            if num < 0:
                num, sign = -num, 8
            size = _req_bytes_number(num)
            self.byte(sign + {2: N16P, 3: N24P, 4: N32P, 7: N64P}[size] * 8)
            self.int_(num, size)

    def string(self, s: bytes):
        ref = self.srefs.get(s)
        if ref:
            size = _req_bytes(ref)
            self.byte((SREF8 + size - 1) * 8)
            self.int_(ref, size)
            return
        n = len(s)
        if n < 16:
            self.byte(16 * n + 4 * E_STRING + 2)
        else:
            size = _req_bytes(n)
            self.byte((STR8 + size - 1) * 8)
            self.int_(n, size)
        self.out += s
        if n > 2:
            self.srefs[s] = len(self.srefs) + 1

    def table(self, t):
        ref = self.trefs.get(id(t))
        if ref:
            size = _req_bytes(ref)
            self.byte((TREF8 + size - 1) * 8)
            self.int_(ref, size)
            return
        self.trefs[id(t)] = len(self.trefs) + 1

        # Array part: keys 1..n with no gaps (Lua ipairs).
        acount = 0
        while (acount + 1) in t and t[acount + 1] is not None:
            acount += 1
        map_items = [(k, v) for k, v in t.items()
                     if not (isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= acount)
                     and v is not None]
        mcount = len(map_items)

        if mcount == 0:
            if acount < 16:
                self.byte(16 * acount + 4 * E_ARRAY + 2)
            else:
                size = _req_bytes(acount)
                self.byte((ARR8 + size - 1) * 8)
                self.int_(acount, size)
            for i in range(1, acount + 1):
                self.obj(t[i])
        elif acount != 0:
            if mcount < 5 and acount < 5:
                combined = (mcount - 1) * 4 + acount - 1
                self.byte(16 * combined + 4 * E_MIXED + 2)
            else:
                size = max(_req_bytes(mcount), _req_bytes(acount))
                self.byte((MIX8 + size - 1) * 8)
                self.int_(acount, size)
                self.int_(mcount, size)
            for i in range(1, acount + 1):
                self.obj(t[i])
            for k, v in map_items:
                self.obj(k)
                self.obj(v)
        else:
            if mcount < 16:
                self.byte(16 * mcount + 4 * E_TABLE + 2)
            else:
                size = _req_bytes(mcount)
                self.byte((TAB8 + size - 1) * 8)
                self.int_(mcount, size)
            for k, v in map_items:
                self.obj(k)
                self.obj(v)


SERIALIZATION_VERSION = 1


def deserialize(raw: bytes):
    r = _Reader(raw)
    version = r.byte()
    if version > 2:
        raise ValueError(f"unknown LibSerialize version {version}")
    values = []
    while not r.at_end():
        values.append(r.obj())
    return values


def serialize(values) -> bytes:
    w = _Writer()
    w.byte(SERIALIZATION_VERSION)
    for v in values:
        w.obj(v)
    return bytes(w.out)


# --------------------------------------------------------------------------
# Whole export strings
# --------------------------------------------------------------------------

def decode_export(text: str):
    """Export string -> (list of top-level Lua values, raw serialized bytes)."""
    raw = inflate(decode_for_print(text))
    return deserialize(raw), raw


def encode_export(values) -> str:
    return encode_for_print(deflate(serialize(values)))

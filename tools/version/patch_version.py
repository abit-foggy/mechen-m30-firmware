#!/usr/bin/env python3
"""Rewrite the Settings -> Information version and date rows in setting.ap.

usage: patch_version.py SETTING.ap OUT.ap VERSION IDENT

The Information callback sub_40115074 (bank 0x40114c00 = setting.ap file 0x2c00,
found through the .ap bank table) loads three strings with PC-relative `la`:

  0x4011507a -> "M30"          stock halfword 0x0a23   (model row, untouched)
  0x4011507e -> "  V1.101.10"  stock halfword 0x0a23   (version row)
  0x40115082 -> "2025-06-25"   stock halfword 0x0a25   (date row)

MIPS16e `la rx, imm8(PC)` encodes target = instr + imm8*4 - 2 (calibrated on the
three stock sites above; imm8 is unsigned, so a target must sit within +1022 bytes
of its instruction). The stock strings stay in place as dead data -- the version
field is only 12 bytes, far too small for a longer replacement -- and the two row
pointers are redirected to new strings written into the verified all-zero tail of
the same bank (guest 0x401153b8..0x40115400, file 0x33b8..0x3400; the strings at
0x401153a0 "legal.txt" and 0x401153ac "m_type.txt" end just before it).

Every stock byte the patch depends on (bank table entry, the three `la` halfwords,
the three stock strings, the zero tail) is asserted before anything is written,
and the result is re-read and diffed against the input so only the two halfwords
and the two 0x20-byte slots may differ.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from apinfo import parse  # noqa: E402

CALLBACK = 0x40115074                 # sub_40115074, the Information callback
LA_MODEL, LA_VER, LA_DATE = 0x4011507a, 0x4011507e, 0x40115082
STR_MODEL, STR_VER, STR_DATE = 0x40115104, 0x40115108, 0x40115114
STOCK_HW = {LA_MODEL: 0x0a23, LA_VER: 0x0a23, LA_DATE: 0x0a25}
STOCK_STR = {STR_MODEL: b'M30\x00', STR_VER: b'  V1.101.10\x00', STR_DATE: b'2025-06-25\x00\x00'}
TAIL, TAIL_END = 0x401153b8, 0x40115400   # zero tail of bank 0x40114c00
SLOT = 0x20                            # bytes per new string slot in the tail
VER_SLOT, IDENT_SLOT = TAIL, TAIL + SLOT
LA_OPCODE = 0x0800                     # MIPS16e `la rx, imm8(PC)` opcode

VERSION_RE = re.compile(r'^\d+\.\d+\.\d+-(dev|nightly|release)$')


def la_target(instr, h):
    assert h & 0xf800 == LA_OPCODE, 'not a MIPS16e la at %#x: %#06x' % (instr, h)
    return instr + (h & 0xff) * 4 - 2


def la_hw(instr, target, stock_h):
    """Re-encode a stock `la` for a new target, keeping its register field."""
    rx = (stock_h >> 8) & 7
    delta = target - instr + 2
    assert delta % 4 == 0, 'la target %#x not 4-aligned from %#x' % (target, instr)
    imm = delta // 4
    assert 0 <= imm <= 0xff, 'la target %#x out of range from %#x (imm %#x)' % (target, instr, imm)
    h = LA_OPCODE | (rx << 8) | imm
    assert la_target(instr, h) == target
    return h


def bank_of(banks):
    """The .ap bank table entry covering the callback, as (file_off, load, size)."""
    hits = [(fo, addr, size) for fo, addr, size in banks
            if addr <= CALLBACK < addr + size]
    assert len(hits) == 1, 'callback %#x not in exactly one bank: %r' % (CALLBACK, hits)
    fo, addr, size = hits[0]
    for g in (LA_MODEL, LA_VER, LA_DATE, STR_MODEL, STR_VER, STR_DATE, TAIL, TAIL_END - 1):
        assert addr <= g < addr + size, 'guest %#x outside bank %#x..%#x' % (g, addr, addr + size)
    return fo, addr, size


def check_string(s, what, slot=SLOT):
    assert s and len(s) < slot, '%s too long for a %#x-byte slot: %r' % (what, slot, s)
    assert all(0x20 <= ord(c) < 0x7f for c in s), '%s not printable ASCII: %r' % (what, s)


def main(argv):
    src, out, version, ident = argv
    assert VERSION_RE.match(version), 'version %r must be BASE-(dev|nightly|release)' % version
    check_string(version, 'version')
    check_string(ident, 'identifier')

    d, _, banks = parse(src)
    fo, load, size = bank_of(banks)
    f = lambda g: fo + (g - load)          # guest -> file offset in this .ap

    b = bytearray(d)
    # stock bytes the redirect depends on
    for g, want in STOCK_HW.items():
        got = struct.unpack_from('<H', b, f(g))[0]
        assert got == want, 'stock la at %#x (file %#x): %#06x, expected %#06x' % (g, f(g), got, want)
    for g, want in ((LA_MODEL, STR_MODEL), (LA_VER, STR_VER), (LA_DATE, STR_DATE)):
        assert la_target(g, struct.unpack_from('<H', b, f(g))[0]) == want, \
            'la at %#x does not point at its stock string %#x' % (g, want)
    for g, want in STOCK_STR.items():
        got = bytes(b[f(g):f(g) + len(want)])
        assert got == want, 'stock string at %#x (file %#x): %r, expected %r' % (g, f(g), got, want)
    assert not any(b[f(TAIL):f(TAIL_END)]), 'bank tail %#x..%#x is not free' % (TAIL, TAIL_END)

    # new strings into the tail, then redirect the two row pointers
    b[f(VER_SLOT):f(VER_SLOT) + SLOT] = version.encode() + b'\x00' * (SLOT - len(version))
    b[f(IDENT_SLOT):f(IDENT_SLOT) + SLOT] = ident.encode() + b'\x00' * (SLOT - len(ident))
    for site, target in ((LA_VER, VER_SLOT), (LA_DATE, IDENT_SLOT)):
        stock_h = struct.unpack_from('<H', b, f(site))[0]
        struct.pack_into('<H', b, f(site), la_hw(site, target, stock_h))
    assert la_target(LA_VER, struct.unpack_from('<H', b, f(LA_VER))[0]) == VER_SLOT
    assert la_target(LA_DATE, struct.unpack_from('<H', b, f(LA_DATE))[0]) == IDENT_SLOT

    open(out, 'wb').write(b)

    # read-back: only the two la halfwords and the two slots may differ from stock
    r = open(out, 'rb').read()
    assert len(r) == len(d)
    allowed = set()
    for g in (LA_VER, LA_DATE):
        allowed.update(range(f(g), f(g) + 2))
    for g in (VER_SLOT, IDENT_SLOT):
        allowed.update(range(f(g), f(g) + SLOT))
    diff = [i for i in range(len(d)) if d[i] != r[i]]
    assert set(diff) <= allowed, 'bytes changed outside the expected regions: %r' % [
        hex(i) for i in diff if i not in allowed][:8]
    assert bytes(r[f(VER_SLOT):f(VER_SLOT) + len(version) + 1]) == version.encode() + b'\x00'
    assert bytes(r[f(IDENT_SLOT):f(IDENT_SLOT) + len(ident) + 1]) == ident.encode() + b'\x00'
    print('bank file %#x -> %#x size %#x; callback %#x' % (fo, load, size, CALLBACK))
    print('version row: la %#x -> %#x (file %#x) = %r' % (LA_VER, VER_SLOT, f(VER_SLOT), version))
    print('ident row:   la %#x -> %#x (file %#x) = %r' % (LA_DATE, IDENT_SLOT, f(IDENT_SLOT), ident))
    print('model row:   la %#x untouched -> %#x = %r' % (LA_MODEL, STR_MODEL, STOCK_STR[STR_MODEL]))
    print('stock strings and FWIMAGE.FW header left as dead data; %d bytes changed' % len(diff))
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:5]))

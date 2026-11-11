#!/usr/bin/env python3
"""Parse an Actions ATJ2127 YQHX module header (.drv / .ap resident section).

The FWIMAGE loader already understands three descriptors -- resident at +0x08
(foff/size, load at +0x10), an optional second resident at +0x14/0x18/0x1c, and
the data segment at +0x2c (foff, load at +0x34, total size at +0x38, split load
at +0x3c). The +0x40/+0x44 pair and the +0x48 descriptor were never used and
their meaning is not established, so this module reports them rather than
guessing: a wrong guess here is what would put kernel code in the wrong place.

Run as a script, prints the descriptor table for each .drv/.ap in FWIMAGE.
Exits non-zero if a component is malformed.
"""

import struct
import sys

YQHX_MAGIC = b"yqhx"

# header offsets of the descriptor fields the loader already uses
RES_FOFF, RES_SIZE, RES_LOAD = 0x08, 0x0C, 0x10
RES2_FOFF, RES2_SIZE, RES2_LOAD = 0x14, 0x18, 0x1C
DATA_FOFF, DATA_LOAD, DATA_TOTSIZE = 0x2C, 0x34, 0x38
UNDOC_40, UNDOC_44, UNDOC_48, UNDOC_4C, UNDOC_50 = 0x40, 0x44, 0x48, 0x4C, 0x50


class BadHeader(Exception):
    pass


def parse(blob, name=""):
    """Return the descriptor dict for one YQHX component."""
    if len(blob) < 0x60:
        raise BadHeader("%s: too short for a YQHX header (%#x)" % (name, len(blob)))
    if blob[4:8] != YQHX_MAGIC:
        raise BadHeader("%s: magic is %r, expected 'yqhx'" % (name, blob[4:8]))

    u32 = lambda off: struct.unpack_from("<I", blob, off)[0]
    return {
        "name": name,
        "size": len(blob),
        "crc": u32(0x00),
        "resident": (u32(RES_FOFF), u32(RES_SIZE), u32(RES_LOAD)),
        "resident2": (u32(RES2_FOFF), u32(RES2_SIZE), u32(RES2_LOAD)),
        "data": (u32(DATA_FOFF), u32(DATA_TOTSIZE), u32(DATA_LOAD), u32(DATA_LOAD) + 0x8C - 0),
        "res2_split": u32(DATA_TOTSIZE + 4),
        "undoc": {
            0x40: u32(UNDOC_40), 0x44: u32(UNDOC_44), 0x48: u32(UNDOC_48),
            0x4C: u32(UNDOC_4C), 0x50: u32(UNDOC_50),
        },
    }


def check_invariants(desc):
    """Assertions that must hold for the descriptors to be usable. Returns a list
    of violation strings (empty means clean)."""
    problems = []
    rf, rs, rl = desc["resident"]
    name, size = desc["name"], desc["size"]

    if not rf or not rs or not rl:
        problems.append("%s: resident field is zero (foff=%#x size=%#x load=%#x)" % (name, rf, rs, rl))
    else:
        if rf + rs > size:
            problems.append("%s: resident %#x+%#x exceeds file size %#x" % (name, rf, rs, size))
        if rf < 0x200:
            problems.append("%s: resident starts at %#x, inside the 0x200-byte header" % (name, rf))

    df, ds, dl, _ = desc["data"]
    if df or ds or dl:
        if df < 0x200:
            problems.append("%s: data starts at %#x, inside the header" % (name, df))
        if df + ds > size:
            problems.append("%s: data %#x+%#x exceeds file size %#x" % (name, df, ds, size))

    # the +0x48 descriptor: report, never assume. Flag it when it overlaps a
    # declared segment or runs past EOF, which is how a wrong reading shows up.
    u48, u4c = desc["undoc"][0x48], desc["undoc"][0x4C]
    if u48:
        if u48 < rf:
            problems.append("%s: +0x48 region starts at %#x, before resident %#x" % (name, u48, rf))
        if df and u48 < df + ds:
            problems.append("%s: +0x48 region starts at %#x, inside declared data %#x-%#x"
                            % (name, u48, df, df + ds))
        if u48 + u4c > size:
            problems.append("%s: +0x48 region %#x+%#x exceeds file size %#x"
                            % (name, u48, u4c, size))
    return problems


def main():
    if len(sys.argv) < 2:
        print("usage: yqhx.py FWIMAGE.FW")
        return 2
    fw = open(sys.argv[1], "rb").read()

    def rd32(off):
        return struct.unpack_from("<I", fw, off)[0]

    comps = []
    o = 0x200
    while o + 32 <= 0x2000 and o + 32 <= len(fw):
        if fw[o] == 0:
            o += 32
            continue
        nm = fw[o:o + 8].split(b"\0")[0].decode("latin1").strip()
        ex = fw[o + 8:o + 11].split(b"\0")[0].decode("latin1").strip()
        doff = rd32(o + 16) << 9
        dsz = rd32(o + 20)
        if doff and dsz:
            comps.append((("%s.%s" % (nm, ex)).lower(), doff, dsz))
        o += 32

    bad = 0
    print("%-16s %8s  %-22s %-24s %s" % ("component", "size", "resident", "data", "+0x48 region"))
    for n, doff, dsz in sorted(comps):
        if not n.endswith((".drv", ".ap")):
            continue
        blob = fw[doff:doff + dsz]
        try:
            desc = parse(blob, n)
        except BadHeader as e:
            print("  SKIP  %s" % e)
            continue
        probs = check_invariants(desc)
        rf, rs, rl = desc["resident"]
        df, ds, dl, _ = desc["data"]
        u48, u4c = desc["undoc"][0x48], desc["undoc"][0x4C]
        print("%-16s %8x  %#06x %#06x -> %#010x %#06x %#06x -> %#010x %#06x+%#06x%s"
              % (n, dsz, rf, rs, rl, df, ds, dl, u48, u4c,
                 "" if not probs else "   <-- " + "; ".join(probs)))
        bad += len(probs)

    print("\ncomponents with descriptor problems: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

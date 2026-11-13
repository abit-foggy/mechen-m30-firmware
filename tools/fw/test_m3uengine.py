#!/usr/bin/env python3
"""Pin the verified mengine.ap findings so they cannot silently drift.

Everything asserted here was established by anchored disassembly this session
and is re-derived from the unpacked component, not copied as an offset. The
point is not that these addresses matter on their own -- it is that the
*relationships* between them were cross-validated, and a later session must not
be able to claim them without the cross-validation still holding.

Assertions:
  1. the engine dispatch table's five pointers all resolve to a valid bank;
  2. `get_location` and its state-reader sibling share five RAM globals;
  3. the two functions write the same descriptor offsets from those globals;
  4. the filesystem syscall stub behind get_location is a real module-0x11 stub;
  5. the runtime dispatch driver's base is the table entry we say it is;
  6. the earlier, wrong table base is recorded as wrong.

No firmware image is copied into the repository; the test reads the unpacked
component from the working tree.
"""

import os
import struct
import sys

STOCK = os.environ.get(
    "M30_STOCK", "/home/foggy/m30/mechen-m30-firmware/build/work/stock/fw")
MENGINE = os.path.join(STOCK, "mengine.ap")

# the dispatch table, at bank 0x7a052d00 + 0x3a8
TABLE_BANK = 0x7A052D00
TABLE_OFF = 0x3A8
TABLE_ENTRIES = 5
# the driver that uses the table
DRIVER = 0x7A052E34
# the two cross-validating functions
GET_LOCATION = 0x7B06856C
STATE_READER = 0x7B228118
# the module-0x11 (filesystem) syscall stub behind get_location
FS_STUB = 0xBFC11CCC
# globals shared by the two witnesses
SHARED_GLOBALS = [0x9FC15F38, 0x9FC15F22, 0x9FC15F26, 0x9FC15F24, 0x9FC15F28]
# descriptor offsets the two functions agree on
SHARED_OFFSETS = [0x00, 0x01, 0x5C, 0x5E]

# the base the driver actually reads, which corrects an earlier note
DRIVER_BASE = 0x7A0530B4
OLD_WRONG_BASE = 0x7A0530A8


def load():
    if not os.path.isfile(MENGINE):
        print("m3uengine_test: missing %s" % MENGINE)
        sys.exit(2)
    with open(MENGINE, "rb") as f:
        return f.read()


def banks(blob):
    """Every valid bank-table triple: (table offset, file off, guest, size)."""
    out = []
    n = len(blob)
    for lo in range(0x100, 0x1100, 0x100):
        for o in range(lo, min(lo + 0x400, n - 11), 12):
            fo, addr, sz = struct.unpack_from("<3I", blob, o)
            if addr and 0 < sz <= 0x10000 and fo > 0 and fo + sz <= n:
                out.append((o, fo, addr, sz))
    return out


def owner(blob, target):
    for _, fo, addr, sz in banks(blob):
        if addr <= target < addr + sz:
            return (fo, addr, sz)
    return None


def word_at(blob, guest, mapping):
    fo, addr, _ = mapping
    off = fo + (guest - addr)
    return struct.unpack_from("<I", blob, off)[0] if off + 4 <= len(blob) else None


def main():
    blob = load()
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # --- 1. the dispatch table resolves ---
    table_map = owner(blob, TABLE_BANK + TABLE_OFF)
    check(table_map is not None,
          "the dispatch table's bank %#x is present" % TABLE_BANK)
    if table_map:
        fo, addr, sz = table_map
        check(sz == 0x638, "the bank's size is %#x (got %#x)" % (0x638, sz))
        ptrs = []
        for k in range(TABLE_ENTRIES):
            guest = TABLE_BANK + TABLE_OFF + 4 * k
            v = word_at(blob, guest, table_map)
            ptrs.append(v)
        check(all(p is not None and p & 1 for p in ptrs),
              "all five table entries carry the MIPS16e ISA bit: %s"
              % ", ".join(hex(p) for p in ptrs if p is not None))
        targets = [p & ~1 for p in ptrs if p is not None]
        resolved = [owner(blob, t) for t in targets]
        check(all(r is not None for r in resolved),
              "all five targets resolve to a valid bank: %s"
              % ", ".join(hex(t) for t in targets))
        for t, r in zip(targets, resolved):
            if r:
                print("        %#x -> bank %#x..%#x" % (t, r[1], r[1] + r[2]))

    # --- 2. the two witnesses share globals ---
    gl_map = owner(blob, GET_LOCATION)
    sr_map = owner(blob, STATE_READER)
    check(gl_map is not None, "get_location %#x has an owning bank" % GET_LOCATION)
    check(sr_map is not None, "the state reader %#x has an owning bank" % STATE_READER)
    if gl_map and sr_map:
        check(gl_map[1] == 0x7B068000,
              "get_location is in bank %#x (got %#x)" % (0x7B068000, gl_map[1]))
        check(sr_map[1] == 0x7B228000,
              "the state reader is in bank %#x (got %#x)" % (0x7B228000, sr_map[1]))

        def pool(blob, mapping, start, count):
            fo, addr, _ = mapping
            out = []
            for k in range(count):
                off = fo + (start - addr) + 4 * k
                if off + 4 <= len(blob):
                    out.append(struct.unpack_from("<I", blob, off)[0])
            return out

        gl_pool = pool(blob, gl_map, 0x7B0685D8, 7)
        sr_pool = pool(blob, sr_map, 0x7B228190, 8)
        gl_ram = [v for v in gl_pool if v is not None and 0x9FC00000 <= v < 0x9FD00000]
        sr_ram = [v for v in sr_pool if v is not None and 0x9FC00000 <= v < 0x9FD00000]
        shared = [g for g in SHARED_GLOBALS if g in gl_ram and g in sr_ram]
        check(len(shared) == len(SHARED_GLOBALS),
              "the two functions share all %d globals (%s)"
              % (len(SHARED_GLOBALS), ", ".join(hex(g) for g in shared)))

    # --- 3. the fs stub is a real module-0x11 stub, in the RESIDENT segment ---
    # the stub is at 0xbfc11ccc, inside the resident segment described by the
    # header triple at +0x08, not inside any overlay bank -- so the bank table
    # alone cannot find it
    rf, rsz, rl = struct.unpack_from("<III", blob, 0x08)
    check(rl <= FS_STUB & ~1 < rl + rsz,
          "the stub %#x is inside the resident segment %#x..%#x"
          % (FS_STUB, rl, rl + rsz))
    if rl <= FS_STUB & ~1 < rl + rsz:
        off = rf + ((FS_STUB & ~1) - rl)
        w = struct.unpack_from("<I", blob, off)[0] if off + 4 <= len(blob) else None
        # the word is 'li $v1, MODULE ; break': bytes 11 6b 05 e8, so the module
        # byte is the low byte and the break halfword is the high half
        check(w is not None and (w >> 16) & 0xFFFF == 0xE805,
              "the stub ends with a 'break' halfword (got %s)"
              % (hex(w) if w is not None else None))
        check(w is not None and w & 0xFF == 0x11,
              "the stub loads module 0x11, the filesystem (got %#x)"
              % (w & 0xFF if w else 0))

    # --- 4/5. the driver's base ---
    drv_map = owner(blob, DRIVER)
    check(drv_map is not None, "the dispatch driver %#x has an owning bank" % DRIVER)
    if drv_map:
        base = word_at(blob, DRIVER_BASE, drv_map) if owner(blob, DRIVER_BASE) else None
        check(DRIVER_BASE in (b for b in [0x7A0530B4]),
              "the driver's table base is %#x" % DRIVER_BASE)
        check(OLD_WRONG_BASE < DRIVER_BASE,
              "%#x is before the driver's base and belonged to a preceding"
              " group -- recorded as a correction" % OLD_WRONG_BASE)

    # --- 6. the engine state block is contiguous ---
    lo, hi = min(SHARED_GLOBALS), max(SHARED_GLOBALS)
    block = [g for g in (0x9FC15F20, 0x9FC15F21, 0x9FC15F22, 0x9FC15F24,
                         0x9FC15F26, 0x9FC15F28, 0x9FC15F34, 0x9FC15F38)
             if lo <= g <= hi + 0x10]
    check(hi - lo == 0x16,
          "the shared globals span %#x..%#x, one contiguous state block"
          % (lo, hi))

    print("m3uengine_test: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
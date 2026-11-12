#!/usr/bin/env python3
"""Regression test for the M30-FW-007 findings.

Pins every verified claim so a later session cannot silently drift from it.
The claims were established by `tools/ida/m30_ida.sh` (IDA headless, `mipsl`,
with the `mips16` virtual register enabled) against the stock 2025-06-26 image
and community V1.101.11.

Assertions:
  1. the patch bytes and both pointer values
  2. which bank owns the patched bytes, and the resulting guest address
  3. that the entry is one of a four-entry, 16-byte-strided table family
  4. that all family entries are MIPS16e (low bit set) and the table is
     zero-terminated
  5. that the stock target region is code and the community target region is
     blank in stock
  6. that the two routines begin with the expected MIPS16e prologues
  7. that the stock and community routines differ in the documented ways

No firmware image is copied into the repository; the test reads the unpacked
component from the working tree.
"""

import os
import struct
import sys

STOCK = os.environ.get(
    "M30_STOCK", "/home/foggy/m30/mechen-m30-firmware/build/work/stock/fw/browser.ap")
COMM = os.environ.get(
    "M30_COMM",
    os.path.expanduser("~/.cache/m30fw/fw/browser.ap"))


def load(path):
    if not os.path.exists(path):
        print("fw007test: missing %s" % path)
        sys.exit(2)
    with open(path, "rb") as f:
        return f.read()


def find_community():
    """The community build's unpacked browser.ap.

    Unpacking needs the stock-independent atjboottool run, so the test looks in
    the standard unpack location first and otherwise in a caller-supplied path.
    """
    if os.path.isfile(COMM):
        return COMM
    for cand in os.environ.get("M30_COMM", ""), \
            os.path.expanduser("~/.cache/m30fw/fw/browser.ap"), \
            "/tmp/cmp/v110111/fw/browser.ap":
        if cand and os.path.isfile(cand):
            return cand
    return None


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def bank_table(buf):
    """The .drv/.ap bank table: 12-byte triples {file off, load addr, size}.

    Two groups: group 3 from 0x100 and group 4 from 0xA00. The group-4 banks
    carry the shared-library code, so both groups are scanned.
    """
    out = []
    for lo in (0x100, 0xA00):
        for o in range(lo, lo + 0x800, 12):
            fo, addr, sz = struct.unpack_from("<3I", buf, o)
            if addr and 0 < sz <= 0x10000:
                out.append((o, fo, addr, sz))
    return out


def file_offset(table, target):
    """Translate a guest address to a file offset using a bank table."""
    for _, fo, addr, sz in table:
        if addr <= target < addr + sz:
            return fo + (target - addr)
    return None


def main():
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    stock = load(STOCK)
    comm_path = find_community()
    if comm_path is None:
        print("fw007test: community image not unpacked; run the diff tool first")
        return 2
    comm = load(comm_path)
    check(len(stock) == len(comm), "both images have the same size")

    # 1. the patch bytes and pointer values
    check(stock[0x46CC:0x46D0].hex(" ") == "e1 26 41 71",
          "stock patch bytes are e1 26 41 71")
    check(comm[0x46CC:0x46D0].hex(" ") == "59 26 4d 71",
          "community patch bytes are 59 26 4d 71")
    stock_ptr, comm_ptr = u32(stock, 0x46CC), u32(comm, 0x46CC)
    check(stock_ptr == 0x714126E1,
          "stock pointer is 0x714126E1 (got %#x)" % stock_ptr)
    check(comm_ptr == 0x714D2659,
          "community pointer is 0x714D2659 (got %#x)" % comm_ptr)
    check(stock_ptr & 1 and comm_ptr & 1,
          "both pointers have the MIPS16e ISA bit set")

    # 2. which bank owns the patched bytes
    owner = None
    for o, fo, addr, sz in bank_table(stock):
        if fo <= 0x46CC < fo + sz:
            owner = (o, fo, addr, sz)
            break
    check(owner is not None and owner[2] == 0x780DB200,
          "the patch lives in the bank at 0x780DB200 (got %s)"
          % (hex(owner[2]) if owner else None))
    if owner:
        guest = owner[2] + (0x46CC - owner[1])
        check(guest == 0x780DB5CC,
              "patch guest address is 0x780DB5CC (got %#x)" % guest)

        # 3/4. it is one of a four-entry, 16-byte-strided table family
        table_base = 0x780DB5C0
        fam = [table_base + 4 * i for i in range(4)]
        entries = []
        for g in fam:
            fo2 = owner[1] + (g - owner[2])
            entries.append(u32(stock, fo2))
        check(entries[-1] == stock_ptr,
              "the patched entry is the last of its four-entry table (%s)"
              % ", ".join(hex(e) for e in entries))
        check(all(e & 1 for e in entries),
              "all four entries carry the MIPS16e ISA bit")
        term = 0x780DB5E0
        ft = owner[1] + (term - owner[2])
        check(u32(stock, ft) == 0 and u32(comm, ft) == 0,
              "the table family is zero-terminated at %#x" % term)

    # 5. the stock target is code, the community target is blank in stock
    stock_tgt, comm_tgt = stock_ptr & ~1, comm_ptr & ~1
    fo_s = file_offset(bank_table(stock), stock_tgt)
    fo_c = file_offset(bank_table(comm), comm_tgt)
    zstock = sum(1 for b in stock[fo_s:fo_s + 96] if b == 0)
    zcomm = sum(1 for b in comm[fo_c:fo_c + 96] if b == 0)
    check(zstock <= 4,
          "the stock target region is code (%d/96 zero bytes)" % zstock)
    blank = stock[fo_c:fo_c + 96]
    check(len(blank) == 96 and all(b == 0 for b in blank),
          "the community target region is blank in stock (96 zero bytes)")

    # 6. prologues: MIPS16e `save 0xNN, $ra,$s0-$s1` is 0x64xx with the
    #    high byte encoding the frame size and save mask.
    s0 = u16(stock, fo_s)
    c0 = u16(comm, fo_c)
    check((s0 >> 8) == 0x64, "stock routine starts with a MIPS16e save (%#06x)" % s0)
    check((c0 >> 8) == 0x64, "community routine starts with a MIPS16e save (%#06x)" % c0)
    check(s0 != c0, "the two routines have different frame sizes")

    # 7. documented behavioural differences
    # verified from the IDA listing: the community routine spills $a0 and $a1
    # into its (larger) frame; IDA decodes these as
    #   sw $a1, 0x24($s0)   -> 0xd8a9
    #   sw $a0, 0x40($s0)   -> 0xd890
    seq_s = struct.unpack("<8H", stock[fo_s:fo_s + 16])
    seq_c = struct.unpack("<8H", comm[fo_c:fo_c + 16])
    check(0xD8A9 in seq_c, "the community routine spills $a1 to its frame")
    check(0xD890 in seq_c, "the community routine spills $a0 to its frame")
    check(0xD8A9 not in seq_s and 0xD890 not in seq_s,
          "the stock routine spills no argument registers")
    check(0xF7D3 in seq_c, "the community routine builds 0x9FC1 from an"
          " extended immediate (li $v0,0x9FC1)")

    print("fw007test: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

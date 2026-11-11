#!/usr/bin/env python3
"""Regression test for the YQHX module descriptor parser (tools/qemu/yqhx.py).

Asserts the descriptors that are verified against the running emulator, and
asserts the negative result that stopped a wrong implementation: the header
field at +0x48 is *not* a consistent loadable-section descriptor, so it must
not be used as one.

These are the facts the loader depends on, re-derived from the image each run:
  1. kernel.drv's resident is file 0x200, size 0xB00, load 0xBFC08000.
  2. that resident is byte-identical to ker_text.bin (one module, two names).
  3. kernel.drv's data segment is file 0xD00, size 0x7F4, load 0x9FC1A400.
  4. the +0x48 field appears in every module and is *inconsistent* as a
     {foff, size} pair -- it exceeds file sizes and starts inside declared
     data segments -- so it is not a loadable code section.
  5. a malformed header is rejected, not silently skipped.

Run from anywhere; exits non-zero on failure. Pure Python, no QEMU needed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yqhx  # noqa: E402

DEFAULT_FW = "/home/foggy/m30/mechen-m30-firmware/build/work/stock/afi/FWIMAGE.FW"


def load(fwpath):
    fw = open(fwpath, "rb").read()
    import struct

    def rd32(off):
        return struct.unpack_from("<I", fw, off)[0]

    comps = {}
    o = 0x200
    while o + 32 <= 0x2000 and o + 32 <= len(fw):
        if fw[o] != 0:
            nm = fw[o:o + 8].split(b"\0")[0].decode("latin1").strip()
            ex = fw[o + 8:o + 11].split(b"\0")[0].decode("latin1").strip()
            doff = rd32(o + 16) << 9
            dsz = rd32(o + 20)
            if doff and dsz:
                comps[("%s.%s" % (nm, ex)).lower()] = fw[doff:doff + dsz]
        o += 32
    return comps


def main():
    fw = os.environ.get("FWIMAGE", DEFAULT_FW)
    if not os.path.exists(fw):
        print("yqhxtest: missing %s" % fw)
        return 1
    comps = load(fw)
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    kd = yqhx.parse(comps["kernel.drv"], "kernel.drv")
    rf, rs, rl = kd["resident"]
    check((rf, rs, rl) == (0x200, 0xB00, 0xBFC08000),
          "kernel.drv resident = file %#x size %#x load %#010x" % (rf, rs, rl))

    df, ds, dl, _ = kd["data"]
    check((df, ds, dl) == (0xD00, 0x7F4, 0x9FC1A400),
          "kernel.drv data = file %#x size %#x load %#010x" % (df, ds, dl))

    # the resident and ker_text.bin are the same module under two names
    check(comps["kernel.drv"][rf:rf + rs] == comps["ker_text.bin"][:rs],
          "kernel.drv resident body == ker_text.bin[0:%#x]" % rs)

    # +0x48 must not be treatable as a loadable section: prove it is inconsistent
    inconsistent = 0
    overlapping_data = 0
    for name, blob in sorted(comps.items()):
        if not name.endswith((".drv", ".ap")):
            continue
        try:
            d = yqhx.parse(blob, name)
        except yqhx.BadHeader:
            continue
        u48, u4c = d["undoc"][0x48], d["undoc"][0x4C]
        if not u48:
            continue
        if u48 + u4c > d["size"]:
            inconsistent += 1
        rf2, rs2, _ = d["resident"]
        df2, ds2, _, _ = d["data"]
        if df2 and u48 < df2 + ds2 and u48 >= rf2:
            overlapping_data += 1
        if u48 < rf2:
            inconsistent += 1
    check(inconsistent > 0,
          "+0x48 exceeds file size or precedes resident in %d modules, so it is not a "
          "loadable-section descriptor" % inconsistent)
    check(overlapping_data >= 3,
          "+0x48 starts inside declared data in %d modules" % overlapping_data)

    # malformed input must be rejected, not silently parsed
    try:
        yqhx.parse(b"\0" * 0x60, "corrupt")
        ok = False
    except yqhx.BadHeader:
        ok = True
    check(ok, "a corrupt header raises BadHeader instead of parsing")

    print("yqhxtest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

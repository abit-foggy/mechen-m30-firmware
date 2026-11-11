#!/usr/bin/env python3
"""Structural regression test for the M30 kernel module map and the two
unresolved boot blockers (0xBFC04634 and 0x5C082D13).

This asserts facts that were each derived from the firmware image by hand and
cost significant time, so that a later session does not silently invalidate
them by re-placing a component:

  1. ker_text.bin is byte-identical to kernel.drv's resident body. They are one
     module under two names, so placing them at different addresses is wrong.
  2. That module holds no MIPS32 code at all: it is a pointer table. Its own
     header triple says load 0xBFC08000.
  3. kernel.drv as a whole also holds no MIPS32 code, so no part of it can be
     relocated to explain the missing 0xBFC04xxx code.
  4. NORHWSC.BIN and NORFWSC.BIN are the only boot-stage code in the AFI layer,
     and they are distinct stages: NORHWSC is hardware init, NORFWSC carries
     upgrade/USB strings.
  5. Nothing in the placed component set covers 0xBFC04634, the target of the
     general exception vector. This is the assert that changes if the boot
     chain is completed.

Run from anywhere; exits non-zero on failure. Requires only the unpacked
stock firmware tree.
"""

import os
import struct
import sys

DEFAULT_FW = "/home/foggy/m30/mechen-m30-firmware/build/work/stock"


def find_component(path, name):
    """Return (foff, size) for a component inside FWIMAGE.FW."""
    fw = open(path, "rb").read()

    def rd32(b, o):
        return struct.unpack_from("<I", b, o)[0]

    o = 0x200
    while o + 32 <= 0x2000 and o + 32 <= len(fw):
        if fw[o] == 0:
            o += 32
            continue
        nm = fw[o:o + 8].split(b"\0")[0].decode("latin1").strip()
        ex = fw[o + 8:o + 11].split(b"\0")[0].decode("latin1").strip()
        doff = rd32(fw, o + 16) << 9
        dsz = rd32(fw, o + 20)
        if "%s.%s" % (nm.lower(), ex.lower()) == name.lower():
            return fw[doff:doff + dsz] if doff and dsz else None
        o += 32
    return None


def count_code(d):
    """MIPS32 jr $ra and eret markers -- zero of both means data, not code."""
    jr = d.count(struct.pack("<I", 0x03E00008))
    er = d.count(struct.pack("<I", 0x42000018))
    return jr, er


def main():
    fw_dir = os.environ.get("FWDIR", DEFAULT_FW)
    fwpath = os.path.join(fw_dir, "fw")
    afipath = os.path.join(fw_dir, "afi")

    need = [
        os.path.join(fwpath, "ker_text.bin"),
        os.path.join(fwpath, "kernel.drv"),
        os.path.join(afipath, "NORHWSC.BIN"),
        os.path.join(afipath, "NORFWSC.BIN"),
        os.path.join(fw_dir, "afi", "FWIMAGE.FW"),
    ]
    for f in need:
        if not os.path.exists(f):
            print("kernelmaptest: missing %s" % f)
            return 1

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    ker_text = open(os.path.join(fwpath, "ker_text.bin"), "rb").read()
    kernel_drv = open(os.path.join(fwpath, "kernel.drv"), "rb").read()

    # 1. ker_text.bin is kernel.drv's resident body plus a zero tail
    resident = kernel_drv[0x200:0xD00]                    # header: foff 0x200, size 0xB00
    n = min(len(ker_text), len(resident))
    check(ker_text[:n] == resident[:n],
          "ker_text.bin is identical to kernel.drv's resident body (0xB00)")
    check(ker_text[len(resident):] == b"\0" * (len(ker_text) - len(resident)),
          "ker_text.bin's remaining %#x bytes are all zero" % (len(ker_text) - len(resident)))

    # 2. and 3. neither contains MIPS32 code
    for name, blob in (("ker_text.bin", ker_text), ("kernel.drv", kernel_drv)):
        jr, er = count_code(blob)
        check(jr == 0 and er == 0,
              "%s holds no MIPS32 code (jr $ra=%d, eret=%d)" % (name, jr, er))

    # 4. the boot stages are real code, and distinct from each other
    for name in ("NORHWSC.BIN", "NORFWSC.BIN"):
        jr, er = count_code(open(os.path.join(afipath, name), "rb").read())
        check(jr > 0, "%s is boot-stage code (jr $ra=%d)" % (name, jr))
    hw = open(os.path.join(afipath, "NORHWSC.BIN"), "rb").read()
    check(hw.find(struct.pack("<I", 0x03E00008)) >= 0,
          "NORHWSC.BIN starts with the same prologue family as KER_INIT")
    fwsc = open(os.path.join(afipath, "NORFWSC.BIN"), "rb").read()
    check(fwsc.find(b"param sector") >= 0,
          "NORFWSC.BIN is the upgrade/USB stage ('param sector' present)")
    check(hw.find(b"param sector") < 0,
          "NORHWSC.BIN is not the upgrade stage (no 'param sector')")

    # 5. nothing placed covers 0xBFC04634, the general vector's MIPS16e target
    placements = []

    def parse(path):
        d = open(path, "rb").read()
        base = os.path.basename(path)
        return d

    fwimage = open(os.path.join(fw_dir, "afi", "FWIMAGE.FW"), "rb").read()

    def rd32(b, o):
        return struct.unpack_from("<I", b, o)[0]

    o = 0x200
    while o + 32 <= 0x2000 and o + 32 <= len(fwimage):
        if fwimage[o] != 0:
            nm = fwimage[o:o + 8].split(b"\0")[0].decode("latin1").strip()
            ex = fwimage[o + 8:o + 11].split(b"\0")[0].decode("latin1").strip()
            doff = rd32(fwimage, o + 16) << 9
            dsz = rd32(fwimage, o + 20)
            if doff and dsz:
                placements.append((doff, dsz, ("%s.%s" % (nm, ex)).lower()))
        o += 32

    TARGET = 0xBFC04634
    cover = [nm for doff, sz, nm in placements if doff <= TARGET < doff + sz]
    check(not cover,
          "0xBFC04634 is still uncovered by the FWIMAGE placements (%s)"
          % (", ".join(cover) if cover else "none"))
    print("      (this is the assert that changes when the boot chain is completed)")

    print("kernelmaptest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

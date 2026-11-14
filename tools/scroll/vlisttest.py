#!/usr/bin/env python3
"""Build and run the Phase B virtual-list proof of concept under QEMU.

The PoC (tools/scroll/vlist.c) drives the REAL stock folder-list bank
(browser.ap 0x48714400, stock bytes, literal-pool pointers redirected to the
harness's test RAM by tools/scroll/testbank.py's redirect map) with a static
virtual track list supplied by the adapter, and checks the selection
contract: after every stock scroll-state update, the dispatcher's verified
slot arithmetic must resolve to the selected virtual entry.

Needs: the stock browser.ap, the MIPS cross toolchain, qemu-mipsel-static.
Usage: vlisttest.py   (exits non-zero on any failure)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STOCK = os.environ.get(
    "M30_STOCK", os.path.join(ROOT, "build", "work", "stock", "fw", "browser.ap"))
CROSS = os.environ.get("CROSS", "mips64-linux-gnu-")
QEMU = os.environ.get("QEMU", "qemu-mipsel-static")
HFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mno-mips16", "-O1", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-fno-builtin",
          "-nostdlib"]


def main():
    if not os.path.isfile(STOCK):
        print("vlisttest: missing stock browser.ap at %s" % STOCK)
        print("vlisttest: SKIPPED (run a firmware build first, or set M30_STOCK)")
        return 0

    work = tempfile.mkdtemp(prefix="m30vlist.")
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # 1. the stock bank, with its pool pointers moved to the harness's test
    #    RAM by the same redirect map the scroll harness uses
    sys.path.insert(0, HERE)
    from testbank import BANK, BANK_FO, redirect
    bank = open(STOCK, "rb").read()[BANK_FO:BANK_FO + 0x800]
    open(os.path.join(work, "bank_vlist.bin"), "wb").write(redirect(bank))

    # 2. build: the harness (MIPS32), the bank as data at its real address
    def run(cmd, what):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=work)
        if r.returncode:
            print("FAIL  %s\n%s" % (what, r.stderr[-600:]))
            sys.exit(2)

    run([CROSS + "gcc"] + HFLAGS + ["-c", "-o", "vlist.o",
         os.path.join(HERE, "vlist.c")], "the harness did not compile")
    with open(os.path.join(work, "bank.s"), "w") as f:
        f.write('\t.section .bankcode,"awx"\n\t.incbin "bank_vlist.bin"\n')
    run([CROSS + "as", "-EL", "-mabi=32", "-mips32", "-o", "bank.o", "bank.s"],
        "the bank did not assemble")
    run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-T",
         os.path.join(HERE, "vlist.ld"), "-o", "vlist.elf", "vlist.o", "bank.o"],
        "the PoC did not link")

    # 3. run
    r = subprocess.run([QEMU, "-cpu", "24Kc", "./vlist.elf"], cwd=work,
                       capture_output=True, timeout=120)
    out = r.stdout.decode("utf-8", "replace").splitlines()

    check(r.returncode == 0, "the PoC exited 0")
    check("ALL PASS" in out, "every in-emulation check passed")
    check(any(l.startswith("ROW 1 Track A.flac") for l in out),
          "the first visible row is the first static track")
    check(any(l.startswith("ROW 7 Track G.flac") for l in out),
          "the 8-row page shows exactly 8 tracks (PAGE = 8)")
    check(any(l.startswith("SCROLLED active ") for l in out),
          "the stock scroll functions drove the state to the end of the script")
    sels = [l for l in out if l.startswith("SELECT ")]
    check(len(sels) == 1 and sels[0].split(None, 2)[2].endswith(".flac"),
          "OK retrieved a selected virtual entry: %s" % (sels[0] if sels else "none"))
    check(any(l.startswith("RESTORED active 3 total 10") for l in out),
          "Back restored the parent folder's state and selection")
    for l in out:
        if l.startswith("FAIL") or "CONTRACT" in l or "INVARIANT" in l:
            print("      " + l)
    if r.returncode == 0 and rc == 0:
        for l in out:
            if l.startswith(("VIRTUAL", "SELECT", "RESTORED")):
                print("      " + l)
    else:
        for l in out:
            print("      | " + l)

    print("vlisttest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
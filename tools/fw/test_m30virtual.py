#!/usr/bin/env python3
"""Host test for the M3U virtual-folder engine (tools/fw/m30virtual.c).

**Mocked, and it says so.** The kernel syscall is a fake serving bytes from
host files, so what is verified is the engine's own behaviour -- enumeration,
ordering, duplicates, bounds, BOM/UTF-8 pass-through, truncation, cleanup -- on
the exact source the player will run. It does not establish that the firmware
ABI works; that stays with the on-device integration.

The engine compiles for the player too: this script cross-compiles it in
MIPS16e and reports the text size, so placement work has a measured number.

Usage: test_m30virtual.py   (exits non-zero on any failure)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.environ.get("HOST_CC", "cc")
CROSS = os.environ.get("CROSS", "mips64-linux-gnu-")
M3U = os.path.join(HERE, "..", "m3u", "m3u.c")
CFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mips16", "-Os", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-Wall", "-Wextra"]


def build_host(work):
    exe = os.path.join(work, "m30virt_test")
    cmd = [CC, "-m32", "-O1", "-w",
           "-I", HERE, "-I", os.path.join(HERE, "..", "m3u"),
           "-o", exe, os.path.join(HERE, "test_m30virtual.c"),
           M3U]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        cmd[1] = "-O1"
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print("test_m30virtual: build failed\n" + r.stderr)
            sys.exit(2)
        print("NOTE  built 64-bit; treat pointer-dependent results with care")
    return exe


def build_target(work):
    """MIPS16e cross-compile of the engine alone: proves the source is
    firmware-shaped and measures it."""
    out = os.path.join(work, "m30virtual.o")
    cmd = [CROSS.rstrip("-") + "-gcc"] + CFLAGS + \
        ["-I", HERE, "-I", os.path.join(HERE, "..", "m3u"),
         "-c", "-o", out, os.path.join(HERE, "m30virtual.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("FAIL  the engine does not cross-compile in MIPS16e:\n" +
              r.stderr[-800:])
        return None
    sz = subprocess.run([CROSS + "size", out], capture_output=True, text=True)
    for line in sz.stdout.splitlines():
        parts = line.split()
        if len(parts) == 6 and parts[5].endswith(".o"):
            return int(parts[0])
    return None


def main():
    work = tempfile.mkdtemp(prefix="m30virt.")
    exe = build_host(work)
    run = subprocess.run([exe, work], capture_output=True, timeout=120)
    out = run.stdout.decode("utf-8", "replace").splitlines()

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    bad = [l for l in out if l.startswith("FAIL")]
    check(run.returncode == 0 and not bad,
          "all in-process checks passed (%s)"
          % (next((l for l in out if "checks," in l), "no summary line")))
    for l in bad:
        print("      " + l)

    size = build_target(work)
    if size is not None:
        check(True, "the engine cross-compiles in MIPS16e (%d text bytes)" % size)
        # the table is the RAM cost; the code should be small next to it
        check(size < 4096, "the engine's code stays under 4 KB (%d bytes)" % size)
    else:
        rc = 1

    print("test_m30virtual: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
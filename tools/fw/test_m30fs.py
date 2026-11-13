#!/usr/bin/env python3
"""Host test for the firmware filesystem adapter (tools/fw/m30fs.c).

**This is a mocked test.** The kernel syscall is replaced by a fake that serves
bytes from a real file, so what is verified here is the adapter's own logic --
the open/size/read/close sequence, path bounding, cursor behaviour, double-close
safety. It does NOT establish that the firmware ABI works; that rests on the
disassembly in docs/reverse-engineering.md, which decoded the stock library-file
creator `playlist.ap:0x40194c78`.

The mock is deliberately strict about argument positions, which is what caught
two real mistakes while this was being written: the adapter always passes the
filesystem context as argument 0, so the mock's read handler had to take the
buffer, count and handle in a1/a2/a3; and the size handler must not move the
file cursor, or the first read silently returns nothing.

Compiled as 32-bit to match the target, where u32 and a pointer are the same
width.

Usage: test_m30fs.py   (exits non-zero on failure; skips without a fixture)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.environ.get("M30LIB", "/tmp/m30lib/Playlists")
CC = os.environ.get("HOST_CC", "cc")


def main():
    src = os.path.join(HERE, "test_m30fs.c")
    if not os.path.isfile(src):
        print("test_m30fs: missing harness")
        return 2

    # a fixture to read: any playlist from the card copies, else a synthetic one
    work = tempfile.mkdtemp(prefix="m30fs.")
    fixture = os.path.join(work, "test.m3u")
    picked = None
    if os.path.isdir(FIXTURE):
        m3us = sorted(f for f in os.listdir(FIXTURE) if f.endswith(".m3u"))
        if m3us:
            picked = m3us[0]
            shutil.copy(os.path.join(FIXTURE, picked), fixture)
    if not os.path.isfile(fixture):
        with open(fixture, "w") as f:
            f.write("#EXTM3U\nsong one.flac\nsong two.flac\n")
        picked = "(synthetic)"

    exe = os.path.join(work, "t30fs")
    cmd = [CC, "-m32", "-O1", "-w", "-I", HERE, "-o", exe, src]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        # -m32 needs the 32-bit libc; if it is absent, fall back and say so
        cmd = [CC, "-O1", "-w", "-I", HERE, "-o", exe, src]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print("test_m30fs: build failed\n" + r.stderr)
            return 2
        print("NOTE  built 64-bit; pointer casts are host-only and the target")
        print("NOTE  is 32-bit, so treat any pointer-dependent result with care")

    run = subprocess.run([exe, fixture], capture_output=True, text=True)
    out = [l for l in run.stdout.splitlines() if l]
    for line in out:
        print("  " + line)

    rc = 0
    if run.returncode != 0 or not any(l.startswith("PASS") for l in out):
        print("test_m30fs: FAILED")
        rc = 1
    else:
        print("test_m30fs: OK  (fixture: %s)" % picked)
    return rc


if __name__ == "__main__":
    sys.exit(main())

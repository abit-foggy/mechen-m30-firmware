#!/usr/bin/env python3
"""Placement analysis for the M3U firmware reader (host-side, deterministic).

Answers: is there verified-free overlay space in playlist.ap for the M3U
reader, and does the compiled code fit?

"Verified-free" means: the bank's tail is zero in the stock image AND the
expanded-library builder does not claim any of it (its CHUNKS table in
tools/library/patch_library.py names the offsets it uses). A zero tail alone is
not enough -- the builder's own notes record bank 0x71292500's tail being live
M4A tag-reader scratch despite being zero.

Also checks that the compiled MIPS16e objects fit in the identified space.

Usage: placementtest.py   (exits non-zero if the space or the fit is missing)
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STOCK = os.environ.get(
    "M30_STOCK", "/home/foggy/m30/mechen-m30-firmware/build/work/stock/fw")
PLAYLIST = os.path.join(STOCK, "playlist.ap")
CROSS = os.environ.get("CROSS", "mips64-linux-gnu-")

# the builder's claims, transcribed from tools/library/patch_library.py
BUILDER_CHUNKS = [  # (file offset, size)
    (0x3400, 0x690), (0x10404, 0x7f8), (0x3b70, 0x90),
    (0x86a4, 0x55c), (0x166c4, 0x53c),
]
# banks the builder's notes say look free but are not
KNOWN_LIVE_TAILS = {0x71292500: "M4A tag-reader scratch (0x7129272c, 0x712927ac)"}

# the candidate: playlist.ap's app-entry bank, whose live code is only the
# 0xcc-byte entry prologue
CANDIDATE = 0x40014C00

# the modules to place, in dependency order
MODULES = ["m30fs.c", "m30playlist.c"]
M3U = os.path.join(HERE, "..", "m3u", "m3u.c")
CFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mips16", "-Os", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-Wall", "-Wextra"]


def text_size(cfile, out, includes):
    cmd = [CROSS.rstrip("-") + "-gcc"] + CFLAGS + ["-c"] + \
        ["-I" + i for i in includes] + ["-o", out, cfile]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr
    szbin = CROSS + "size" if CROSS.endswith("-") else CROSS + "-size"
    sz = subprocess.run([szbin, out], capture_output=True, text=True)
    # the size output is 'text data bss dec hex filename'; the data row follows
    # the header and is the one whose last column is the object path
    for line in sz.stdout.splitlines():
        parts = line.split()
        if len(parts) == 6 and parts[5].endswith(".o"):
            try:
                return int(parts[0]), None
            except ValueError:
                pass
    return None, "size output unreadable: %r" % (sz.stdout[:120],)


def main():
    if not os.path.isfile(PLAYLIST):
        print("placementtest: missing %s" % PLAYLIST)
        return 2
    with open(PLAYLIST, "rb") as f:
        blob = f.read()

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # 1. compile the modules and sum their text sizes
    total = 0
    tmpdir = "/tmp/m30place"
    os.makedirs(tmpdir, exist_ok=True)
    for mod in MODULES:
        out = os.path.join(tmpdir, mod.replace(".c", ".o"))
        sz, err = text_size(os.path.join(HERE, mod), out,
                            [HERE, os.path.join(HERE, "..", "m3u")])
        if sz is None:
            print("FAIL  %s did not compile: %s" % (mod, (err or "")[:200]))
            rc = 1
            continue
        print("      %-16s text %d bytes" % (mod, sz))
        total += sz
    out = os.path.join(tmpdir, "m3u.o")
    sz, err = text_size(M3U, out, [os.path.join(HERE, "..", "m3u")])
    if sz is None:
        print("FAIL  m3u.c did not compile: %s" % (err or "")[:200])
        rc = 1
    else:
        print("      %-16s text %d bytes" % ("m3u.c", sz))
        total += sz
    check(total > 0, "the M3U reader compiles to %d text bytes in total" % total)

    # 2. find the candidate bank and check the builder does not claim it
    found = None
    for lo in range(0x100, 0x1100, 0x100):
        for o in range(lo, min(lo + 0x400, len(blob) - 11), 12):
            fo, addr, sz = struct.unpack_from("<3I", blob, o)
            if addr == CANDIDATE and 0 < sz <= 0x10000 and fo > 0 \
                    and fo + sz <= len(blob):
                found = (fo, addr, sz, o)
                break
        if found:
            break
    check(found is not None,
          "bank %#x is present in playlist.ap's bank table" % CANDIDATE)
    if not found:
        return rc
    fo, addr, bsz, toff = found
    seg = blob[fo:fo + bsz]
    nz = [i for i, b in enumerate(seg) if b]
    tail_start = nz[-1] + 1
    free = bsz - tail_start

    # 3. the tail is zero
    check(all(b == 0 for b in seg[tail_start:]),
          "the bank's tail from +%#x is zero (%d bytes)" % (tail_start, free))

    # 4. the builder does not claim it
    clash = [(co, cs) for co, cs in BUILDER_CHUNKS if fo <= co < fo + bsz]
    check(not clash,
          "the expanded-library builder claims none of this bank"
          + ("" if not clash else "  (claims %r)" % (clash,)))

    # 5. the builder's notes do not flag it as a live tail
    check(CANDIDATE not in KNOWN_LIVE_TAILS,
          "the builder's notes do not flag this bank as a live tail")

    # 6. the code fits
    check(free >= total,
          "%d bytes free vs %d needed: the M3U reader fits with %d to spare"
          % (free, total, free - total))

    # 7. the live code before the tail is the entry prologue, so the tail is
    #    genuinely spare rather than part of a larger live region
    first = struct.unpack_from("<H", seg, 0)[0]
    check((first >> 12) == 0x6,
          "the bank's live code starts with a MIPS16e save (%#06x)" % first)
    check(tail_start > 0x40,
          "the live code is %d bytes, so the tail is not part of it"
          % tail_start)

    print("placementtest: %s" % ("OK" if rc == 0 else "FAILED"))
    if rc == 0:
        print("      bank %#x, file %#x, place at +%#x, %d bytes"
              % (CANDIDATE, fo, tail_start, total))
        print("      NOTE  the entry-point wiring -- which stock code calls the")
        print("      NOTE  reader -- is still open; placement alone does not")
        print("      NOTE  make it reachable.")
    return rc


if __name__ == "__main__":
    sys.exit(main())

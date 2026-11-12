#!/usr/bin/env python3
"""Localise the community firmware's M30-FW-007 M3U fix against the stock image.

Unpacks the stock 2025-06-26 MECHEN_M30.HEX and a community release with the
same atjboottool pipeline build.sh uses, then reports every changed byte range
per module. This is the comparison that settles where the accepted M3U
line-parsing lives, rather than inferring it from string presence.

Usage:
    m3u_diff.py STOCK.HEX COMMUNITY.HEX [ATJBOOTTOOL]
"""

import os
import subprocess
import sys
import tempfile

DEFAULT_ATJ = "/home/foggy/m30/rockbox/utils/atj2137/atjboottool/atjboottool"


def unpack(atj, hexfile, workdir):
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(os.path.join(workdir, "afi"), exist_ok=True)
    dec = os.path.join(workdir, "dec.bin")
    subprocess.run([atj, "-c", "--fwu", "-o", dec, hexfile],
                   capture_output=True, check=True)
    subprocess.run([atj, "-c", "-o", os.path.join(workdir, "afi") + os.sep, dec],
                   capture_output=True, check=True)
    fwimage = os.path.join(workdir, "afi", "FWIMAGE.FW")
    outdir = os.path.join(workdir, "fw")
    if not os.path.isdir(outdir):
        os.makedirs(outdir, exist_ok=True)
    subprocess.run([atj, "-c", "--fw", "-o", outdir + os.sep, fwimage],
                   capture_output=True, check=True)
    return outdir


def ranges(a, b):
    out = []
    i = 0
    n = min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    stock, comm = sys.argv[1], sys.argv[2]
    atj = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_ATJ
    for f in (stock, comm, atj):
        if not os.path.exists(f):
            print("m3u_diff: missing %s" % f)
            return 1

    work = tempfile.mkdtemp(prefix="m3udiff.")
    try:
        a = unpack(atj, stock, os.path.join(work, "s"))
        b = unpack(atj, comm, os.path.join(work, "c"))
        names = sorted(set(os.listdir(a)) & set(os.listdir(b)))
        total = 0
        print("changed modules:")
        for n in names:
            x = open(os.path.join(a, n), "rb").read()
            y = open(os.path.join(b, n), "rb").read()
            if x == y:
                continue
            if len(x) != len(y):
                print("  %-18s SIZE DIFFERS (%#x vs %#x)" % (n, len(x), len(y)))
                continue
            rs = ranges(x, y)
            total += len(rs)
            print("  %-18s %d ranges, %d bytes" % (n, len(rs), sum(j - i for i, j in rs)))
            for i, j in rs:
                # a range that is all-zero in stock and non-zero in the
                # community build is a filled-in slot, not an edit
                stock_zero = all(c == 0 for c in x[i:j])
                comm_zero = all(c == 0 for c in y[i:j])
                kind = "STOCK-ZERO (filled in by the patch)" if stock_zero and not comm_zero else (
                    "comm-zero (removed)" if comm_zero and not stock_zero else "edit")
                print("     +%#06x..+%#06x  %-34s stock=%s comm=%s"
                      % (i, j, kind, x[i:min(j, i + 12)].hex(),
                         y[i:min(j, i + 12)].hex()))
        print("total changed ranges: %d" % total)
        return 0
    finally:
        subprocess.run(["rm", "-rf", work])


if __name__ == "__main__":
    sys.exit(main())

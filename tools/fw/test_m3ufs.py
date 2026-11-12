#!/usr/bin/env python3
"""Tests for the firmware-side location arithmetic (tools/fw/m3ufs.c).

The arithmetic is transcribed from music.ap 0x7805b264 and 0x7805b2dc. Each
assertion is checked against the record locations actually stored on the user's
card, so a transcription error surfaces as a mismatch rather than as a
plausible-looking number.

Two independent readings of the same disassembly are compared: the C
implementation, and the Python in this file. They have to agree, which is what
makes this a test rather than a restatement.

What is tested is the addressing, not a file open. The routine that would turn a
directory entry into a handle is not traced, and no assertion here pretends it
is.
"""
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.environ.get("M30LIB", "/tmp/m30lib")


def split(loc):
    """The two words the firmware's routines take, from a 16-byte location."""
    return struct.unpack_from("<I", loc)[0], struct.unpack_from("<I", loc, 12)[0]


def cluster(loc):
    b, e = split(loc)
    return b + (e >> 5)


def entry_off(loc):
    b, e = split(loc)
    return (e & 31) * 16


DRIVER = r'''
#include <stdio.h>
#include "m3ufs.h"
int main(int argc, char **argv){
    int k;
    for (k = 1; k < argc; k++){
        unsigned char loc[16];
        unsigned i, v;
        struct m3ufs_loc l;
        for (i = 0; i < 16; i++){
            unsigned hi, lo;
            { const char *h = argv[k] + i * 2; char c = *h;
              hi = (c >= 'a') ? (unsigned)(c - 'a' + 10)
                              : (unsigned)(c - '0'); }
            { const char *h = argv[k] + i * 2 + 1; char c = *h;
              lo = (c >= 'a') ? (unsigned)(c - 'a' + 10)
                              : (unsigned)(c - '0'); }
            loc[i] = (unsigned char)((hi << 4) | lo);
        }
        if (m3ufs_split(loc, 16, &l) != 0){ return 2; }
        printf("%u %u\n", m3ufs_cluster(&l), m3ufs_entry_offset(&l));
    }
    return 0;
}
'''


def main():
    lib = os.path.join(FIXTURE, "M3U.LIB")
    if not os.path.isfile(lib):
        print("test_m3ufs: no fixture at %s" % lib)
        return 0
    with open(lib, "rb") as f:
        d = f.read()
    n = struct.unpack_from("<H", d, 8)[0]
    locs = [d[0x200 + 256 * i + 0xA9:0x200 + 256 * i + 0xA9 + 16]
            for i in range(n)]

    work = tempfile.mkdtemp(prefix="m3ufs.")
    drv = os.path.join(work, "drv_m3ufs.c")
    exe = os.path.join(work, "m3ufs_test")
    with open(drv, "w") as f:
        f.write(DRIVER)
    cmd = ["cc", "-O1", "-Wall", "-Wextra", "-I", HERE,
           "-I", os.path.join(HERE, "..", "m3u"), "-o", exe, drv,
           os.path.join(HERE, "m3ufs.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("test_m3ufs: build failed\n" + r.stderr)
        return 2

    got = subprocess.run([exe] + [l.hex() for l in locs],
                         capture_output=True, text=True)
    rows = [l.split() for l in got.stdout.splitlines() if l]

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    check(got.returncode == 0 and len(rows) == n,
          "the C implementation classified all %d real locations" % n)
    if len(rows) != n:
        print("   got %d rows" % len(rows))
        return 1

    for i, row in enumerate(rows):
        check(row[0] == str(cluster(locs[i]))
              and row[1] == str(entry_off(locs[i])),
              "record %d: cluster %s and entry offset %s match the"
              " disassembly's arithmetic" % (i, row[0], row[1]))
        check(entry_off(locs[i]) % 16 == 0 and entry_off(locs[i]) + 16 <= 512,
              "record %d: entry offset %d is a 16-byte slot that fits one"
              " 512-byte cluster" % (i, entry_off(locs[i])))
        check(cluster(locs[i]) >= split(locs[i])[0],
              "record %d: cluster %d is at or beyond the base %d"
              % (i, cluster(locs[i]), split(locs[i])[0]))

    # the card's own structure: all ten playlists in one directory, with small
    # monotonic cluster deltas -- that is what makes the addressing meaningful
    bases = [split(l)[0] for l in locs]
    raw = [split(l)[1] for l in locs]
    deltas = [x >> 5 for x in raw]
    check(len(set(bases)) == 1,
          "all %d records share one base cluster (%#x), so the ten playlists"
          " live in one directory" % (n, bases[0]))
    # every delta is a multiple of 32, so the entry-within-cluster index is 0:
    # each playlist starts at a cluster boundary. And they are distinct, so the
    # ten records address ten different positions, not one repeated entry.
    check(all(x % 32 == 0 for x in raw),
          "the entry selectors are all multiples of 32 (%s), so each"
          " playlist's entry sits at a cluster boundary" % deltas)
    check(len(set(deltas)) == n,
          "the %d entry selectors are all distinct, so the records address"
          " %d different positions" % (n, len(set(deltas))))
    check(deltas == sorted(deltas),
          "the deltas are monotonic in record order, so records 0..%d are"
          " directory entries in order" % (n - 1))

    print("test_m3ufs: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

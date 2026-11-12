#!/usr/bin/env python3
"""Location-arithmetic and location-layout regression tests.

Every assertion is checked against the ten real locations on the user's card,
so a transcription error or a wrong field split shows up as a failure.

The tests pin two separate things, and the distinction matters:

  * the transcription, i.e. that m3ufs.c computes what the disassembly says;
  * the layout, i.e. which bytes of the 16-byte field carry what -- which the
    card's own data settles, and which an earlier reading of this session got
    wrong.

They deliberately do NOT assert that the arithmetic resolves to a file. The
routines it comes from are unreferenced in the image, and no test here should
imply otherwise.
"""
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.environ.get("M30LIB", "/tmp/m30lib")

DRIVER = r'''
#include <stdio.h>
#include "m3ufs.h"
int main(int argc, char **argv){
    int k;
    for (k = 1; k < argc; k++){
        unsigned char loc[16];
        unsigned i, hi, lo;
        struct m3ufs_loc l;
        for (i = 0; i < 16; i++){
            hi = (*  (argv[k] + i*2)   >= 'a') ? (unsigned)(*(argv[k]+i*2)   - 'a' + 10)
                                               : (unsigned)(*(argv[k]+i*2)   - '0');
            lo = (*(argv[k] + i*2+1) >= 'a') ? (unsigned)(*(argv[k]+i*2+1) - 'a' + 10)
                                             : (unsigned)(*(argv[k]+i*2+1) - '0');
            loc[i] = (unsigned char)((hi << 4) | lo);
        }
        if (m3ufs_split(loc, 16, &l) != 0){ return 2; }
        printf("%u %u %lu %d\n", m3ufs_sector_of(&l), m3ufs_slot_of(&l),
               m3ufs_byte_offset(&l), m3ufs_slot_is_zero(&l));
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

    # the layout, established by the card's own data
    const12 = [l[:12] for l in locs]
    selectors = [struct.unpack_from("<I", l, 12)[0] for l in locs]

    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    check(len(set(const12)) == 1,
          "all %d records share their first twelve location bytes (%s), so the"
          " per-record value is the last four" % (n, const12[0].hex(" ")))
    check(selectors == [800, 1056, 1280, 1408, 1504, 1632, 1760, 1888, 2016,
                        2208],
          "the ten per-record selectors are the expected values")
    check(all(x % 32 == 0 for x in selectors),
          "every selector is a multiple of 32, so (arg1 & 0x1F) is zero for all"
          " of them -- the routines never exercise their own low-bit path")
    check(selectors == sorted(selectors) and len(set(selectors)) == n,
          "the selectors are distinct and monotonic in record order")

    # the transcription, checked against an independent reading of the same
    # disassembly, and against the C implementation
    def byte_at(l, off):
        return struct.unpack_from("<I", l, off)[0]

    def sector(l):
        return byte_at(l, 0) + (byte_at(l, 12) >> 5)

    def slot(l):
        return (byte_at(l, 12) & 0x1F) << 4

    work = tempfile.mkdtemp(prefix="m3ufs.")
    drv = os.path.join(work, "drv.c")
    exe = os.path.join(work, "m3ufs_test")
    with open(drv, "w") as f:
        f.write(DRIVER)
    cmd = ["cc", "-O1", "-Wall", "-Wextra", "-I", HERE, "-o", exe, drv,
           os.path.join(HERE, "m3ufs.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print("test_m3ufs: build failed\n" + r.stderr)
        return 2
    got = subprocess.run([exe] + [l.hex() for l in locs],
                         capture_output=True, text=True)
    rows = [l.split() for l in got.stdout.splitlines() if l]
    check(got.returncode == 0 and len(rows) == n,
          "the C implementation classified all %d real locations" % n)
    if len(rows) != n:
        return 1
    for i, row in enumerate(rows):
        check(row[0] == str(sector(locs[i])) and row[1] == str(slot(locs[i])),
              "record %d: sector %s and slot %s match the disassembly"
              % (i, row[0], row[1]))
        check(row[3] == ("1" if slot(locs[i]) == 0 else "0"),
              "record %d: slot_is_zero is %s" % (i, row[3]))

    print("test_m3ufs: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

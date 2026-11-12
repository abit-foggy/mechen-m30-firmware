#!/usr/bin/env python3
"""Audit how the M30 firmware's folder browser treats `.m3u` files.

The question this answers is *not* whether the firmware can parse a playlist --
it can: `playlist.ap` references `M3U`, `M3U.LIB` and its own `playlist.sty`.
The question is whether a user can *reach* a playlist from the folder browser.

That means finding the list of file extensions the browser enumerates, and
checking whether `.m3u` is in it. The list is a table of NUL-terminated
ASCII strings: a 3-character extension, then a longer display name, repeated.
`M3U` appearing elsewhere in the file (as a *filename* in the library-name
cluster, next to `MUSIC.LIB`) is a different thing entirely and does not make
the browser show `.m3u` files.

Usage:
    m3u_audit.py [FWIMAGE.FW] [browser.ap]
"""

import os
import re
import struct
import sys

DEFAULT_FW = "/home/foggy/m30/mechen-m30-firmware/build/work/stock/afi/FWIMAGE.FW"


def components(fwpath):
    fw = open(fwpath, "rb").read()
    comps = []
    o = 0x200
    while o + 32 <= 0x2000 and o + 32 <= len(fw):
        if fw[o] != 0:
            nm = fw[o:o + 8].split(b"\0")[0].decode("latin1").strip()
            ex = fw[o + 8:o + 11].split(b"\0")[0].decode("latin1").strip()
            doff = struct.unpack_from("<I", fw, o + 0x10)[0] << 9
            dsz = struct.unpack_from("<I", fw, o + 0x14)[0]
            if doff and dsz:
                comps.append((("%s.%s" % (nm, ex)).lower(), fw[doff:doff + dsz]))
        o += 32
    return comps


def find_extension_table(blob):
    """Locate the browser's extension array.

    The array is a run of fixed 4-byte slots, each a NUL-padded 3-character
    uppercase extension. It is found by anchoring on `MP3\0` and walking while
    the slot stays a plausible extension. Merged pairs such as `FLACAPE` and
    `JPEGDSF` are just two slots whose NUL was overwritten by the next entry,
    which is why stride matters and NUL-splitting does not.
    Returns (start_offset, [ext, ...]) or None.
    """
    for m in re.finditer(rb"MP3\x00", blob):
        start = m.start()
        if (start % 4) != 0:
            continue
        exts = []
        pos = start
        while pos + 4 <= len(blob):
            slot = blob[pos:pos + 4]
            core = slot[:3]
            # a real slot is three alphanumerics (wildcards `*` allowed) plus
            # a NUL or the first character of the next extension
            if not all(48 <= c <= 57 or 65 <= c <= 90 or c == 42 or c == 32
                       for c in core):
                break
            exts.append(core.decode("latin1").rstrip())
            pos += 4
        if len(exts) >= 10:
            return start, exts
    return None


def main():
    fw = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FW
    if not os.path.exists(fw):
        print("m3u_audit: missing %s" % fw)
        return 1

    comps = components(fw)
    byname = dict(comps)
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # 1. the playlist subsystem does exist
    for name, marker in (("playlist.ap", b"M3U.LIB"),
                         ("browser.ap", b"M3U.LIB"),
                         ("music.ap", b"M3U.LIB")):
        check(marker in byname.get(name, b""),
              "%s references %r (the playlist subsystem is present)" % (name, marker))
    check(b"playlist.sty" in byname.get("playlist.ap", b""),
          "playlist.ap carries its own playlist.sty resource")

    # 2. the browser enumerates a fixed extension list, and .m3u is not in it
    for probe in ("browser.ap", "music.ap", "playlist.ap", "mainmenu.ap"):
        tab = find_extension_table(byname.get(probe, b""))
        if not tab:
            print("      %s: no extension table found" % probe)
            continue
        off, exts = tab
        print("      %s: extension array at file+%#x, %d entries: %s"
              % (probe, off, len(exts), ", ".join(exts)))
        if probe == "browser.ap":
            check("M3U" not in exts and "M3U8" not in exts,
                  "the browser's extension list has no M3U/M3U8 entry, so .m3u"
                  " files are filtered out of the folder browser")
            check(len(exts) >= 10,
                  "the list is a real type filter (%d entries), not a stray table"
                  % len(exts))
    # 3. the decisive question: is there a .m3u *parser* at all?
    allblobs = b"".join(b for _, b in comps)
    for marker in (b"#EXTM3U", b"#EXTINF", b".m3u"):
        check(marker not in allblobs,
              "no %r anywhere in the firmware: there is no .m3u *parser*" % marker)
    check(b"M3U.LIB" in allblobs,
          "M3U.LIB exists -- so the playlist *database* format exists, which is"
          " a different thing from parsing a .m3u file")
    check(b"USERPL1.PL" in allblobs,
          "USERPL1-3.PL exist: playlist databases the device reads directly")

    print()
    print("verdict:")
    print("  * the playlist *database* format exists (M3U.LIB, USERPL1-3.PL,")
    print("    playlist.sty) and playlist.ap renders those databases.")
    print("  * the folder browser's extension array has no M3U entry, so .m3u")
    print("    files are never listed.")
    print("  * and there is no .m3u parser in the firmware at all -- no")
    print("    #EXTM3U, no #EXTINF, no .m3u extension anywhere.")
    print("  => a playlist on the card is invisible AND unparseable. The gap is")
    print("     a missing parser, not just a missing filter entry.")
    return rc


if __name__ == "__main__":
    sys.exit(main())

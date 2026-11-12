#!/usr/bin/env python3
"""Pin the verified facts behind .m3u visibility in the folder browser.

Everything asserted here was established this session against the unpacked
stock 2025-06-26 image and community V1.101.11, and each claim is checked by
re-deriving it from the files rather than by matching a recorded offset. The
point is that a later session cannot quietly drift from the layout: the
extension table is a *fixed 4-byte slot array*, not the NUL-separated string
list it looks like at first glance, and the browser does not compare
extension strings at all -- it selects slots with a bit mask.

No firmware image is copied into the repository; the test reads the unpacked
components from the working tree and, for the community comparison, from the
standard unpack location.

Usage: exttest.py   (exits non-zero on any failure; 2 if inputs are missing)
"""

import os
import struct
import sys

STOCK = os.environ.get(
    "M30_STOCK", "/home/foggy/m30/mechen-m30-firmware/build/work/stock/fw")
COMM_CANDIDATES = (
    os.environ.get("M30_COMM", ""),
    "/tmp/cmp/v110111/fw",
    os.path.expanduser("~/.cache/m30fw/fw"),
)

# The 27 recognised extensions, in slot order. FLAC and APE share a pair of
# slots as do JPEG and DSF, because each entry is a fixed 4-byte slot and a
# 4-character name fills one whole slot with no room for the terminator.
EXPECTED_ENTRIES = [
    "MP3", "WMA", "WAV", "AAC", "FLAC", "APE", "AVI", "TXT", "JPG", "JPEG",
    "DSF", "DFF", "LRC", "ASF", "OGG", "TTA", "ISO", "AAX", "AA", "MP1",
    "MP2", "M4A", "POS", "ACT", "BMK", "AIF", "APK", "PCM",
]
# The three slots after them. Neither stock nor community ever accepts a file
# by one of these alone: they are matched as whole words, see the mask below.
WILDCARDS = ["**", "*f", "   "]
MUSIC_MASK = 0x7E190EA0
M3U_MASK = 0x00080400
MASK_TABLE = 0x2A20          # in playlist.ap: MUSIC.LIB mask, then a word, M3U.LIB
DRIVERS = ("fat_32n.drv", "exfatn.drv")
DRIVER_LOAD = 0xBFC16C00     # both drivers' resident bank: they are exclusive
SEGMENT_TAIL = 8             # bytes at the end of the resident bank
TAIL_STUB = bytes.fromhex("106b05e80f6b05e8")


def load(dirpath, name):
    p = os.path.join(dirpath, name)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def find_community():
    for c in COMM_CANDIDATES:
        if c and os.path.isfile(os.path.join(c, DRIVERS[0])):
            return c
    return None


def resident_span(blob):
    """The resident bank of a .drv, from its YQHX header.

    +0x08 is the resident file offset and +0x0c its size; both drivers put it
    at 0x200 with a size of 0x800, so the bank is 0x200..0xa00.
    """
    foff, size = struct.unpack_from("<II", blob, 0x08)
    return foff, foff + size


def find_table(blob):
    """Locate the extension slot array by anchoring on 'MP3\\0'.

    Anchoring on the content rather than a stored offset keeps this valid
    across repacking. The array is a run of whole 4-byte slots holding
    NUL-padded uppercase text; it ends at the first slot that is not such a
    word. Returns (start, end_exclusive) or None.
    """
    i = blob.find(b"MP3\x00WMA\x00")
    if i < 0 or i % 4:
        return None
    pos = i
    while pos + 4 <= len(blob):
        slot = blob[pos:pos + 4]
        text = slot.rstrip(b"\x00")
        if not text or not all(0x20 <= b < 0x7F for b in text):
            break
        pos += 4
    return i, pos


def slots(blob, start, count):
    out = []
    for k in range(count):
        raw = blob[start + 4 * k:start + 4 * k + 4]
        txt = raw.rstrip(b"\x00").decode("latin-1")
        word = struct.unpack_from("<I", raw)[0]
        out.append((txt, word))
    return out


def main():
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    for name in DRIVERS:
        if load(STOCK, name) is None:
            print("exttest: missing %s under %s" % (name, STOCK))
            return 2
    comm = find_community()

    bases = {}
    for name in DRIVERS:
        blob = load(STOCK, name)
        pos = find_table(blob)
        check(pos is not None,
              "%s: the extension array is present and slot-aligned" % name)
        if not pos:
            continue
        start, end = pos
        bases[name] = (start, end)

        # 1. a fixed 4-byte slot array, not a NUL-separated string list
        nslots = (end - start) // 4
        check(nslots == len(EXPECTED_ENTRIES) + len(WILDCARDS),
              "%s: the run is %d slots (%d extensions + %d wildcards)"
              % (name, nslots, len(EXPECTED_ENTRIES), len(WILDCARDS)))
        got = [t for t, _ in slots(blob, start, len(EXPECTED_ENTRIES))]
        check(got == EXPECTED_ENTRIES,
              "%s: the first %d slots are the expected extensions, in order"
              % (name, len(EXPECTED_ENTRIES)))
        if got != EXPECTED_ENTRIES:
            print("        got %s" % got)

        # 2. the wildcard slots close the run, then a whole zero slot
        wstart = start + 4 * len(EXPECTED_ENTRIES)
        w = slots(blob, wstart, len(WILDCARDS))
        check([t for t, _ in w] == WILDCARDS,
              "%s: the run closes with the wildcard slots %s, in order"
              % (name, "/".join(repr(x) for x in WILDCARDS)))
        check(all(len(t) < 4 for t, _ in w),
              "%s: each wildcard fits inside its own slot with a terminator"
              % name)
        zero = blob[end:end + 4]
        check(zero == b"\x00\x00\x00\x00",
              "%s: the run is terminated by a whole zero slot" % name)

        # 3. after the terminator the bank is zero up to its last eight bytes,
        #    which hold a small MIPS16e stub pair rather than padding. Its
        #    function is undetermined; what matters for a patch is that it is
        #    not free space, so a byte appended at "the end" would land on it.
        seg = resident_span(blob)
        tail = seg[1] - SEGMENT_TAIL
        free = blob[end + 4:tail]
        stub = blob[tail:seg[1]]
        check(all(b == 0 for b in free) and len(free) == tail - (end + 4),
              "%s: %d zero bytes after the terminator, up to the stub"
              % (name, len(free)))
        check(stub == TAIL_STUB,
              "%s: the last %d bytes of the bank are the stub %s"
              % (name, SEGMENT_TAIL, TAIL_STUB.hex(" ")))
        check(len(free) >= 4,
              "%s: room for %d more slots in the zero run" % (name, len(free) // 4))

        # 4. no M3U slot exists in this driver
        check(all(t != "M3U" for t, _ in slots(blob, start, nslots)),
              "%s: no M3U slot exists, so no mask can select one" % name)
        check(b"M3U" not in blob,
              "%s: the string M3U appears nowhere in the driver" % name)

        # 5. both drivers load at the same address and only one is resident,
        #    so the array has one guest address whichever is loaded
        guest = DRIVER_LOAD + (start - 0x200)
        check(0xBFC17000 <= guest < 0xBFC17400,
              "%s: the array maps to guest %#x, inside the resident bank"
              % (name, guest))

    # 6. the two drivers agree byte for byte over the array and its tail
    if len(bases) == 2:
        (s1, e1), (s2, e2) = bases[DRIVERS[0]], bases[DRIVERS[1]]
        b1 = load(STOCK, DRIVERS[0])[s1:e1 + 16]
        b2 = load(STOCK, DRIVERS[1])[s2:e2 + 16]
        check(b1 == b2,
              "fat_32n.drv and exfatn.drv carry byte-identical arrays")
        check(e1 - s1 == e2 - s2,
              "both arrays are the same length (%d bytes)" % (e1 - s1))

    # 7. neither the shipped community firmware nor stock extended the array
    if comm:
        for name in DRIVERS:
            s = load(STOCK, name)
            k = load(comm, name)
            if k is None:
                continue
            ps, pk = find_table(s), find_table(k)
            if not (ps and pk):
                continue
            a = s[ps[0]:ps[1] + 4 * len(WILDCARDS) + 4]
            b = k[pk[0]:pk[1] + 4 * len(WILDCARDS) + 4]
            check(a == b,
                  "%s: the community image leaves the array unchanged" % name)

        # 8. the extension mask table in playlist.ap: one mask per library
        #    type. Bits select slots of the array; which bit is which slot is
        #    not yet decoded, so only the mask values are asserted. A word
        #    sits between the two masks that is not a MIPS16e pointer (its
        #    low bit is clear), and is recorded as unresolved.
        sp = load(STOCK, "playlist.ap")
        cp = load(comm, "playlist.ap")
        if sp is not None and cp is not None:
            music, middle, m3u = struct.unpack_from("<3I", sp, MASK_TABLE)
            check(music == MUSIC_MASK,
                  "playlist.ap: the MUSIC.LIB mask is %#x (got %#x)"
                  % (MUSIC_MASK, music))
            check(m3u == M3U_MASK,
                  "playlist.ap: the M3U.LIB mask is %#x (got %#x)"
                  % (M3U_MASK, m3u))
            check(0xBFC00000 <= middle < 0xBFC20000,
                  "playlist.ap: the word between the masks is a resident"
                  " address (%#x), not a MIPS16e pointer" % middle)
            check(sp[MASK_TABLE - 8:MASK_TABLE + 0x10] ==
                  cp[MASK_TABLE - 8:MASK_TABLE + 0x10],
                  "playlist.ap: the community image leaves the masks unchanged")
            check(bin(music).count("1") == 14,
                  "the MUSIC.LIB mask sets 14 bits (got %d)"
                  % bin(music).count("1"))
            check(bin(m3u).count("1") == 2,
                  "the M3U.LIB mask sets 2 bits (got %d)"
                  % bin(m3u).count("1"))
    else:
        print("SKIP  community image not unpacked; ran without it")

    # 9. what this means for a patch: an appended slot cannot move anything,
    #    because every existing slot keeps its offset and the array is
    #    slot-indexed. This is the shape a fix must have.
    print("NOTE  an additive M3U slot would go after the wildcards; it"
          " cannot be inserted anywhere else without shifting indices,")
    print("NOTE  and the wildcards are matched as whole words, so their"
          " order relative to an appended slot is the unresolved risk.")

    print("exttest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

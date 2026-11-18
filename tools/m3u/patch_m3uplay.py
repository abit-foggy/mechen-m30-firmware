"""Insert the M3U play-on-click hooks into browser.ap and mengine.ap.

usage:
  patch_m3uplay.py BROW_IN BROW_OUT PLAY.bin TRAMP_ADDR
                   [MENG_IN MENG_OUT MTRAMP.bin MSTEP.bin SETLOC BYNO PREV NEXT]

browser.ap writes (every site guarded by stock-byte assertions):
  1. file 0x12894 (guest 0x40D15194, path-B classify call):
     stock `81 1a 80 53` (jal 0x40D14E00) -> `60 18 34 53` (jal 0x400D4CD0).
  2. file 0x23D0 (bank 0x400D4C00 tail, guest 0x400D4CD0, max 0x730 = 1840 B):
     verified all-zero tail -> PLAY.bin.

mengine.ap writes (when MENG_IN..NEXT are supplied):
  1. bank 0x7A052D00 (table @0x40C, file 0x5600, stock size 0x638):
     - four mode-0 fsel pointers (set_location @0x59B4, get_byno @0x59C0,
       get_prevfile @0x59CC, get_nextfile @0x59D8) -> MTRAMP symbols | 1
     - MTRAMP.bin placed in the verified-zero tail at file 0x5C38 (guest
       0x7A053338, max 0xC8 = 200 B) and bank size raised to cover it.
  2. bank 0x7B268000 (unused group-0x7B bank 9, table @0x76C, stock no-op stub
     at file 0xA100):
     - bank 0x60A50D00 (table @0x2EC, file 0xC900, live code ends at 0xCAAC)
       load size trimmed from 0x800 to 0x200
     - bank 9 table @0x76C pointed at the verified-zero 0x600-byte run at file
       0xCB00..0xD100 (guest 0x7B268000) and MSTEP.bin written there.
"""
import struct
import sys

# browser.ap constants
CLICK_FO = 0x12894
CLICK_STOCK = bytes.fromhex("811a8053")   # jal 0x40D14E00
CLICK_NEW = bytes.fromhex("60183453")     # jal 0x400D4CD0 (m3uplay_tramp)
POOL_FO = 0x4594                          # stock 0x780DB494 (must remain stock)
POOL_STOCK = 0xBFC16A2D
BLOB_FO = 0x23D0                          # bank 0x400D4C00 + 0xD0
BLOB_MAX = 0x730
TRAMP = 0x400D4CD0

# mengine.ap constants
M_7A05_TBL = 0x40C
M_7A05_FO, M_7A05_VA, M_7A05_SZ = 0x5600, 0x7A052D00, 0x638
M_TRAMP_FO, M_TRAMP_VA, M_TRAMP_MAX = 0x5C38, 0x7A053338, 0xC8
M_60A5_TBL = 0x2EC
M_60A5_FO, M_60A5_VA, M_60A5_SZ, M_60A5_NEW_SZ = 0xC900, 0x60A50D00, 0x800, 0x200
M_7B26_TBL = 0x76C
M_7B26_OLD_FO, M_7B26_VA, M_7B26_OLD_SZ = 0xA100, 0x7B268000, 0xC
M_7B26_STUB = bytes.fromhex("91643d67b9651164a0e80065")
M_STEP_FO, M_STEP_MAX = 0xCB00, 0x600

M_PTRS = [
    (0x59B4, 0x7B0685F5),   # set_location[0]
    (0x59C0, 0x7B0E81F9),   # get_byno[0]
    (0x59CC, 0x7B0A8001),   # get_prevfile[0]
    (0x59D8, 0x7B068001),   # get_nextfile[0]
]


def patch_browser(src, out, blob_path, tramp_s):
    tramp = int(tramp_s, 0)
    assert tramp == TRAMP, \
        "click-site jal bytes are encoded for tramp %#x only (got %#x)" % (TRAMP, tramp)
    blob = open(blob_path, "rb").read()
    assert 0 < len(blob) <= BLOB_MAX, "browser blob is %d bytes, max %d" % (len(blob), BLOB_MAX)

    d = bytearray(open(src, "rb").read())
    orig = bytes(d)

    assert d[CLICK_FO:CLICK_FO + 4] == CLICK_STOCK, \
        "click site file %#x is not stock: %s" % (CLICK_FO, d[CLICK_FO:CLICK_FO + 4].hex())
    assert struct.unpack_from("<I", d, POOL_FO)[0] == POOL_STOCK, \
        "fetch pool word file %#x is not stock: %#x" % (
            POOL_FO, struct.unpack_from("<I", d, POOL_FO)[0])
    assert not any(d[BLOB_FO:BLOB_FO + BLOB_MAX]), \
        "blob tail file %#x..%#x is not zero" % (BLOB_FO, BLOB_FO + BLOB_MAX)
    assert BLOB_FO + len(blob) <= len(d), "blob runs off browser.ap"

    d[CLICK_FO:CLICK_FO + 4] = CLICK_NEW
    d[BLOB_FO:BLOB_FO + len(blob)] = blob

    # read-back + diff-set check
    assert d[CLICK_FO:CLICK_FO + 4] == CLICK_NEW
    assert bytes(d[BLOB_FO:BLOB_FO + len(blob)]) == blob
    diffs = {i for i in range(len(d)) if d[i] != orig[i]}
    allowed = set(range(CLICK_FO, CLICK_FO + 4)) | set(range(BLOB_FO, BLOB_FO + len(blob)))
    assert diffs <= allowed, "unexpected browser.ap byte changes outside patch sites"

    open(out, "wb").write(d)
    print("m3uplay browser.ap: click 0x40D15194 -> jal %#x, blob %d/%d B at %#x" % (
        tramp, len(blob), BLOB_MAX, tramp))


def patch_mengine(src, out, mtramp_path, mstep_path, setloc_s, byno_s, prev_s, next_s):
    addrs = [int(x, 0) for x in (setloc_s, byno_s, prev_s, next_s)]
    mtramp = open(mtramp_path, "rb").read()
    mstep = open(mstep_path, "rb").read()
    assert 0 < len(mtramp) <= M_TRAMP_MAX, \
        "mengine tramp is %d bytes, max %d" % (len(mtramp), M_TRAMP_MAX)
    assert 0 < len(mstep) <= M_STEP_MAX, \
        "mengine step blob is %d bytes, max %d" % (len(mstep), M_STEP_MAX)
    for a in addrs:
        assert M_TRAMP_VA <= a < M_TRAMP_VA + len(mtramp) and (a & 1) == 0, \
            "mengine tramp symbol %#x outside %#x..%#x" % (a, M_TRAMP_VA, M_TRAMP_VA + len(mtramp))

    d = bytearray(open(src, "rb").read())
    orig = bytes(d)

    assert struct.unpack_from("<3I", d, M_7A05_TBL) == (M_7A05_FO, M_7A05_VA, M_7A05_SZ), \
        "7A052D00 bank entry mismatch: %r" % (struct.unpack_from("<3I", d, M_7A05_TBL),)
    assert struct.unpack_from("<3I", d, M_60A5_TBL) == (M_60A5_FO, M_60A5_VA, M_60A5_SZ), \
        "60A50D00 bank entry mismatch: %r" % (struct.unpack_from("<3I", d, M_60A5_TBL),)
    assert struct.unpack_from("<3I", d, M_7B26_TBL) == (M_7B26_OLD_FO, M_7B26_VA, M_7B26_OLD_SZ), \
        "7B268000 bank entry mismatch: %r" % (struct.unpack_from("<3I", d, M_7B26_TBL),)
    assert bytes(d[M_7B26_OLD_FO:M_7B26_OLD_FO + M_7B26_OLD_SZ]) == M_7B26_STUB, \
        "7B268000 stock stub mismatch"
    assert not any(d[M_TRAMP_FO:M_TRAMP_FO + M_TRAMP_MAX]), \
        "7A052D00 zero tail %#x..%#x is not zero" % (M_TRAMP_FO, M_TRAMP_FO + M_TRAMP_MAX)
    assert not any(d[0xCAAC:M_STEP_FO + M_STEP_MAX]), \
        "60A50D00 zero tail 0xCAAC..%#x is not zero" % (M_STEP_FO + M_STEP_MAX)
    for (fo, stock), _ in zip(M_PTRS, addrs):
        got = struct.unpack_from("<I", d, fo)[0]
        assert got == stock, "mengine ptr @%#x = %#x, expected %#x" % (fo, got, stock)

    new_7a05_sz = (M_7A05_SZ + len(mtramp) + 3) & ~3
    new_7b26_sz = (len(mstep) + 3) & ~3
    assert new_7a05_sz <= 0x700 and new_7b26_sz <= M_STEP_MAX

    for (fo, _), a in zip(M_PTRS, addrs):
        struct.pack_into("<I", d, fo, a | 1)
    d[M_TRAMP_FO:M_TRAMP_FO + len(mtramp)] = mtramp
    struct.pack_into("<I", d, M_7A05_TBL + 8, new_7a05_sz)

    struct.pack_into("<I", d, M_60A5_TBL + 8, M_60A5_NEW_SZ)
    struct.pack_into("<3I", d, M_7B26_TBL, M_STEP_FO, M_7B26_VA, new_7b26_sz)
    d[M_STEP_FO:M_STEP_FO + len(mstep)] = mstep

    # read-back + diff-set check
    for (fo, _), a in zip(M_PTRS, addrs):
        assert struct.unpack_from("<I", d, fo)[0] == (a | 1)
    assert bytes(d[M_TRAMP_FO:M_TRAMP_FO + len(mtramp)]) == mtramp
    assert bytes(d[M_STEP_FO:M_STEP_FO + len(mstep)]) == mstep
    assert struct.unpack_from("<3I", d, M_7B26_TBL) == (M_STEP_FO, M_7B26_VA, new_7b26_sz)

    allowed = (
        set(range(M_7A05_TBL + 8, M_7A05_TBL + 12))
        | set(range(M_60A5_TBL + 8, M_60A5_TBL + 12))
        | set(range(M_7B26_TBL, M_7B26_TBL + 12))
        | set(range(M_TRAMP_FO, M_TRAMP_FO + len(mtramp)))
        | set(range(M_STEP_FO, M_STEP_FO + len(mstep)))
    )
    for fo, _ in M_PTRS:
        allowed |= set(range(fo, fo + 4))
    diffs = {i for i in range(len(d)) if d[i] != orig[i]}
    assert diffs <= allowed, "unexpected mengine.ap byte changes outside patch sites"

    open(out, "wb").write(d)
    print("m3uplay mengine.ap: tramp %d/%d B at %#x, step %d/%d B at %#x" % (
        len(mtramp), M_TRAMP_MAX, M_TRAMP_VA, len(mstep), M_STEP_MAX, M_7B26_VA))


def main():
    if len(sys.argv) not in (5, 13):
        sys.exit(__doc__)
    patch_browser(*sys.argv[1:5])
    if len(sys.argv) == 13:
        patch_mengine(*sys.argv[5:13])


if __name__ == "__main__":
    main()

"""Insert the M3U play-on-click hook into browser.ap (Phase D/E).

usage: patch_m3uplay.py SRC.ap OUT.ap BLOB.bin TRAMP_ADDR FETCH_ADDR

Three writes, every one guarded by a stock-byte assertion:

 1. file 0x12894 (guest 0x40D15194, the path-B classify call):
    stock `81 1a 80 53` (jal 0x40D14E00) -> `60 18 34 53` (jal 0x400D4CD0,
    m3uplay_tramp). The encoding was produced by the cross assembler for
    exactly that target, so TRAMP_ADDR must equal 0x400D4CD0.
 2. file 0x4594 (pool word dword_780DB494 of the record fetch 0x780DB460):
    stock 0xBFC16A2D (the fs stub) -> FETCH_ADDR | 1. The wrapper keeps its
    own prologue/epilogue and publishes whatever the call returns to
    0x9FC1573C, so the hook only has to return the record pointer; with the
    server disarmed it just tail-calls the real stub with identical args.
 3. file 0x23D0 (bank 0x400D4C00, guest 0x400D4CD0, 16-aligned so the linker
    never moves it): the blob. The tail is 0x730 bytes, verified all-zero
    and unreferenced.

The read-back re-checks all three writes and that nothing else moved.
"""
import struct
import sys

CLICK_FO = 0x12894
CLICK_STOCK = bytes.fromhex("811a8053")   # jal 0x40D14E00
CLICK_NEW = bytes.fromhex("60183453")     # jal 0x400D4CD0 (m3uplay_tramp)
POOL_FO = 0x4594                          # dword_780DB494
POOL_STOCK = 0xBFC16A2D
BLOB_FO = 0x23D0                          # bank 0x400D4C00 + 0xD0 (16-aligned)
BLOB_MAX = 0x730
TRAMP = 0x400D4CD0


def main(src, out, blob_path, tramp, fetch):
    tramp, fetch = int(tramp, 0), int(fetch, 0)
    assert tramp == TRAMP, \
        "the click-site jal bytes are encoded for tramp %#x only (got %#x)" % (TRAMP, tramp)
    blob = open(blob_path, "rb").read()
    assert len(blob) <= BLOB_MAX, "blob is %d bytes, only %d fit" % (len(blob), BLOB_MAX)

    d = bytearray(open(src, "rb").read())
    orig = bytes(d)

    assert d[CLICK_FO:CLICK_FO + 4] == CLICK_STOCK, \
        "click site file %#x is not stock: %s" % (CLICK_FO, d[CLICK_FO:CLICK_FO + 4].hex())
    assert struct.unpack_from("<I", d, POOL_FO)[0] == POOL_STOCK, \
        "fetch pool word file %#x is not stock: %#x" % (
            POOL_FO, struct.unpack_from("<I", d, POOL_FO)[0])
    assert not any(d[BLOB_FO:BLOB_FO + BLOB_MAX]), \
        "blob tail file %#x..%#x is not zero" % (BLOB_FO, BLOB_FO + BLOB_MAX)
    assert BLOB_FO + len(blob) <= len(d), "blob runs off the file"

    d[CLICK_FO:CLICK_FO + 4] = CLICK_NEW
    struct.pack_into("<I", d, POOL_FO, fetch | 1)
    d[BLOB_FO:BLOB_FO + len(blob)] = blob

    # read-back
    assert d[CLICK_FO:CLICK_FO + 4] == CLICK_NEW, "click-site read-back failed"
    assert struct.unpack_from("<I", d, POOL_FO)[0] == (fetch | 1), "pool read-back failed"
    assert bytes(d[BLOB_FO:BLOB_FO + len(blob)]) == blob, "blob read-back failed"

    # nothing else may have moved
    diffs = [i for i in range(len(d)) if d[i] != orig[i]]
    lo, hi = min(diffs), max(diffs)
    assert set(range(CLICK_FO, CLICK_FO + 4)) | set(range(POOL_FO, POOL_FO + 4)) \
        | set(range(BLOB_FO, BLOB_FO + len(blob))) >= set(diffs), \
        "bytes outside the three patch regions changed (%#x..%#x)" % (lo, hi)

    open(out, "wb").write(d)
    print("   m3uplay: click 0x40D15194 -> jal %#x, fetch pool 0x780DB494 -> %#x,"
          " blob %d bytes at %#x (file %#x)" % (tramp, fetch | 1, len(blob), tramp, BLOB_FO))


if __name__ == "__main__":
    main(*sys.argv[1:6])

#!/usr/bin/env python3
"""Test the M3U/M3U8 visibility patch against the real stock files.

usage: test_m3uvis.py STOCK_fat_32n.drv STOCK_browser.ap

Applies patch_m3uvis.py to temp copies, then checks:
  1. exactly the four 4-byte slots differ from stock (nothing else moved);
  2. a faithful model of the driver classifier (0xBFC16D94: loop j=0..30,
     mask bit[30-j], break on entry 0 / "**", match on 24-bit compare)
     run over the PATCHED driver table admits M3U and M3U8 under the music
     mask 0x7e190ea0, rejects them when the slot bit is cleared, and still
     admits MP3/FLAC while no longer admitting AIF/MP2;
  3. the same for the browser-local table (0x40D1529C, slot j <-> bit[31-j]).

Exits non-zero on any failure.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

MUSIC_MASK = 0x7E190EA0          # bitmap table [0] at 0x40D1531C
DRV_TABLE, LOC_TABLE, LOC_BANK_FO = 0x780, 0x49C, 0x12500


def classify(table, mask, ext24, base_bit):
    """Model of the classifier loop. base_bit: driver 30, browser 31.

    entry[j] <-> mask bit [base_bit - j]; j runs 1..(base_bit+1) in the asm
    (idx = j+1), the loop ends when idx reaches 32 (driver) / the mask runs
    out; entries 0 and "**" end the scan. Returns True on match.
    """
    if mask == 0:
        return False
    ext = ext24 & 0xFFFFFF
    n_slots = 31 if base_bit == 30 else 32
    for j in range(n_slots):
        bit = 1 << (base_bit - j)
        if not (mask & bit):
            continue
        entry = struct.unpack("<I", table[4 * j:4 * j + 4])[0] & 0xFFFFFF
        if entry == 0 or entry == 0x2A2A:      # 0 / "**"
            break
        if entry == 0x202020:                   # "   " directory marker
            continue
        if entry == 0x662A:                     # "*f" all-files marker
            continue
        if entry == ext:
            return True
    return False


def main(stock_drv, stock_brow):
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    work = tempfile.mkdtemp(prefix="m30vis.")
    drv, brow = os.path.join(work, "fat_32n.drv"), os.path.join(work, "browser.ap")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_m3uvis.py"),
                        stock_drv, drv, stock_brow, brow], capture_output=True, text=True)
    check(r.returncode == 0, "patch tool ran cleanly")
    if r.returncode:
        print(r.stderr[-800:])
        return 1

    sd, sb = open(stock_drv, "rb").read(), open(stock_brow, "rb").read()
    pd, pb = open(drv, "rb").read(), open(brow, "rb").read()

    # 1. exactly the four slots changed: the new bytes are in place and
    #    every offset outside those slots is identical to stock
    slots_d = [(DRV_TABLE + 4 * 25, b"M3U\x00"), (DRV_TABLE + 4 * 20, b"M3U8")]
    slots_b = [(LOC_BANK_FO + LOC_TABLE + 4 * 26, b"M3U\x00"),
               (LOC_BANK_FO + LOC_TABLE + 4 * 21, b"M3U8")]
    ok_d = all(pd[off:off + 4] == new for off, new in slots_d) and all(
        sd[i] == pd[i] for i in range(len(sd))
        if not any(off <= i < off + 4 for off, _ in slots_d))
    ok_b = all(pb[off:off + 4] == new for off, new in slots_b) and all(
        sb[i] == pb[i] for i in range(len(sb))
        if not any(off <= i < off + 4 for off, _ in slots_b))
    check(ok_d, "driver: slots 25/20 now M3U/M3U8, every other byte stock")
    check(ok_b, "browser: local slots 26/21 now M3U/M3U8, every other byte stock")

    drv_tab = pd[DRV_TABLE:DRV_TABLE + 31 * 4]
    loc_tab = pb[LOC_BANK_FO + LOC_TABLE:LOC_BANK_FO + LOC_TABLE + 32 * 4]

    # 2. driver classifier model over the patched table
    cases = [
        (MUSIC_MASK, b"M3U\x00", True,  "driver: .m3u admitted under music mask"),
        (MUSIC_MASK, b"M3U8",   True,  "driver: .m3u8 admitted under music mask"),
        (MUSIC_MASK, b"MP3\x00", True, "driver: .mp3 still admitted"),
        (MUSIC_MASK, b"FLAC",   True,  "driver: .flac still admitted (24-bit FLA)"),
        (MUSIC_MASK, b"AIF\x00", False, "driver: .aif no longer admitted (slot reused)"),
        (MUSIC_MASK, b"MP2\x00", False, "driver: .mp2 no longer admitted (slot reused)"),
        (MUSIC_MASK, b"TXT\x00", False, "driver: .txt not admitted under music mask"),
        # the driver compares 24 bits, so the "M3U8" slot also matches .m3u
        # through bit10; .m3u needs bit5 OR bit10, and both bits off removes it
        (MUSIC_MASK & ~0x20, b"M3U\x00", True, "driver: .m3u still admitted via the M3U8 slot (bit10)"),
        (MUSIC_MASK & ~0x20 & ~0x400, b"M3U\x00", False, "driver: bits 5+10 off removes .m3u (bit mapping)"),
        (0x20, b"M3U\x00", True,  "driver: bit5 alone admits .m3u"),
        (0x400, b"M3U8", True,  "driver: bit10 alone admits .m3u8"),
        (0, b"M3U\x00", False, "driver: zero mask admits nothing"),
    ]
    for mask, ext, want, msg in cases:
        check(classify(drv_tab, mask, struct.unpack("<I", ext)[0], 30) == want, msg)

    # 3. browser-local table model (slot j <-> bit[31-j])
    for mask, ext, want, msg in [
        (MUSIC_MASK, b"M3U\x00", True,  "browser: .m3u admitted under music mask"),
        (MUSIC_MASK, b"M3U8",   True,  "browser: .m3u8 admitted under music mask"),
        (MUSIC_MASK, b"MP3\x00", True, "browser: .mp3 still admitted"),
        (MUSIC_MASK, b"AIF\x00", False, "browser: .aif no longer admitted"),
        (MUSIC_MASK & ~0x20 & ~0x400, b"M3U\x00", False, "browser: bits 5+10 off removes .m3u"),
        (0x400, b"M3U8", True,  "browser: bit10 alone admits .m3u8"),
    ]:
        check(classify(loc_tab, mask, struct.unpack("<I", ext)[0], 31) == want, msg)

    # 4. the stock tables must NOT admit m3u (the bug we are fixing)
    sdrv_tab = sd[DRV_TABLE:DRV_TABLE + 31 * 4]
    sloc_tab = sb[LOC_BANK_FO + LOC_TABLE:LOC_BANK_FO + LOC_TABLE + 32 * 4]
    check(not classify(sdrv_tab, MUSIC_MASK, struct.unpack("<I", b"M3U\x00")[0], 30),
          "stock driver table does not admit .m3u (reproduces the hardware verdict)")
    check(not classify(sloc_tab, MUSIC_MASK, struct.unpack("<I", b"M3U\x00")[0], 31),
          "stock browser table does not admit .m3u")

    shutil.rmtree(work, ignore_errors=True)
    print("test_m3uvis: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))

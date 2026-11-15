#!/usr/bin/env python3
"""Test the M3U/M3U8 visibility patch against the real stock files.

usage: test_m3uvis.py STOCK_fat_32n.drv STOCK_browser.ap [STOCK_exfatn.drv]

Applies patch_m3uvis.py to temp copies, then checks:
  1. exactly the patched slots/mask words differ from stock (nothing else moved);
  2. a faithful model of the driver matcher (0xBFC16D94: loop idx=1..31,
     mask bit[31-idx], table[idx-1], exact 24-bit compare - case sensitive,
     as verified under QEMU by tools/m3u/fsmatchtest.py) run over the PATCHED
     driver tables admits M3U/m3u and M3U8/m3u8 under the patched music mask,
     still admits MP3/FLAC, and no longer admits AIF/MP2/POS;
  3. the same for the browser-local table (0x40D1529C, slot j <-> bit[31-j]);
  4. the stock tables do not admit m3u in any case (the hardware bug).

The M30 card is exFAT, so exfatn.drv (table at file 0x7f8, same slot layout)
is the driver that actually runs there - it is patched and checked too.

Exits non-zero on any failure.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

MUSIC_MASK = 0x7E190EA0          # bitmap table [0] at 0x40D1531C (stock)
NEW_MASK = MUSIC_MASK | 0x100 | 0x1000   # bits 8 and 12 added by the patch
DRV_TABLE, EXFAT_TABLE, LOC_TABLE, LOC_BANK_FO, RES_TABLE = 0x780, 0x7F8, 0x49C, 0x12500, 0xC188
MASK_SITES = [0xF98, 0x17FC, 0xBD00, 0x12A1C]

DRV_SLOTS = [(25, b"M3U\x00"), (20, b"M3U8"), (22, b"m3u\x00"), (18, b"m3u8")]
LOC_SLOTS = [(26, b"M3U\x00"), (21, b"M3U8"), (23, b"m3u\x00"), (19, b"m3u8")]
RES_SLOTS = [(25, b"M3U\x00"), (20, b"M3U8"), (18, b"m3u8")]


def classify(table, mask, ext24, base_bit):
    """Model of the matcher loop. base_bit: driver 30, browser 31.

    entry[j] <-> mask bit [base_bit - j]; the loop ends when the index
    reaches 32; entries 0 and "**" end the scan. Exact 24-bit compare.
    Returns True on match.
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


def main(stock_drv, stock_brow, stock_exfat=None):
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    work = tempfile.mkdtemp(prefix="m30vis.")
    drv, brow = os.path.join(work, "fat_32n.drv"), os.path.join(work, "browser.ap")
    exf = os.path.join(work, "exfatn.drv")
    args = [stock_drv, drv]
    if stock_exfat:
        args += [stock_exfat, exf]
    args += [stock_brow, brow]
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_m3uvis.py")] + args,
                       capture_output=True, text=True)
    check(r.returncode == 0, "patch tool ran cleanly")
    if r.returncode:
        print(r.stderr[-800:])
        return 1

    sd, sb = open(stock_drv, "rb").read(), open(stock_brow, "rb").read()
    pd, pb = open(drv, "rb").read(), open(brow, "rb").read()
    se = open(stock_exfat, "rb").read() if stock_exfat else None
    pe = open(exf, "rb").read() if stock_exfat else None

    # 1. exactly the patch sites changed: new bytes in place, all else stock
    sites_d = [(DRV_TABLE + 4 * s, new) for s, new in DRV_SLOTS]
    sites_b = ([(LOC_BANK_FO + LOC_TABLE + 4 * s, new) for s, new in LOC_SLOTS] +
               [(RES_TABLE + 4 * s, new) for s, new in RES_SLOTS] +
               [(off, struct.pack("<I", NEW_MASK)) for off in MASK_SITES])
    ok_d = all(pd[off:off + 4] == new for off, new in sites_d) and all(
        sd[i] == pd[i] for i in range(len(sd))
        if not any(off <= i < off + 4 for off, _ in sites_d))
    ok_b = all(pb[off:off + 4] == new for off, new in sites_b) and all(
        sb[i] == pb[i] for i in range(len(sb))
        if not any(off <= i < off + 4 for off, _ in sites_b))
    check(ok_d, "driver: slots 25/20/22/18 = M3U/M3U8/m3u/m3u8, every other byte stock")
    check(ok_b, "browser: local 26/21/23/19 + resident 25/20/18 + 4 mask words patched, rest stock")
    if se is not None:
        sites_e = [(EXFAT_TABLE + 4 * s, new) for s, new in DRV_SLOTS]
        ok_e = all(pe[off:off + 4] == new for off, new in sites_e) and all(
            se[i] == pe[i] for i in range(len(se))
            if not any(off <= i < off + 4 for off, _ in sites_e))
        check(ok_e, "exfatn.drv (the live driver on the exFAT card): same 4 slots at 0x7f8, rest stock")

    drv_tab = pd[DRV_TABLE:DRV_TABLE + 31 * 4]
    loc_tab = pb[LOC_BANK_FO + LOC_TABLE:LOC_BANK_FO + LOC_TABLE + 32 * 4]

    # 2. driver matcher model over the patched table (patched mask NEW_MASK)
    cases = [
        (NEW_MASK, b"M3U\x00", True,  "driver: .M3U admitted (bit5 slot25)"),
        (NEW_MASK, b"m3u\x00", True,  "driver: .m3u admitted (bit8 slot22) - the hardware case"),
        (NEW_MASK, b"M3U8",   True,  "driver: .M3U8 admitted (bit10 slot20)"),
        (NEW_MASK, b"m3u8",   True,  "driver: .m3u8 admitted (bit12 slot18)"),
        (MUSIC_MASK, b"M3U\x00", True,  "driver: stock mask still admits .M3U (bit5 was already set)"),
        (MUSIC_MASK, b"m3u\x00", False, "driver: stock mask does NOT admit .m3u (reproduces hardware)"),
        (NEW_MASK, b"MP3\x00", True,  "driver: .mp3 still admitted"),
        (NEW_MASK, b"FLAC",   True,  "driver: .flac still admitted (24-bit FLA)"),
        (NEW_MASK, b"AIF\x00", False, "driver: .aif no longer admitted (slot reused)"),
        (NEW_MASK, b"MP2\x00", False, "driver: .mp2 no longer admitted (slot reused)"),
        (NEW_MASK, b"POS\x00", False, "driver: .pos no longer admitted (slot reused)"),
        (NEW_MASK, b"TXT\x00", False, "driver: .txt not admitted under music mask"),
        (0x100, b"m3u\x00", True,   "driver: bit8 alone admits .m3u"),
        (0x1000, b"m3u8", True,     "driver: bit12 alone admits .m3u8"),
        (0x20, b"M3U\x00", True,    "driver: bit5 alone admits .M3U"),
        (0x400, b"M3U8", True,      "driver: bit10 alone admits .M3U8"),
        (NEW_MASK & ~0x100 & ~0x20 & ~0x1000, b"m3u\x00", False, "driver: bits 5+8+12 off removes .m3u"),
        (0, b"M3U\x00", False,      "driver: zero mask admits nothing"),
    ]
    for mask, ext, want, msg in cases:
        check(classify(drv_tab, mask, struct.unpack("<I", ext)[0], 30) == want, msg)

    # 2b. the exFAT driver's table (same slot layout at file 0x7f8) behaves identically
    if se is not None:
        exf_tab = pe[EXFAT_TABLE:EXFAT_TABLE + 31 * 4]
        for mask, ext, want, msg in [
            (NEW_MASK, b"m3u\x00", True,  "exfatn.drv: .m3u admitted - THE hardware case on an exFAT card"),
            (NEW_MASK, b"M3U\x00", True,  "exfatn.drv: .M3U admitted"),
            (NEW_MASK, b"m3u8",   True,  "exfatn.drv: .m3u8 admitted"),
            (NEW_MASK, b"M3U8",   True,  "exfatn.drv: .M3U8 admitted"),
            (NEW_MASK, b"MP3\x00", True,  "exfatn.drv: .mp3 still admitted"),
            (MUSIC_MASK, b"m3u\x00", False, "exfatn.drv: stock table+mask does NOT admit .m3u (hardware bug)"),
            (NEW_MASK, b"AIF\x00", False, "exfatn.drv: .aif no longer admitted (slot reused)"),
        ]:
            check(classify(exf_tab, mask, struct.unpack("<I", ext)[0], 30) == want, msg)
        check(not classify(se[EXFAT_TABLE:EXFAT_TABLE + 31 * 4], NEW_MASK,
                           struct.unpack("<I", b"m3u\x00")[0], 30),
              "exfatn.drv stock table does not admit .m3u even under the new mask")

    # 3. browser-local table model (slot j <-> bit[31-j])
    for mask, ext, want, msg in [
        (NEW_MASK, b"M3U\x00", True,  "browser: .M3U admitted"),
        (NEW_MASK, b"m3u\x00", True,  "browser: .m3u admitted"),
        (NEW_MASK, b"M3U8",   True,  "browser: .M3U8 admitted"),
        (NEW_MASK, b"m3u8",   True,  "browser: .m3u8 admitted"),
        (MUSIC_MASK, b"m3u\x00", False, "browser: stock mask does not admit .m3u (hardware bug)"),
        (NEW_MASK, b"MP3\x00", True,  "browser: .mp3 still admitted"),
        (NEW_MASK, b"AIF\x00", False, "browser: .aif no longer admitted"),
        (0x100, b"m3u\x00", True,    "browser: bit8 alone admits .m3u"),
        (0x1000, b"m3u8", True,      "browser: bit12 alone admits .m3u8"),
    ]:
        check(classify(loc_tab, mask, struct.unpack("<I", ext)[0], 31) == want, msg)

    # 4. the stock tables must NOT admit m3u in any case (the bug we are fixing)
    sdrv_tab = sd[DRV_TABLE:DRV_TABLE + 31 * 4]
    sloc_tab = sb[LOC_BANK_FO + LOC_TABLE:LOC_BANK_FO + LOC_TABLE + 32 * 4]
    check(not classify(sdrv_tab, MUSIC_MASK, struct.unpack("<I", b"M3U\x00")[0], 30),
          "stock driver table does not admit .M3U (reproduces the hardware verdict)")
    check(not classify(sdrv_tab, MUSIC_MASK, struct.unpack("<I", b"m3u\x00")[0], 30),
          "stock driver table does not admit .m3u")
    check(not classify(sloc_tab, MUSIC_MASK, struct.unpack("<I", b"M3U\x00")[0], 31),
          "stock browser table does not admit .M3U")

    shutil.rmtree(work, ignore_errors=True)
    print("test_m3uvis: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))

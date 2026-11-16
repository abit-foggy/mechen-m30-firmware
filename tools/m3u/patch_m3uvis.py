"""Make .m3u/.m3u8 rows visible in the stock file browser (Phase C visibility).

usage: patch_m3uvis.py FAT_IN FAT_OUT EXFAT_IN EXFAT_OUT BROWSER_IN BROWSER_OUT

Three extension tables gate which files the browser lists:

  1. fat_32n.drv, file 0x780 (guest 0xBFC17180) and exfatn.drv, file 0x7f8:
     the drivers' rom_ext_name tables, 31 slots, same layout in both. The two
     .drv files are mutually exclusive resident banks (both load at 0xbfc16c00);
     WHICH ONE RUNS DEPENDS ON THE CARD'S FILESYSTEM - the M30 card is exFAT, so
     exfatn.drv is the live driver there and fat_32n.drv alone was never enough
     (that is why the first patch round still showed no .m3u on hardware).
     The matcher (sub_BFC16D94 in fat_32n.drv at file 0x394, file 0x590 in
     exfatn.drv) loops idx = 1..31, tests mask bit [31-idx] (`sllv` + `slti <0`),
     reads table[idx-1], and matches when (table[idx-1] & 0xFFFFFF) ==
     (ext & 0xFFFFFF). VERIFIED UNDER QEMU (tools/m3u/fsmatchtest.py): the
     compare is an exact, CASE-SENSITIVE 24-bit xor, and the fs delivers the
     extension in the case stored in the long file name - lowercase "m3u" for
     files like "idk.m3u". So a file is listed iff some slot holds its
     extension (exact case) AND the caller's 32-bit mask has that slot's bit set.

  2. browser.ap bank 0x40D14E00 (file 0x12500), local table at 0x40D1529C
     (file 0x1299C): 32 slots, slot j <-> mask bit [31-j] (slot 0 is "***"),
     compared by the fsel classifier 0x40D14E00 via the ROM compare.

  3. browser.ap resident ext array at file 0xC188 (guest 0xBFC16588):
     the per-app registration table music.ap reads from browser.ap.

Slot <-> mask-bit map (both verified against the real code):
  driver: slot s <-> bit(30-s);  browser local: slot j <-> bit(31-j).

The browser's music mask is 0x7e190ea0 (the only scan descriptor,
browser.ap file 0x17fc, plus the fsel bitmap[0] at file 0x12a1c). Its bits
already cover:
  driver slot 25 "AIF"  <-> bit5     browser slot 26 "AIF"  <-> bit5
  driver slot 20 "MP2"  <-> bit10    browser slot 21 "MP2"  <-> bit10

Because the driver compare is case-sensitive and the card's playlists are
lowercase .m3u (long file names), uppercase-only slots are not enough: the
hardware test with only the uppercase slots showed no .m3u at all. We
therefore ALSO repurpose two more spare slots and set their mask bits
(bit8, bit12) in every 0x7e190ea0 copy inside browser.ap:
  driver slot 22 "POS"  <-> bit8     browser slot 23 "POS"  <-> bit8   -> "m3u"
  driver slot 18 "AA "  <-> bit12    browser slot 19 "AA "  <-> bit12  -> "m3u8"

Result: M3U/m3u and M3U8/m3u8 are all admitted (any ext case), while AIF, MP2,
POS and "AA " rows disappear (none exist on the player). Every other byte of
both files is untouched, and the stock bytes at every patch site are asserted
first, so any firmware drift fails the build instead of writing a wrong patch.

  slot content: "M3U\\0" (4d 33 55 00) / "m3u\\0" for .m3u,
                "M3U8" (4d 33 55 38) / "m3u8" for .m3u8
  (the driver compares 24 bits, so the "M3U8" slot also matches .m3u there;
  the browser-local 4-byte compare needs both spellings).

4. browser.ap bank 0x40D14E00, classifier class masks at 0x40D1531C
   (file 0x12A1C) - THIS IS THE CLICK PATH, not the list path. Selecting a
   file row runs the dispatcher 0x40D14F14's file branch (0x40D150F6), which
   calls the classifier 0x40D14E00(cur_file). The classifier loops class
   i = 0..1, mask = classmask[i], slot j = 0..31 with bit (31-j), and
   compares the row's 4-byte ext against table slot j with the ROM compare
   0xBFC16A21(row, slot, 3, 5) - case-insensitive in practice (hardware:
   a lowercase idk.m3u row classified as audio). The mask table at
   0x40D1531C is referenced by exactly one pool word in the whole module
   (the classifier's dword_40D14E74), so its [0]/[1] entries are the
   classifier's class masks and NOTHING else: class[0] = 0x7e190ea0 (audio;
   bits 5/10 -> slots 26/21, 8/12 -> slots 23/19, all four now M3U/M3U8/
   m3u/m3u8 after the slot patch above), class[1] = 0x3000 (bit 12 ->
   slot 19 = m3u8). The dispatcher then reads status =
   u16[0x40D1533C + class*2]: classes 0..4 map to 0x8001..0x8005 (non-zero
   -> launch the engine via 0x780DB28D + 0x780DB2F9, which is why clicking
   an .m3u ran the audio decoder and said "file type not supported"),
   class 5 reads the zero tail at +0x546 (status 0 -> the stock dialog
   gui_dialog_msg(0x8000,3,0x8019) = "File format not supported!", clean
   exit, no engine launch). We therefore CLEAR bits 5+8+10+12 in class[0]
   and bit 12 in class[1], so every m3u/m3u8 row (any case) falls through
   to class 5 instead of being launched as audio. The list filter is the
   SEPARATE resident scan descriptor (file 0x17fc, kept at NEW_MASK), so
   .m3u rows stay visible; no other extension lives in the cleared slots
   anymore, so nothing else changes.
"""
import struct
import sys

DRV_TABLE = 0x780          # fat_32n.drv file offset of rom_ext_name (guest 0xBFC17180)
EXFAT_TABLE = 0x7F8        # exfatn.drv file offset of its identical rom_ext_name table
BANK_FO = 0x12500          # browser.ap file offset of bank 0x40D14E00
LOC_TABLE = 0x49C          # bank offset of the local table (guest 0x40D1529C)
RES_TABLE = 0xC188         # browser.ap resident ext array (guest 0xBFC16588)
CLASS_MASK = 0x51C         # bank offset of the classifier class masks (guest 0x40D1531C)

# (slot, stock bytes, new bytes) per table
DRV_SLOTS = [
    (25, b"AIF\x00", b"M3U\x00"),   # bit5  - .m3u uppercase
    (20, b"MP2\x00", b"M3U8"),      # bit10 - .m3u8
    (22, b"POS\x00", b"m3u\x00"),   # bit8  - .m3u lowercase
    (18, b"AA\x00\x00", b"m3u8"),   # bit12 - .m3u8 lowercase
]
LOC_SLOTS = [
    (26, b"AIF\x00", b"M3U\x00"),   # bit5
    (21, b"MP2\x00", b"M3U8"),      # bit10
    (23, b"POS\x00", b"m3u\x00"),   # bit8
    (19, b"AA \x00", b"m3u8"),      # bit12
]
RES_SLOTS = [
    (25, b"AIF\x00", b"M3U\x00"),
    (20, b"MP2\x00", b"M3U8"),
    (18, b"AA \x00", b"m3u8"),
]

# the music-mask dword copies that gate the LIST filter (scan descriptor at
# 0x17fc plus three resident copies); add bits 8 and 12 so the new lowercase
# slots are actually enabled there. 0x12a1c is NOT in this list: that copy
# is the classifier's class[0] mask (see CLASS_MASK below), not a list mask.
MASK_SITES = [0xF98, 0x17FC, 0xBD00]
MUSIC_MASK = 0x7E190EA0
NEW_MASK = MUSIC_MASK | (1 << 8) | (1 << 12)      # 0x7e191fa0

# classifier class masks (bank 0x40D14E00 + 0x51C = file 0x12A1C): class[0]
# is the audio class (stock 0x7e190ea0), class[1] is 0x3000. After the slot
# patch above, slots 26/21/23/19 hold M3U/M3U8/m3u/m3u8 and their bits are
# 5/10/8/12 in class[0] and 12 in class[1] - clear them all so selecting an
# .m3u/.m3u8 row yields class 5 (status 0, stock dialog) instead of class
# 0/1 (status 0x8001/0x8002, audio engine launch).
CLASS0 = 0x7E190EA0
CLASS1 = 0x00003000
NEW_CLASS0 = CLASS0 & ~((1 << 5) | (1 << 8) | (1 << 10) | (1 << 12))  # 0x7e190a80
NEW_CLASS1 = CLASS1 & ~(1 << 12)                                     # 0x00002000


def patch(path_in, path_out, sites):
    """sites: list of (file_offset, stock_bytes, new_bytes)."""
    d = bytearray(open(path_in, "rb").read())
    for off, stock, new in sites:
        assert len(stock) == len(new)
        got = bytes(d[off:off + len(stock)])
        assert got == stock, "%s @%#x: expected %s, found %s" % (
            path_out, off, stock.hex(), got.hex())
    for off, stock, new in sites:
        d[off:off + len(new)] = new
    # read-back: the new bytes are in place and nothing else moved
    for off, stock, new in sites:
        assert bytes(d[off:off + len(new)]) == new, "%s @%#x read-back failed" % (path_out, off)
    open(path_out, "wb").write(d)
    for off, stock, new in sites:
        print("   %s @%#x: %r -> %r" % (path_out, off, stock, new))


def main(fat_in, fat_out, exfat_in, exfat_out, brow_in, brow_out):
    slots = [(DRV_TABLE + 4 * s, old, new) for s, old, new in DRV_SLOTS]
    patch(fat_in, fat_out, slots)
    patch(exfat_in, exfat_out, [(EXFAT_TABLE + 4 * s, old, new) for s, old, new in DRV_SLOTS])
    patch(brow_in, brow_out,
          [(BANK_FO + LOC_TABLE + 4 * s, old, new) for s, old, new in LOC_SLOTS] +
          [(RES_TABLE + 4 * s, old, new) for s, old, new in RES_SLOTS] +
          [(off, struct.pack("<I", MUSIC_MASK), struct.pack("<I", NEW_MASK))
           for off in MASK_SITES] +
          [(BANK_FO + CLASS_MASK,
            struct.pack("<II", CLASS0, CLASS1),
            struct.pack("<II", NEW_CLASS0, NEW_CLASS1))])
    print("   m3u visibility: M3U/M3U8 (bits 5/10) + m3u/m3u8 (bits 8/12) in fat_32n.drv,"
          " exfatn.drv and the three browser.ap ext tables;"
          " music mask 0x%x -> 0x%x at the 3 list-filter copies" % (MUSIC_MASK, NEW_MASK))
    print("   m3u click divert: classifier class masks 0x%x/0x%x -> 0x%x/0x%x"
          " (bits 5,8,10,12 cleared) so .m3u rows classify as class 5 (dialog)"
          " instead of class 0/1 (audio engine)" % (CLASS0, CLASS1, NEW_CLASS0, NEW_CLASS1))


if __name__ == "__main__":
    main(*sys.argv[1:7])

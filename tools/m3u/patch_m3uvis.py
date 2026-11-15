"""Make .m3u/.m3u8 rows visible in the stock file browser (Phase C visibility).

usage: patch_m3uvis.py DRV_IN DRV_OUT BROWSER_IN BROWSER_OUT

Three extension tables gate which files the browser lists:

  1. fat_32n.drv, file 0x780 (guest 0xBFC17180): the driver's rom_ext_name table,
     31 slots. The matcher at 0xBFC16D94 loops idx = 1..31, tests mask bit
     [31-idx] (`sllv` + `slti <0`), reads table[idx-1], and matches when
     (table[idx-1] & 0xFFFFFF) == (ext & 0xFFFFFF). VERIFIED UNDER QEMU
     (tools/m3u/fsmatchtest.py): the compare is an exact, CASE-SENSITIVE
     24-bit xor, and the fs delivers the extension in the case stored in the
     FAT long file name - lowercase "m3u" for files like "idk.m3u".
     So a file is listed iff some slot holds its extension (exact case) AND
     the caller's 32-bit mask has that slot's bit set.

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
"""
import struct
import sys

DRV_TABLE = 0x780          # fat_32n.drv file offset of rom_ext_name (guest 0xBFC17180)
BANK_FO = 0x12500          # browser.ap file offset of bank 0x40D14E00
LOC_TABLE = 0x49C          # bank offset of the local table (guest 0x40D1529C)
RES_TABLE = 0xC188         # browser.ap resident ext array (guest 0xBFC16588)

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

# every 0x7e190ea0 dword in browser.ap is a copy of the music mask (scan
# descriptor at 0x17fc, fsel bitmap[0] at 0x12a1c, two more resident copies);
# add bits 8 and 12 so the new lowercase slots are actually enabled
MASK_SITES = [0xF98, 0x17FC, 0xBD00, 0x12A1C]
MUSIC_MASK = 0x7E190EA0
NEW_MASK = MUSIC_MASK | (1 << 8) | (1 << 12)      # 0x7e191fa0


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


def main(drv_in, drv_out, brow_in, brow_out):
    patch(drv_in, drv_out, [(DRV_TABLE + 4 * s, old, new) for s, old, new in DRV_SLOTS])
    patch(brow_in, brow_out,
          [(BANK_FO + LOC_TABLE + 4 * s, old, new) for s, old, new in LOC_SLOTS] +
          [(RES_TABLE + 4 * s, old, new) for s, old, new in RES_SLOTS] +
          [(off, struct.pack("<I", MUSIC_MASK), struct.pack("<I", NEW_MASK))
           for off in MASK_SITES])
    print("   m3u visibility: M3U/M3U8 (bits 5/10) + m3u/m3u8 (bits 8/12) in all three ext tables;"
          " music mask 0x%x -> 0x%x in browser.ap" % (MUSIC_MASK, NEW_MASK))


if __name__ == "__main__":
    main(*sys.argv[1:5])

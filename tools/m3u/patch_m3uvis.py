"""Make .m3u/.m3u8 rows visible in the stock file browser (Phase C visibility).

usage: patch_m3uvis.py DRV_IN DRV_OUT BROWSER_IN BROWSER_OUT

Two extension tables gate which files the browser lists:

  1. fat_32n.drv, file 0x780 (guest 0xBFC17180): the driver's rom_ext_name table,
     31 slots. The classifier at 0xBFC16D94 loops j = 0..30, tests mask bit
     [30-j] (`sllv` + `slti <0`), reads table[j], breaks on 0 / "**", and
     matches when (table[j] & 0xFFFFFF) == (ext & 0xFFFFFF). So a file is
     listed iff some slot holds its extension AND the caller's 32-bit mask
     has that slot's bit set.

  2. browser.ap bank 0x40D14E00 (file 0x12500), local table at 0x40D1529C
     (file 0x1299C): 32 slots, slot j <-> mask bit [31-j] (slot 0 is "***").
     The bank registers these entries with the driver (cmd 5) for every bit
     set in its mode bitmap; the bitmap table at 0x40D1531C starts with the
     music mask 0x7e190ea0.

The browser's mask is the music bitmap 0x7e190ea0 (that is what makes music
rows appear; an ALLFILE mask would already list .m3u, and the hardware test
showed it does not). Its set bits map to these slots:

  driver table:  bit5  -> slot 25 "AIF",  bit10 -> slot 20 "MP2"
  browser table: bit5  -> slot 26 "AIF",  bit10 -> slot 21 "MP2"

So we repurpose exactly those two pairs of slots (AIF and MP2 — neither
exists on the player) for M3U/M3U8. Every other byte of both files is
untouched, and the stock bytes at the four patch sites are asserted first,
so any firmware drift fails the build instead of writing a wrong patch.

  slot content: "M3U\\0" (4d 33 55 00) for .m3u, "M3U8" (4d 33 55 38) for .m3u8
  (the driver compares 24 bits, so "M3U8" also matches .m3u there; the
  browser-local 4-byte compare needs both spellings).
"""
import sys

DRV_TABLE = 0x780          # fat_32n.drv file offset of rom_ext_name (guest 0xBFC17180)
DRV_SLOT_AIF, DRV_SLOT_MP2 = 25, 20
BANK_FO = 0x12500          # browser.ap file offset of bank 0x40D14E00
LOC_TABLE = 0x49C          # bank offset of the local table (guest 0x40D1529C)
LOC_SLOT_AIF, LOC_SLOT_MP2 = 26, 21

STOCK_AIF = b"AIF\x00"
STOCK_MP2 = b"MP2\x00"
NEW_M3U = b"M3U\x00"
NEW_M3U8 = b"M3U8"


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
    patch(drv_in, drv_out, [
        (DRV_TABLE + 4 * DRV_SLOT_AIF, STOCK_AIF, NEW_M3U),
        (DRV_TABLE + 4 * DRV_SLOT_MP2, STOCK_MP2, NEW_M3U8),
    ])
    patch(brow_in, brow_out, [
        (BANK_FO + LOC_TABLE + 4 * LOC_SLOT_AIF, STOCK_AIF, NEW_M3U),
        (BANK_FO + LOC_TABLE + 4 * LOC_SLOT_MP2, STOCK_MP2, NEW_M3U8),
    ])
    print("   m3u visibility: AIF->M3U (bit5), MP2->M3U8 (bit10) in both ext tables")


if __name__ == "__main__":
    main(*sys.argv[1:5])

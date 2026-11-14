"""Insert the M3U selection hook into browser.ap (Phase C, first hardware candidate).

usage: patch_m3uhook.py SRC.ap OUT.ap HOOK.bin HOOK_ADDR SLOT_ADDR
  HOOK_ADDR/SLOT_ADDR are the linked addresses of m30u_hook / m30u_branch_slot (from nm).

Patch site: bank 0x40D14E00 (file 0x12500), the selected-file wrapper's first
instruction at 0x40D15270 (`save 0x38, $ra,$s1`, halfword 0x64d7). The
wrapper's single caller reaches it with `jal`, and the selected row's
file_brow_t pointer sits at 0($s1) — both verified by disassembly. The hook
goes in the bank's verified-zero tail (stock bytes +0x546..+0x600 are zero;
the live content ends at +0x545).

The patch is two writes:
  1. wrapper entry: `save 0x38,$ra,$s1` -> `b m30u_hook`  (2 bytes)
  2. hook's branch slot: 0x0000 -> `b 0x40D15272`          (2 bytes)
Everything else in browser.ap is untouched, including the scroll-acceleration
patch in bank 0x48714400.

Every assertion is deterministic: the stock bytes at the patch site, the zero
tail, the blob's shape, and a read-back of both branch encodings.
"""
import struct
import sys

BANK, BANK_FO, SIZE = 0x40D14E00, 0x12500, 0x600
WRAP = 0x40D15270                       # the wrapper's first instruction
TAIL_FROM = 0x546                       # the verified-zero tail in the bank
HOOK_AT = 0x54C                         # where the blob is placed in the bank
CONT = 0x40D15272                       # the wrapper's second instruction
STOCK_WRAP = bytes.fromhex("d7640401")  # save 0x38,$ra,$s1; addiu $s1,$sp,0x10


def b_enc(site, target):
    """MIPS16e `b` (unconditional, 11-bit signed halfword offset)."""
    off = (target - (site + 2)) // 2
    assert -1024 <= off < 1024, "branch out of range: %#x -> %#x" % (site, target)
    return struct.pack("<H", 0x1000 | (off & 0x7FF))


def b_dec(site, half):
    """Decode a `b` back to its target, for the read-back check."""
    off = struct.unpack("<H", half)[0] & 0x7FF
    if off >= 0x400:
        off -= 0x800
    return site + 2 + off * 2


def main(src, out, blob_path, hook_addr, slot_addr):
    hook, slot = int(hook_addr, 0), int(slot_addr, 0)
    blob = open(blob_path, "rb").read()
    d = bytearray(open(src, "rb").read())
    b = BANK_FO

    # --- deterministic original-byte assertions
    wrap_fo = b + WRAP - BANK
    assert d[wrap_fo:wrap_fo + 4] == STOCK_WRAP, \
        "wrapper prologue at %#x is not stock: %s" % (WRAP, d[wrap_fo:wrap_fo + 4].hex())
    tail = d[b + TAIL_FROM:b + SIZE]
    assert not any(tail), "bank tail from +%#x is not zero" % TAIL_FROM
    assert len(blob) <= SIZE - HOOK_AT, \
        "hook blob is %d bytes, only %d fit" % (len(blob), SIZE - HOOK_AT)
    assert struct.unpack_from("<I", blob, len(blob) - 4)[0] == 0x48AD4A2D, \
        "the hook's dialog pool word is missing"
    # the entry can sit anywhere inside the placed blob (alignment padding
    # depends on the compiler flags); only range matters, the read-back below
    # proves the branch
    assert BANK + HOOK_AT <= hook < BANK + HOOK_AT + len(blob), \
        "the hook entry %#x is outside the blob placement %#x..%#x" % (
            hook, BANK + HOOK_AT, BANK + HOOK_AT + len(blob))
    assert BANK + HOOK_AT < slot < BANK + HOOK_AT + len(blob), \
        "the branch slot %#x is outside the blob" % slot

    # --- write 1: the wrapper entry branches to the hook
    d[wrap_fo:wrap_fo + 2] = b_enc(WRAP, hook)
    # --- write 2: the blob goes into the tail, then its slot is encoded
    d[b + HOOK_AT:b + HOOK_AT + len(blob)] = blob
    slot_fo = b + slot - BANK
    assert struct.unpack_from("<H", d, slot_fo)[0] == 0, "branch slot is not the placeholder"
    struct.pack_into("<H", d, slot_fo, *struct.unpack("<H", b_enc(slot, CONT)))

    # --- read-back verification of both branches
    assert b_dec(WRAP, d[wrap_fo:wrap_fo + 2]) == hook, "wrapper branch read-back failed"
    assert b_dec(slot, d[slot_fo:slot_fo + 2]) == CONT, "hook branch read-back failed"
    assert d[b + slot - BANK + 4:][:4] == blob[-4:], "the pool word did not survive"

    open(out, "wb").write(d)
    print("   m3u hook: wrapper %#x -> hook %#x (blob %d bytes at bank +%#x),"
          " slot %#x -> %#x" % (WRAP, hook, len(blob), HOOK_AT, slot, CONT))


if __name__ == "__main__":
    main(*sys.argv[1:6])
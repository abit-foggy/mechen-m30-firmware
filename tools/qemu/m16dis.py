#!/usr/bin/env python3
"""Disassemble a firmware range in genuine MIPS16e.

Why this is needed
------------------
Neither of the two obvious candidates decodes MIPS16e:

* the host binutils `-m mips:micromips` decodes **microMIPS**, a different
  encoding from MIPS16e, so it produced `.short` garbage on MIPS16e bytes;
* QEMU's `-d in_asm` *translates* MIPS16e correctly (its `24Kc` model has
  ASE_MIPS16, and JR/JALR/JALX switch ISA mode from bit 0 of the target), but
  its disassembler never prints it: `print_insn_mips16()` is inside `#if 0`
  in `disas/mips.c` and `mips16_opcodes` is not even linked. So `-d in_asm`
  shows MIPS32-style output while the CPU is executing MIPS16e, which is
  exactly the trap that invalidated earlier analysis.

This tool therefore decodes MIPS16e from a table **derived from GAS**
(`mips64-linux-gnu-as -mmips16 -EL`), not from a disassembler that guesses.
Every instruction in `m16_table.txt` is an encoding GAS actually produced, so a
match is a verified encoding and a miss is honestly reported as `?` rather than
mis-decoded.

Coverage is deliberately partial and the tool says so: it covers the common
3-register, load/store, immediate and branch forms over the eight registers
MIPS16e's compact fields can address. Anything it cannot match prints as `?`.

Usage:
    m16dis.py [options] FILE OFFSET LENGTH [BASE]

Options:
    --raw          print the raw hex alongside each instruction
    --unknown-stats print how many halfwords could not be decoded

LENGTH is in bytes; halfwords are little-endian, as the firmware's.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, "m16_table.txt")


def load_table():
    """{halfword tuple: text}. Two-halfword entries are tried first."""
    t2 = {}
    t1 = {}
    with open(TABLE) as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if not ln or " " not in ln:
                continue
            words, txt = ln.split(" ", 1)
            ws = tuple(int(w, 16) for w in words.split(","))
            if len(ws) == 1:
                t1[ws[0]] = txt
            else:
                t2[ws] = txt
    return t1, t2


def decode(data, base, t1, t2):
    """Decode a byte string, 16 bits at a time, following GAS's instruction
    boundaries. Returns (rows, stats)."""
    rows = []
    unknown = 0
    total = 0
    i = 0
    while i + 1 < len(data) + 1 and i < len(data):
        if i + 1 >= len(data) + 1 or i + 2 > len(data):
            rows.append((base + i, None, None))
            break
        import struct
        h = struct.unpack_from("<H", data, i)[0]
        total += 1
        if i + 4 <= len(data):
            h2 = struct.unpack_from("<H", data, i + 2)[0]
            pair = (h, h2)
            if pair in t2:
                rows.append((base + i, pair, t2[pair]))
                i += 4
                continue
        if h in t1:
            rows.append((base + i, (h,), t1[h]))
            i += 2
            continue
        rows.append((base + i, (h,), None))
        unknown += 1
        i += 2
    return rows, {"instructions": total, "unknown": unknown}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("offset", type=lambda x: int(x, 0))
    ap.add_argument("length", type=lambda x: int(x, 0))
    ap.add_argument("base", nargs="?", type=lambda x: int(x, 0), default=0)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--unknown-stats", action="store_true")
    a = ap.parse_args()

    try:
        blob = open(a.file, "rb").read()
    except OSError as e:
        print("m16dis: %s" % e)
        return 1
    if a.offset < 0 or a.length <= 0 or a.offset + a.length > len(blob):
        print("m16dis: range %#x+%#x outside file size %#x"
              % (a.offset, a.length, len(blob)))
        return 1

    t1, t2 = load_table()
    rows, stats = decode(blob[a.offset:a.offset + a.length], a.base, t1, t2)

    if a.raw:
        print("; file %s offset %#x length %#x base %#x"
              % (a.file, a.offset, a.length, a.base))
    for addr, words, txt in rows:
        hexes = ",".join("%04x" % w for w in words) if words else ""
        label = txt if txt else "?"
        if a.raw:
            print("%08x  %-10s %s" % (addr, hexes, label))
        else:
            print("%08x  %s" % (addr, label))
    if a.unknown_stats:
        print("; %d halfwords, %d undecoded (%.0f%% coverage)"
              % (stats["instructions"], stats["unknown"],
                 100.0 * (stats["instructions"] - stats["unknown"])
                 / max(1, stats["instructions"])))
    return 0 if stats["instructions"] else 2


if __name__ == "__main__":
    sys.exit(main())

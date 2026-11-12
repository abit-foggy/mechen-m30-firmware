#!/usr/bin/env python3
"""IDA headless analysis of M30 firmware overlay banks as MIPS16e.

IDA needs two things that are easy to get wrong:

1. the processor is `mipsl` (`-pmipsl`);
2. the MIPS16e encoding must be selected explicitly. IDA models the
   MIPS32/MIPS16/microMIPS choice as a *virtual register* named `mips16`
   (index 67 in the MIPS processor's register list), settable per segment via
   `idc.set_default_sreg_value(segment_ea, "mips16", 1)`. Without it IDA prints
   MIPS32 mnemonics over MIPS16e bytes, which is silently wrong.

This script is the `-S` script for `idat`; it reads a small spec from
/tmp/m30ida_spec.txt and writes the disassembly to /tmp/m30ida_out.txt.

Spec file: three lines -- segment base, target address, instruction count.
"""

import os
import struct
import sys

import idc
import ida_bytes
import ida_auto
import ida_idp
import ida_segment
import idautils

OUT = open("/tmp/m30ida_out.txt", "w")


def p(*a):
    OUT.write(" ".join(str(x) for x in a) + "\n")


def main():
    try:
        spec = [l.strip() for l in open("/tmp/m30ida_spec.txt") if l.strip()]
    except OSError:
        OUT.write("missing /tmp/m30ida_spec.txt\n")
        OUT.close()
        return

    target = int(spec[0], 0)
    count = int(spec[1], 0)

    seg = next(idautils.Segments())
    idc.set_default_sreg_value(seg, "mips16", 1)
    base = idc.get_segm_start(seg)

    # extra banks may be attached by the caller through /tmp/m30ida_extra.txt,
    # one "load offset file" per line, so cross-references resolve
    try:
        for ln in open("/tmp/m30ida_extra.txt"):
            off, path = ln.split()
            off = int(off, 0)
            data = open(path, "rb").read()
            ida_segment.add_segm(0, off, off + len(data), "bank", "DATA")
            ida_bytes.put_bytes(off, data)
            idc.set_default_sreg_value(off, "mips16", 1)
    except OSError:
        pass

    ida_auto.auto_wait()

    p("=== MIPS16e decode at %#x (segment base %#x) ===" % (target, base))
    ea = target
    for _ in range(count):
        idc.create_insn(ea)
        sz = idc.get_item_size(ea) or 2
        raw = " ".join("%02x" % b for b in ida_bytes.get_bytes(ea, sz))
        p("  %#010x  %-20s %s" % (ea, raw, idc.generate_disasm_line(ea, 0) or ""))
        ea += sz

    p("")
    p("=== control flow out of the routine ===")
    ea = target
    for _ in range(count):
        idc.create_insn(ea)
        sz = idc.get_item_size(ea) or 2
        nm = idc.print_insn_mnem(ea)
        if nm in ("jal", "jalr", "j", "jr", "b", "beqz", "bnez") and nm != "jr":
            for op in range(3):
                try:
                    v = idc.get_operand_value(ea, op)
                except Exception:
                    continue
                if v:
                    p("  %#x %-6s -> %#x" % (ea, nm, v))
        ea += sz
    OUT.close()


main()

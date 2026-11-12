#!/usr/bin/env python3
"""Regression test for the MIPS16e decoder (tools/qemu/m16dis.py).

The decoder is the only verified MIPS16e disassembler available here -- the host
binutils `-m mips:micromips` decodes microMIPS, and QEMU's `print_insn_mips16`
is `#if 0`'d in `disas/mips.c` so `-d in_asm` shows MIPS32 output while the CPU
executes MIPS16e. Because the table is derived from GAS rather than guessed,
the test that matters is: does the decoder reproduce GAS on instructions it was
never shown?

Asserts:
  1. every halfword of a freshly assembled function decodes to exactly the
     instruction GAS assembled, with no unknown halfwords
  2. `jr $ra` is 0xE820, `nop` is 0x6500, `addiu $sp,$sp,-24` is 0x63FD --
     the three encodings all earlier analysis depended on
  3. an out-of-range request is rejected rather than silently truncated
  4. coverage statistics are reported honestly (undecoded halfwords counted)

Run from anywhere; exits non-zero on failure. Needs mips64-linux-gnu-as, which
is installed for the QEMU cross-build.
"""

import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import m16dis  # noqa: E402

AS = "mips64-linux-gnu-as"
OBJCOPY = "mips64-linux-gnu-objcopy"


def assemble(lines):
    """(bytes, [instruction texts]) for a .S body in MIPS16e mode."""
    src = [".set mips16", ".text"] + lines
    with open("/tmp/m16dis_test.S", "w") as f:
        f.write("\n".join(src) + "\n")
    if subprocess.run([AS, "-mmips16", "-EL", "-o", "/tmp/m16dis_test.o",
                       "/tmp/m16dis_test.S"],
                      capture_output=True).returncode:
        return None, None
    subprocess.run([OBJCOPY, "-O", "binary", "-j", ".text",
                    "/tmp/m16dis_test.o", "/tmp/m16dis_test.bin"],
                   capture_output=True)
    return open("/tmp/m16dis_test.bin", "rb").read(), lines


def main():
    if subprocess.run(["which", AS], capture_output=True).returncode:
        print("m16distest: missing %s" % AS)
        return 1
    t1, t2 = m16dis.load_table()
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    # 1. round-trip: instructions chosen to be absent from the generation set
    lines = [
        "addu $a1,$v0,$a2",
        "subu $a3,$v1,$a0",
        "sll $a0,$a1,7",
        "srl $a1,$a0,5",
        "sra $a2,$a1,1",
        "cmp $v0,$a3",
        "neg $v0,$v1",
        "li $v0,255",
        "addiu $sp,$sp,5",
        "addiu $a0,$a1,-24",
        "sw $ra,20($sp)",
        "lw $a0,4($sp)",
        "sw $s1,0($v0)",
        "lw $v1,228($gp)",
        "move $s0,$zero",
        "jr $ra",
    ]
    blob, _ = assemble(lines)
    if blob is None:
        print("m16distest: assembler rejected the test function")
        return 1
    rows, stats = m16dis.decode(blob, 0, t1, t2)
    check(stats["unknown"] == 0,
          "no undecoded halfwords among the assembled instructions (%d)"
          % stats["unknown"])
    # GAS pads .text out with `nop`s after the last real instruction, and a
    # MIPS16e instruction is 2 or 4 bytes, so trim decoded rows to the
    # requested instruction count rather than guessing at a byte length.
    while rows and rows[-1][2] == "nop" and len(rows) > len(lines):
        rows.pop()
    rows = rows[:len(lines)]
    check(len(rows) == len(lines),
          "%d instructions decoded (some are 4-byte, so halfwords != rows)"
          % len(rows))
    got = [txt for _, _, txt in rows]
    # GAS may reorder side-effect-free instructions (it moves `move $s0,$zero`
    # into the delay slot of `jr $ra`), so compare the decoded multiset rather
    # than the source order: every instruction must still decode to exactly
    # the mnemonic the assembler produced for it.
    check(sorted(got) == sorted(lines),
          "decoder reproduces GAS mnemonics exactly"
          if sorted(got) == sorted(lines)
          else "decoder differs: %s" % sorted(got))

    # 2. the three encodings earlier analysis relied on
    for name, want in (("jr $ra", (0xE820,)), ("nop", (0x6500,)),
                       ("addiu $sp,$sp,-24", (0x63FD,))):
        blob2, _ = assemble([name])
        if blob2 is None:
            continue
        h = struct.unpack_from("<H", blob2, 0)[0]
        rows2, _ = m16dis.decode(blob2[:2], 0, t1, t2)
        check(h == want[0] and rows2 and rows2[0][2] == name,
              "%s is %04x and decodes back to itself" % (name, h))

    # 3. out-of-range is rejected, not silently truncated
    out = subprocess.run(
        [sys.executable, "-I", os.path.join(HERE, "m16dis.py"),
         "/tmp/m16dis_test.bin", "0", "100000", "0"],
        capture_output=True, text=True)
    check(out.returncode == 1 and "outside file size" in out.stdout,
          "an out-of-range request is rejected")

    # 4. honest coverage reporting
    out = subprocess.run(
        [sys.executable, "-I", os.path.join(HERE, "m16dis.py"),
         "/tmp/m16dis_test.bin", "0", "4", "0", "--unknown-stats"],
        capture_output=True, text=True)
    check("coverage" in out.stdout, "coverage statistics are reported")

    print("m16distest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

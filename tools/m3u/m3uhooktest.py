#!/usr/bin/env python3
"""Build and run the M3U selection-hook test under QEMU.

The test (tools/m3u/m3uhooktest.c) calls the ACTUAL patched bytes: the patch
tool's 2-byte wrapper-entry branch is placed at 0x40D15270 and the hook blob
(with its branch slot encoded, exactly as patch_m3uhook.py writes it) at
0x40D1534C, with recording stand-ins for gui_dialog_msg (0x48AD4A2C) and the
wrapper's continuation (0x40D15272). Cases cover M3U/M3U8 in both padding
styles and both cases, plus FLAC/MP3/M3UX pass-through.

usage: m3uhooktest.py   (exits non-zero on any failure)
"""
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CROSS = os.environ.get("CROSS", "mips64-linux-gnu-")
QEMU = os.environ.get("QEMU", "qemu-mipsel-static")
CFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mips16", "-Os", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-fno-builtin"]
HFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mno-mips16", "-O1", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-fno-builtin",
          "-nostdlib"]

HOOK_AT, CONT, SLOT_PLACE = 0x40D1534C, 0x40D15272, 0x40D15398


def enc_b(site, target):
    """MIPS16e `b`, exactly as patch_m3uhook.py writes it."""
    off = (target - (site + 2)) // 2
    assert -1024 <= off < 1024
    return struct.pack("<H", 0x1000 | (off & 0x7FF))


def main():
    work = tempfile.mkdtemp(prefix="m30hook.")
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    def run(cmd, what, cwd=work):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if r.returncode:
            print("FAIL  %s\n%s" % (what, r.stderr[-600:]))
            sys.exit(2)

    # the hook blob: from the firmware build when M30_HOOK_BIN is set (the
    # build's own flags shift the entry a few bytes; the placement assertions
    # adapt), otherwise built exactly as the firmware build does
    env_bin = os.environ.get("M30_HOOK_BIN")
    if env_bin:
        import shutil
        shutil.copy(env_bin, os.path.join(work, "hook.bin"))
        hook_addr = int(os.environ.get("M30_HOOK_ADDR", "0x40d1534c"), 16)
        slot_addr = int(os.environ.get("M30_HOOK_SLOT", "0x40d15394"), 16)
        check(True, "using the firmware build's blob (%s)" % env_bin)
    else:
        run([CROSS + "gcc"] + CFLAGS + ["-x", "assembler-with-cpp", "-c",
             "-o", "hook.o", os.path.join(HERE, "m3uhook.S")], "hook did not assemble")
        run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-Ttext=%#x" % HOOK_AT,
             "-e", "m30u_hook", "-o", "hook.elf", "hook.o"], "hook did not link")
        run([CROSS + "objcopy", "-O", "binary", "-j", ".text", "hook.elf", "hook.bin"],
            "hook binary extraction failed")
    if not env_bin:
        syms = {}
        for line in subprocess.run([CROSS + "nm", "hook.elf"], capture_output=True,
                                   text=True, cwd=work).stdout.splitlines():
            parts = line.split()
            if len(parts) == 3:
                syms[parts[2]] = int(parts[0], 16)
        hook_addr = syms["m30u_hook"]
        slot_addr = syms["m30u_branch_slot"]
        check(0x40D15350 <= hook_addr <= 0x40D15360,
              "the hook entry links in the bank tail (got %#x)" % hook_addr)
        check(0x40D15380 <= slot_addr <= 0x40D153B0,
              "the branch slot links in the bank tail (got %#x)" % slot_addr)

    # encode the slot into the blob, exactly as the patch tool does
    blob = bytearray(open(os.path.join(work, "hook.bin"), "rb").read())
    slot_off = slot_addr - HOOK_AT
    assert struct.unpack_from("<H", blob, slot_off)[0] == 0, "slot is not the placeholder"
    struct.pack_into("<H", blob, slot_off, *struct.unpack("<H", enc_b(slot_addr, CONT)))
    open(os.path.join(work, "blob.bin"), "wb").write(blob)

    # the harness (MIPS32); the cont/dlg stand-ins are extracted to raw
    # binaries so every piece lands byte-exactly (MIPS16e code cannot be
    # realigned by the linker without shifting its pc-relative branches)
    run([CROSS + "gcc"] + HFLAGS + ["-c", "-o", "test.o",
         os.path.join(HERE, "m3uhooktest.c")], "the harness did not compile")
    # the continuation stand-in: pure MIPS16e asm, byte-placed at 0x40D15272
    run([CROSS + "gcc"] + CFLAGS + ["-x", "assembler-with-cpp", "-c",
         "-o", "cont.o", os.path.join(HERE, "m3ucont.S")], "cont did not assemble")
    run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-Ttext=0x40D15272",
         "-e", "test_cont", "-o", "cont.elf", "cont.o"], "cont did not link")
    run([CROSS + "objcopy", "-O", "binary", "-j", ".text", "cont.elf", "cont.bin"],
        "cont extraction failed")
    run([CROSS + "objcopy", "-O", "binary", "-j", ".text.dlg", "test.o", "dlg.bin"],
        "dlg extraction failed")
    open(os.path.join(work, "entry.bin"), "wb").write(enc_b(0x40D15270, hook_addr))
    for name in ("entry", "blob", "cont", "dlg"):
        with open(os.path.join(work, name + ".s"), "w") as f:
            f.write('\t.section .%s_bin,"ax"\n\t.incbin "%s.bin"\n' % (name, {"blob": "blob"}.get(name, name)))
        run([CROSS + "as", "-EL", "-mabi=32", "-mips32", "-o", name + ".o", name + ".s"],
            name + " did not assemble")

    ld = os.path.join(work, "hooktest.ld")
    with open(ld, "w") as f:
        f.write("""ENTRY(_start)
SECTIONS
{
    . = 0x00400000;
    .text : { test.o(.text .text.startup) }
    . = 0x40D15270;
    .entry : { entry.o(.entry_bin) }
    . = 0x40D15272;
    .cont : { cont.o(.cont_bin) }
    . = 0x%08x;
    .hook : { blob.o(.blob_bin) }
    . = 0x48AD4A2C;
    .dlg : { dlg.o(.dlg_bin) }
    . = 0x10000000;
    .testram : { *(.testram) *(.data) *(.rodata*) *(.sbss) *(.bss) *(COMMON) }
    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) }
}
""" % HOOK_AT)
    run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-T", ld, "-o", "hooktest.elf",
         "test.o", "entry.o", "blob.o", "cont.o", "dlg.o"], "the hook test did not link")

    if os.environ.get("M30_HOOK_KEEP"):
        print("      workdir: " + work)
    r = subprocess.run([QEMU, "-cpu", "24Kc", "./hooktest.elf"], cwd=work,
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace").splitlines()

    check(r.returncode == 0, "the hook test exited 0 (got %d)" % r.returncode)
    check(any("ALL PASS" in l for l in out), "every in-emulation hook check passed")
    if rc == 0:
        for l in out:
            if l.startswith("ISO"):
                print("      " + l)
    for l in out:
        if l.startswith(("FAIL", "hook", "ALL")):
            print("      " + l)

    print("m3uhooktest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
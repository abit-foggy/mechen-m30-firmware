#!/usr/bin/env python3
"""Test the M3U play-on-click + mengine track-stepper patch.

usage: test_m3uplay.py STOCK_BROWSER.ap [PATCHED_BROWSER.ap [STOCK_MENGINE.ap PATCHED_MENGINE.ap]]
env:   CROSS, QEMU, HOSTCC, and from build.sh --test:
       M30_PLAY_BIN, M30_PLAY_ELF, M30_MTRAMP_BIN, M30_MTRAMP_ELF, M30_MSTEP_BIN, M30_MSTEP_ELF

Four parts:
  1. patch_m3uplay.py applied to temp copies of stock browser.ap + mengine.ap:
     all stock assertions hold and only the exact patch regions change.
  2. production blobs (when env vars are set): sizes, entry symbols, no
     writable data, and patched binary read-backs.
  3. host -m32 run of m3uplaytest.c + m3uplay.c + m3u_meng.c against an
     exFAT VFS mock (including <0x80 vfs_dir rejection, UTF-8/UTF-16LE,
     long names, Repeat Off/All/One, Prev, Byno, and reversible Shuffle).
  4. QEMU MIPS16e tests of BOTH real assembly trampolines:
     - browser.ap 0x40D15194 -> m3uplay_tramp (0x400D4CD0): 0x8001 stores
       4($s1) and jumps to loc_40D15200; class 0..5 returns to 0x40D15198.
     - mengine.ap m3u_meng_tramp (0x7A053338): setloc arms/disarms COUNT/POS
       and next/prev/byno dispatch to m3u_meng_step vs stock handlers.
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
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-fno-builtin",
          "-nostdlib", "-fno-toplevel-reorder", "-fno-jump-tables",
          "-fno-asynchronous-unwind-tables", "-falign-functions=4"]
HFLAGS = ["-EL", "-mabi=32", "-march=mips32", "-mno-mips16", "-O1", "-G0",
          "-mno-abicalls", "-fno-pic", "-ffreestanding", "-fno-builtin", "-nostdlib"]

CLICK_FO, CLICK_NEW = 0x12894, bytes.fromhex("60183453")
POOL_FO, POOL_STOCK = 0x4594, 0xBFC16A2D
BLOB_FO, BLOB_MAX, TRAMP = 0x23D0, 0x730, 0x400D4CD0

M_TRAMP_FO, M_TRAMP_VA, M_TRAMP_MAX = 0x5C38, 0x7A053338, 0xC8
M_STEP_FO, M_STEP_VA, M_STEP_MAX = 0xCB00, 0x7B268000, 0x600


def main():
    stock_brow = sys.argv[1]
    patched_brow = sys.argv[2] if len(sys.argv) > 2 else None
    stock_meng = sys.argv[3] if len(sys.argv) > 3 else None
    patched_meng = sys.argv[4] if len(sys.argv) > 4 else None
    work = tempfile.mkdtemp(prefix="m30play.")
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    def run(cmd, what, cwd=work):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        if r.returncode:
            print("FAIL  %s\n%s" % (what, r.stderr[-800:]))
            sys.exit(2)
        return r

    def nm_syms(elf):
        syms = {}
        for line in subprocess.run([CROSS + "nm", elf], capture_output=True, text=True,
                                   cwd=work).stdout.splitlines():
            p = line.split()
            if len(p) == 3:
                syms[p[2]] = int(p[0], 16)
        return syms

    def no_writable(elf):
        sz = subprocess.run([CROSS + "size", "-A", elf], capture_output=True, text=True,
                            cwd=work).stdout
        return not any(
            l.split()[0].startswith((".data", ".sdata", ".bss", ".sbss")) and int(l.split()[1]) > 0
            for l in sz.splitlines() if len(l.split()) >= 2 and l.split()[1].isdigit()
        )

    # ---- part 1: patch_m3uplay.py on temp copies of stock binaries --------
    dummy_b = os.path.join(work, "dummy_b.bin")
    dummy_mt = os.path.join(work, "dummy_mt.bin")
    dummy_ms = os.path.join(work, "dummy_ms.bin")
    open(dummy_b, "wb").write(bytes(range(64)))
    open(dummy_mt, "wb").write(bytes(range(32)))
    open(dummy_ms, "wb").write(bytes(range(64)))
    out_b = os.path.join(work, "patched_b.ap")
    out_m = os.path.join(work, "patched_m.ap")

    args = [sys.executable, "-I", os.path.join(HERE, "patch_m3uplay.py"),
            stock_brow, out_b, dummy_b, hex(TRAMP)]
    if stock_meng:
        args += [stock_meng, out_m, dummy_mt, dummy_ms,
                 hex(M_TRAMP_VA), hex(M_TRAMP_VA + 8), hex(M_TRAMP_VA + 12), hex(M_TRAMP_VA + 16)]
    r = subprocess.run(args, capture_output=True, text=True)
    check(r.returncode == 0, "patch_m3uplay.py runs on stock binaries (%s)" % r.stderr.strip()[-200:])
    if r.returncode == 0:
        a = open(stock_brow, "rb").read()
        b = open(out_b, "rb").read()
        check(len(a) == len(b), "patched browser.ap keeps stock size")
        check(b[CLICK_FO:CLICK_FO + 4] == CLICK_NEW, "click site 0x12894 = jal 0x400D4CD0")
        check(struct.unpack_from("<I", b, POOL_FO)[0] == POOL_STOCK, "browser fetch pool stays stock")
        check(b[BLOB_FO:BLOB_FO + 64] == bytes(range(64)), "browser blob written at file 0x23D0")
        check(not any(b[BLOB_FO + 64:BLOB_FO + BLOB_MAX]), "rest of browser tail stays zero")
        if stock_meng:
            am = open(stock_meng, "rb").read()
            bm = open(out_m, "rb").read()
            check(len(am) == len(bm), "patched mengine.ap keeps stock size")
            check(bm[M_TRAMP_FO:M_TRAMP_FO + 32] == bytes(range(32)), "mengine tramp at 0x5C38")
            check(bm[M_STEP_FO:M_STEP_FO + 64] == bytes(range(64)), "mengine step at 0xCB00")

    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_m3uplay.py"),
                        stock_brow, out_b, dummy_b, hex(0x400D4CD8)],
                       capture_output=True, text=True)
    check(r.returncode != 0, "patch tool rejects tramp address != 0x400D4CD0")

    # ---- part 2: production blobs & patched outputs -----------------------
    pbin, pelf = os.environ.get("M30_PLAY_BIN"), os.environ.get("M30_PLAY_ELF")
    mtbin, mtelf = os.environ.get("M30_MTRAMP_BIN"), os.environ.get("M30_MTRAMP_ELF")
    msbin, mself = os.environ.get("M30_MSTEP_BIN"), os.environ.get("M30_MSTEP_ELF")
    if pbin and pelf:
        blob = open(pbin, "rb").read()
        syms = nm_syms(pelf)
        check(len(blob) <= BLOB_MAX, "browser blob fits (%d <= %d)" % (len(blob), BLOB_MAX))
        check(syms.get("m3uplay_tramp") == TRAMP, "m3uplay_tramp at 0x400D4CD0")
        check(no_writable(pelf), "browser blob has no writable data")
        if patched_brow:
            d = open(patched_brow, "rb").read()
            check(d[CLICK_FO:CLICK_FO + 4] == CLICK_NEW, "built browser.ap: click site patched")
            check(d[BLOB_FO:BLOB_FO + len(blob)] == blob, "built browser.ap: blob in place")
    if mtbin and mtelf and msbin and mself:
        mt = open(mtbin, "rb").read()
        ms = open(msbin, "rb").read()
        mtsyms = nm_syms(mtelf)
        mssyms = nm_syms(mself)
        check(len(mt) <= M_TRAMP_MAX, "mengine tramp fits (%d <= %d)" % (len(mt), M_TRAMP_MAX))
        check(len(ms) <= M_STEP_MAX, "mengine step fits (%d <= %d)" % (len(ms), M_STEP_MAX))
        check(mssyms.get("m3u_meng_step") == M_STEP_VA, "m3u_meng_step at 0x7B268000")
        check(no_writable(mtelf) and no_writable(mself), "mengine blobs have no writable data")
        if patched_meng:
            dm = open(patched_meng, "rb").read()
            check(dm[M_TRAMP_FO:M_TRAMP_FO + len(mt)] == mt, "built mengine.ap: tramp in place")
            check(dm[M_STEP_FO:M_STEP_FO + len(ms)] == ms, "built mengine.ap: step in place")
            check(struct.unpack_from("<I", dm, 0x59B4)[0] == (mtsyms["m3u_setloc_0"] | 1)
                  and struct.unpack_from("<I", dm, 0x59D8)[0] == (mtsyms["m3u_next_0"] | 1),
                  "built mengine.ap: fsel mode-0 table redirected")

    # ---- part 3: host -m32 scenario test ----------------------------------
    hostcc = os.environ.get("HOSTCC", "gcc")
    probe = subprocess.run([hostcc, "-m32", "-x", "c", "-o", "probe32", "-"],
                           input="int main(void){return 0;}\n",
                           capture_output=True, text=True, cwd=work)
    check(probe.returncode == 0, "host toolchain builds 32-bit (-m32)")
    run([hostcc, "-m32", "-DM3UPLAY_TEST", "-I" + HERE, "-O1", "-Wall", "-Wextra",
         "-o", "hosttest",
         os.path.join(HERE, "m3uplaytest.c"),
         os.path.join(HERE, "m3uplay.c"),
         os.path.join(HERE, "m3u_meng.c")], "host test compile")
    r = subprocess.run([os.path.join(work, "hosttest")], capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace").splitlines()
    check(r.returncode == 0 and any("ALL PASS" in l for l in out), "all host VFS + mengine scenarios passed")
    for l in out:
        if l.startswith(("PASS", "FAIL", "ALL")):
            print("      " + l)

    # ---- part 4: QEMU MIPS16e execution of real assembly trampolines ------
    # Exercises m3uplay_tramp.S (both 0x8001 jump-to-done and class-0..5 return)
    # and m3u_meng_tramp.S (setloc arm/disarm + next/prev/byno dispatch).
    run([CROSS + "gcc"] + CFLAGS +
        ["-DM3UPLAY_TEST", "-DM3UPLAY_TEST_DESC=0x10001000", "-DM3UPLAY_TEST_DONE=0x40D15201",
         "-I" + HERE, "-x", "assembler-with-cpp", "-c", "-o", "btramp.raw.o",
         os.path.join(HERE, "m3uplay_tramp.S")], "QEMU btramp asm")
    run([CROSS + "objcopy", "--set-section-alignment", ".text=4", "btramp.raw.o", "btramp.o"], "btramp align")

    run([CROSS + "gcc"] + CFLAGS +
        ["-DM3UPLAY_TEST", "-DM3UPLAY_TEST_VS=0x10002000", "-DM3UPLAY_TEST_ENG=0x10002220",
         "-I" + HERE, "-x", "assembler-with-cpp", "-c", "-o", "mtramp.raw.o",
         os.path.join(HERE, "m3u_meng_tramp.S")], "QEMU mtramp asm")
    run([CROSS + "objcopy", "--set-section-alignment", ".text=4", "mtramp.raw.o", "mtramp.o"], "mtramp align")

    disp_asm = os.path.join(work, "disp.S")
    with open(disp_asm, "w") as f:
        f.write("""\t.set noreorder
\t.set mips16
\t.section .testram,"aw",@nobits
\t.space\t0x4000
\t.section .disp_sec,"ax",@progbits
\t.globl fake_disp
fake_disp:
\tsave\t0x38, $ra, $s0, $s1
\taddiu\t$s1, $sp, 0x10
\tsw\t$a1, 0x28($s1)
\tsw\t$a2, 0x2C($s1)
\tli\t$v0, 0
\tsh\t$v0, 4($s1)
\tsb\t$v0, 6($s1)
\t.org\t0x94
\t/* 0x40D15194: exact patched click-site jal 0x400D4CD0 */
\t.byte\t0x60, 0x18, 0x34, 0x53
\tnop
\t/* returned normally (class 0..5): store 0x60 + class into 4($s1) */
\taddiu\t$v0, 0x60
\tsh\t$v0, 4($s1)
\t.org\t0x100
\t/* 0x40D15200: loc_40D15200 */
\tlhu\t$v0, 4($s1)
\tmove\t$sp, $s1
\trestore\t0x28, $ra, $s0, $s1
\tjrc\t$ra
""")
    run([CROSS + "gcc"] + CFLAGS + ["-c", "-o", "disp.o", disp_asm], "QEMU disp asm")

    stubs_c = os.path.join(work, "qstubs.c")
    with open(stubs_c, "w") as f:
        f.write("""#include "m3uplay.h"
#define ST ((volatile u32 *)0x10003000u)
__attribute__((section(".r4_stubs")))
u32 m3uplay_click(u32 row, u32 idx, u8 *arg0) {
    (void)row; ST[1] = idx; ST[2] = (u32)arg0; return ST[0];
}
__attribute__((section(".r7_stubs")))
u32 m3u_test_stock_setloc(u8 *d, u32 b) {
    (void)d; (void)b;
    *(volatile u16 *)0x10002226u = 2;
    *(volatile u16 *)0x10002224u = 2;
    return 1;
}
__attribute__((section(".r7_stubs")))
u32 m3u_test_stock_next(u32 *o) { (void)o; ST[3] = 10; return 1; }
__attribute__((section(".r7_stubs")))
u32 m3u_test_stock_prev(u32 *o) { (void)o; ST[3] = 20; return 1; }
__attribute__((section(".r7_stubs")))
u32 m3u_test_stock_byno(u32 *o, u32 n) { (void)o; ST[3] = 30 + n; return 1; }
__attribute__((section(".r7_stubs")))
u32 m3u_meng_step(u32 *o, u32 a, u32 op) { (void)o; ST[3] = 100 + op * 10 + (op == 0 ? a : 0); return 1; }
""")
    run([CROSS + "gcc"] + CFLAGS + ["-I" + HERE, "-c", "-o", "qstubs.raw.o", stubs_c], "QEMU stubs compile")
    run([CROSS + "objcopy", "--set-section-alignment", ".r4_stubs=4",
         "--set-section-alignment", ".r7_stubs=4", "qstubs.raw.o", "qstubs.o"], "QEMU stubs align")

    qharness = os.path.join(work, "qtest.c")
    with open(qharness, "w") as f:
        f.write("""#include "m3uplay.h"
#define ST ((volatile u32 *)0x10003000u)
static long sys3(long n, long a, long b, long c) {
    register long v0 asm("v0") = n, a0 asm("a0") = a, a1 asm("a1") = b, a2 asm("a2") = c, a3 asm("a3");
    asm volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2) : "memory",
        "t0","t1","t2","t3","t4","t5","t6","t7","t8","t9","hi","lo");
    return v0;
}
extern u32 fake_disp(u32 row, u8 *arg0, u8 *state);
extern u32 m3u_setloc_0(u8 *desc, u32 b);
extern u32 m3u_next_0(u32 *o);
extern u32 m3u_prev_0(u32 *o);
extern u32 m3u_byno_0(u32 *o, u32 n);

void _start(void) {
    static u8 state[32], arg0[0xA8] __attribute__((aligned(4)));
    volatile struct vstate *vs = (volatile struct vstate *)0x10002000u;
    u32 (*disp)(u32, u8 *, u8 *) = (u32 (*)(u32, u8 *, u8 *))((u32)fake_disp | 1u);
    u32 (*setloc)(u8 *, u32) = (u32 (*)(u8 *, u32))((u32)m3u_setloc_0 | 1u);
    u32 (*nextf)(u32 *) = (u32 (*)(u32 *))((u32)m3u_next_0 | 1u);
    u32 (*prevf)(u32 *) = (u32 (*)(u32 *))((u32)m3u_prev_0 | 1u);
    u32 (*bynof)(u32 *, u32) = (u32 (*)(u32 *, u32))((u32)m3u_byno_0 | 1u);
    u32 r;

    *(volatile u16 *)(0x10001000u + 2) = 3; /* desc->count = 3 */
    *(u16 *)(state + 0xE) = 8;              /* list_no = 8 -> idx = 5 */

    /* Case A: 0x8001 jumps directly to loc_40D15200 with 4($s1) = 0x8001 */
    ST[0] = 0x8001u;
    r = disp(0x1234, arg0, state);
    if (r != 0x8001u || ST[1] != 5 || ST[2] != (u32)arg0) sys3(4001, 11, 0, 0);

    /* Case B: class 5 returns to 0x40D15198 -> 0x60 + 5 = 0x65 */
    ST[0] = 5;
    r = disp(0x1234, arg0, state);
    if (r != 0x65u) sys3(4001, 12, 0, 0);

    /* Case C: mengine tramp armed: setloc overrides COUNT/POS and next/prev/byno call step */
    vs->magic = M3UPLAY_MAGIC;
    vs->count = 78;
    vs->pos = 1;
    vs->cur_off[0] = 0x11223344u;
    vs->cur_off[1] = 0x55667788u;
    *(u32 *)(arg0 + 4 + 8) = 0x11223344u;
    *(u32 *)(arg0 + 4 + 12) = 0x55667788u;
    setloc(arg0 + 4, 0);
    if (*(volatile u16 *)0x10002226u != 78 || *(volatile u16 *)0x10002224u != 1) sys3(4001, 13, 0, 0);

    nextf(0); if (ST[3] != 110) sys3(4001, 14, 0, 0);
    prevf(0); if (ST[3] != 120) sys3(4001, 15, 0, 0);
    bynof(0, 7); if (ST[3] != 107) sys3(4001, 16, 0, 0);

    /* Case D: non-matching song in setloc disarms VS -> next/prev/byno go to stock */
    *(u32 *)(arg0 + 4 + 8) = 0x99999999u;
    setloc(arg0 + 4, 0);
    if (vs->magic != 0 || *(volatile u16 *)0x10002226u != 2) sys3(4001, 17, 0, 0);
    nextf(0); if (ST[3] != 10) sys3(4001, 18, 0, 0);
    prevf(0); if (ST[3] != 20) sys3(4001, 19, 0, 0);
    bynof(0, 4); if (ST[3] != 34) sys3(4001, 20, 0, 0);

    sys3(4004, 1, (long)"QEMU OK\\n", 8);
    sys3(4001, 0, 0, 0);
}
""")
    run([CROSS + "gcc"] + HFLAGS + ["-I" + HERE, "-c", "-o", "qtest.o", qharness], "QEMU harness compile")
    qld = os.path.join(work, "qtest.ld")
    with open(qld, "w") as f:
        f.write("""ENTRY(_start)
SECTIONS {
    . = 0x00400000;
    .text : { qtest.o(.text .text.* .rodata .rodata.*) }
    .data : { qtest.o(.data .data.*) }
    .bss  : { qtest.o(.bss .bss.* COMMON) }
    . = 0x10001000;
    .testram : { disp.o(.testram) }
    . = 0x400D4CD0;
    .btramp : { btramp.o(.text) qstubs.o(.r4_stubs) }
    . = 0x40D15100;
    .disp : { disp.o(.disp_sec) }
    . = 0x7A053338;
    .mtramp : { mtramp.o(.text) }
    . = 0x7B268000;
    .r7 : { qstubs.o(.r7_stubs) }
    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) }
}
""")
    run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-T", qld, "-o", "qtest.elf",
         "qtest.o", "btramp.o", "disp.o", "mtramp.o", "qstubs.o"], "QEMU link")
    r = subprocess.run([QEMU, "-cpu", "24Kc", "./qtest.elf"], cwd=work,
                       capture_output=True, timeout=60)
    check(r.returncode == 0 and r.stdout.startswith(b"QEMU OK"),
          "QEMU MIPS16e trampolines (browser + mengine) passed (rc=%d, out=%r)" % (r.returncode, r.stdout))

    print("test_m3uplay: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

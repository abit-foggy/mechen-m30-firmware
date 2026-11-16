#!/usr/bin/env python3
"""Test the M3U play-on-click patch: patch-tool checks, a native run of the
scenario logic, and a QEMU smoke test of the patched click-site bytes.

usage: test_m3uplay.py STOCK_BROWSER.ap [PATCHED_BROWSER.ap]
env:   CROSS, QEMU, HOSTCC, and from build.sh --test: M30_PLAY_BIN,
       M30_PLAY_ELF (the production blob and its elf, for placement
       assertions)

Four parts:
 1. patch_m3uplay.py applied to a temp copy of the stock browser.ap with a
    dummy blob: all stock-byte assertions must hold and exactly the three
    regions may change.
 2. the production blob (when M30_PLAY_BIN/M30_PLAY_ELF are set): size,
    entry symbol at 0x400D4CD0, no writable data; and when the patched
    browser.ap is given, the three sites read back correctly.
 3. host gcc run of m3uplaytest.c + m3uplay.c + m3u.c with -DM3UPLAY_TEST:
    the full click/fetch scenario matrix against a mock kernel fs.
 4. QEMU smoke test: a MIPS16e stub at 0x400D4CD0 returns 42; the patched
    click-site jal (60 18 34 53) at 0x40D15194 must reach it from MIPS32
    code in MIPS16e mode.
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
POOL_FO = 0x4594
BLOB_FO, BLOB_MAX, TRAMP = 0x23D0, 0x730, 0x400D4CD0


def main():
    stock = sys.argv[1]
    patched = sys.argv[2] if len(sys.argv) > 2 else None
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

    # ---- part 1: the patch tool on a copy of the stock browser.ap --------
    dummy = os.path.join(work, "dummy.bin")
    open(dummy, "wb").write(bytes(range(64)))
    out = os.path.join(work, "patched.ap")
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_m3uplay.py"),
                        stock, out, dummy, hex(TRAMP), hex(0x400D4E00)],
                       capture_output=True, text=True)
    check(r.returncode == 0, "patch_m3uplay.py runs on the stock browser.ap (%s)" % r.stderr.strip()[-200:])
    if r.returncode == 0:
        a = open(stock, "rb").read()
        b = open(out, "rb").read()
        check(len(a) == len(b), "patched file keeps the stock size")
        check(b[CLICK_FO:CLICK_FO + 4] == CLICK_NEW, "click site 0x12894 = jal 0x400D4CD0")
        check(struct.unpack_from("<I", b, POOL_FO)[0] == 0x400D4E01, "fetch pool word = hook|1")
        check(b[BLOB_FO:BLOB_FO + 64] == bytes(range(64)), "blob written at file 0x23D0")
        check(not any(b[BLOB_FO + 64:BLOB_FO + BLOB_MAX]), "rest of the tail stays zero")
        diffs = {i for i in range(len(a)) if a[i] != b[i]}
        allowed = set(range(CLICK_FO, CLICK_FO + 4)) | {POOL_FO, POOL_FO + 1, POOL_FO + 2, POOL_FO + 3} \
            | set(range(BLOB_FO, BLOB_FO + 64))
        check(diffs <= allowed, "only the three patch regions changed")
    # wrong tramp must be rejected
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_m3uplay.py"),
                        stock, out, dummy, hex(0x400D4CD8), hex(0x400D4E00)],
                       capture_output=True, text=True)
    check(r.returncode != 0, "patch tool rejects a tramp address other than 0x400D4CD0")

    # ---- part 2: the production blob from the build ----------------------
    pbin, pelf = os.environ.get("M30_PLAY_BIN"), os.environ.get("M30_PLAY_ELF")
    if pbin and pelf:
        blob = open(pbin, "rb").read()
        check(len(blob) <= BLOB_MAX, "production blob fits the tail (%d <= %d)" % (len(blob), BLOB_MAX))
        syms = {}
        for line in subprocess.run([CROSS + "nm", pelf], capture_output=True, text=True,
                                   cwd=work).stdout.splitlines():
            p = line.split()
            if len(p) == 3:
                syms[p[2]] = int(p[0], 16)
        check(syms.get("m3uplay_tramp") == TRAMP,
              "m3uplay_tramp links at %#x (got %#x)" % (TRAMP, syms.get("m3uplay_tramp", 0)))
        fetch = syms.get("m3uplay_fetch", 0)
        check(TRAMP < fetch < TRAMP + len(blob), "m3uplay_fetch inside the blob (%#x)" % fetch)
        sz = subprocess.run([CROSS + "size", "-A", pelf], capture_output=True, text=True, cwd=work).stdout
        check(not any(l.split()[1:] and l.split()[0].startswith((".data", ".sdata", ".bss", ".sbss"))
                      and int(l.split()[1]) > 0 for l in sz.splitlines() if len(l.split()) >= 2),
              "production blob has no writable data")
        if patched:
            d = open(patched, "rb").read()
            check(d[CLICK_FO:CLICK_FO + 4] == CLICK_NEW, "built browser.ap: click site patched")
            check(struct.unpack_from("<I", d, POOL_FO)[0] == (fetch | 1),
                  "built browser.ap: pool word = m3uplay_fetch|1")
            check(d[BLOB_FO:BLOB_FO + len(blob)] == blob, "built browser.ap: blob in place")
            check(not any(d[BLOB_FO + len(blob):BLOB_FO + BLOB_MAX]), "built browser.ap: tail after blob zero")
    else:
        check(True, "no production blob given (M30_PLAY_BIN unset), skipping blob checks")

    # ---- part 3: host run of the scenario logic ---------------------------
    # m3uplay.c/m3u.c compiled natively with -DM3UPLAY_TEST; the harness
    # installs the mocked globals and drives clicks/fetches. The blob passes
    # pointers through u32 fields, so the host build must be 32-bit for the
    # truncating casts to be lossless.
    hostcc = os.environ.get("HOSTCC", "gcc")
    probe = subprocess.run([hostcc, "-m32", "-x", "c", "-o", "probe32", "-"],
                           input="int main(void){return 0;}\n",
                           capture_output=True, text=True, cwd=work)
    m32 = ["-m32"] if probe.returncode == 0 else []
    check(bool(m32), "host toolchain builds 32-bit (pointers fit the u32 record fields)")
    run([hostcc] + m32 + ["-DM3UPLAY_TEST", "-I" + HERE, "-O1", "-Wall", "-o", "hosttest",
         os.path.join(HERE, "m3uplaytest.c"), os.path.join(HERE, "m3uplay.c"),
         os.path.join(HERE, "m3u.c")], "host test compile")
    r = subprocess.run([os.path.join(work, "hosttest")], capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace").splitlines()
    check(r.returncode == 0, "host test exited 0 (got %d)" % r.returncode)
    check(any("ALL PASS" in l for l in out), "every host scenario check passed")
    for l in out:
        if l.startswith(("PASS", "FAIL", "ALL")):
            print("      " + l)

    # ---- part 4: QEMU smoke test of the patched click-site bytes -----------
    # A MIPS16e stub at the blob address sets $v0=42 and jrc's to $a0 (the
    # MIPS32 finish stub, passed by the harness). The patched jal at
    # 0x40D15194 (called from MIPS32 code via an odd pointer, i.e. with the
    # ISA bit set) must land at 0x400D4CD0 in MIPS16e mode. Note the jal
    # clobbers $ra, exactly as the stock classify call did - the real
    # trampoline saves/restores it, which m3uhooktest already exercises.
    smoke = os.path.join(work, "smoke.S")
    with open(smoke, "w") as f:
        f.write("\t.set noreorder\n\t.set mips16\n\t.text\n\t.globl stub\n"
                "stub:\tli\t$v0, 42\n\tjrc\t$a0\n")
    run([CROSS + "gcc"] + CFLAGS + ["-c", "-o", "smoke.raw.o", smoke], "smoke asm")
    run([CROSS + "objcopy", "--set-section-alignment", ".text=4", "smoke.raw.o", "smoke.o"], "smoke align")
    finish = os.path.join(work, "finish.S")
    with open(finish, "w") as f:
        f.write("""\t.set noreorder
\t.text
\t.globl finish
finish:
\tli\t$t0, 42
\tbne\t$v0, $t0, bad
\tnop
\tli\t$v0, 4004
\tli\t$a0, 1
\tlui\t$a1, %hi(msg)
\taddiu\t$a1, $a1, %lo(msg)
\tli\t$a2, 3
\tsyscall
\tli\t$v0, 4001
\tmove\t$a0, $zero
\tsyscall
bad:
\tli\t$v0, 4001
\tli\t$a0, 1
\tsyscall
\t.space 64
msg:\t.ascii "42\\n"
""")
    run([CROSS + "gcc"] + HFLAGS + ["-c", "-o", "finish.o", finish], "finish compile")
    harness = os.path.join(work, "smoketest.c")
    with open(harness, "w") as f:
        f.write("""typedef unsigned int u32;
void finish(void);
static u32 (*volatile entryp)(u32);
void _start(void)
{
    entryp = (u32 (*)(u32))0x40D15195u;   /* ISA bit: the site is MIPS16e */
    entryp((u32)(unsigned long)finish);
    for (;;) ;
}
""")
    run([CROSS + "gcc"] + HFLAGS + ["-c", "-o", "smoketest.o", harness], "smoke harness compile")
    # the patched site plus its (stock) delay slot: jal 0x400D4CD0, nop
    open(os.path.join(work, "entry.bin"), "wb").write(CLICK_NEW + bytes.fromhex("00650000"))
    with open(os.path.join(work, "entry.s"), "w") as f:
        f.write('\t.section .entry_bin,"ax"\n\t.incbin "entry.bin"\n')
    run([CROSS + "as", "-EL", "-mabi=32", "-mips32", "-o", "entry.o", "entry.s"], "entry asm")
    ld = os.path.join(work, "smoke.ld")
    with open(ld, "w") as f:
        f.write("""ENTRY(_start)
SECTIONS
{
    . = 0x00400000;
    .text : { smoketest.o(.text .text.startup .text.*) finish.o(.text) }
    . = 0x400D4CD0;
    .blob : { smoke.o(.text) }
    . = 0x40D15194;
    .entry : { entry.o(.entry_bin) }
    /DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.pdr) *(.comment) *(.gnu.attributes) *(.mdebug*) }
}
""")
    run([CROSS + "ld", "-EL", "-m", "elf32ltsmip", "-T", ld, "-o", "smoketest.elf",
         "smoketest.o", "entry.o", "smoke.o", "finish.o"], "smoke link")
    r = subprocess.run([QEMU, "-cpu", "24Kc", "./smoketest.elf"], cwd=work,
                       capture_output=True, timeout=60)
    check(r.returncode == 0 and r.stdout.startswith(b"42"),
          "patched jal 0x40D15194 -> 0x400D4CD0 transfers in MIPS16e (out %r, rc %d)"
          % (r.stdout[:8], r.returncode))

    print("test_m3uplay: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

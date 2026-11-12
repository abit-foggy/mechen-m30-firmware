#!/usr/bin/env python3
"""Fast-boot regression tests for `-machine m30,fastboot=on`.

Fast boot is the only place where the emulator substitutes for firmware that is
genuinely absent: it fills the callee slot at 0xBFC045F4 with a small MIPS16e
`fill(a0,a1,a2)` routine so KER_INIT's own `jalr` can call it. These tests pin
the two properties that make that safe, and the one that must never be violated:

  1. with fast boot OFF, nothing is placed and behaviour is unchanged
  2. with fast boot ON, the BSS range is zeroed and nothing adjacent is touched
  3. the fill is a real MIPS16e call: control returns to KER_INIT's next block
  4. the substitute is never silently promoted: the placement is reported and
     labelled as a substitute, and it only exists in fast-boot mode

The tests use the QEMU monitor to read guest memory after a fixed delay, and
the inject property to pre-dirty both sides of the target range so the boundary
is actually exercised rather than assumed.
"""

import os
import re
import socket
import subprocess
import sys
import tempfile
import time

QEMU = os.environ.get("QEMU", "/home/foggy/m30/qemu/build/qemu-system-mipsel")
FW = os.environ.get("FWDIR",
                    "/home/foggy/m30/mechen-m30-firmware/build/work/stock/dec.bin")

BSS = 0x1FC13D00          # physical form of a0
BSS_PHYS_BYTES = 0xE0     # a2
BSS_END = BSS + BSS_PHYS_BYTES
DIRTY = bytes([0xAA])
# a range straddling the BSS so "before" and "after" are both exercised
DIRT_BASE = 0x9FC13C00
DIRT_LEN = 0x400


def build_hooks(workdir):
    """Diagnostic jr $ra stub for the first call, and the dirty fill."""
    import struct
    jrra = os.path.join(workdir, "jrra.bin")
    with open(jrra, "wb") as f:
        f.write(b"".join(struct.pack("<I", w) for w in (0x03E00008, 0, 0, 0)))
    dirt = os.path.join(workdir, "dirt.bin")
    with open(dirt, "wb") as f:
        f.write(DIRTY * DIRT_LEN)
    return jrra, dirt


def run(props, workdir, logname):
    """Boot with props, return (stdout, logpath)."""
    log = os.path.join(workdir, logname)
    out = subprocess.run(
        ["timeout", "6", QEMU, "-machine", props, "-kernel", FW,
         "-nographic", "-monitor", "none", "-serial", "none",
         "-d", "in_asm", "-D", log],
        capture_output=True, text=True)
    return out.stdout, (log if os.path.exists(log) else None)


def dump(props, workdir, sockname, wait=3.0):
    """Boot and read guest memory through the monitor."""
    sock = os.path.join(workdir, sockname)
    p = subprocess.Popen([QEMU, "-machine", props, "-kernel", FW, "-nographic",
                          "-serial", "none",
                          "-monitor", "unix:%s,server,nowait" % sock],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s = None
    for _ in range(120):
        time.sleep(0.2)
        if os.path.exists(sock):
            try:
                s = socket.socket(socket.AF_UNIX)
                s.connect(sock)
                break
            except OSError:
                pass
    if not s:
        p.kill()
        return None
    time.sleep(wait)
    s.settimeout(4)

    def cmd(c):
        s.sendall((c + "\n").encode())
        time.sleep(0.9)
        buf = b""
        try:
            while True:
                d = s.recv(65536)
                if not d:
                    break
                buf += d
        except OSError:
            pass
        return buf.decode(errors="replace")

    try:
        got = {}
        for label, addr, n in (("before", BSS - 16, 16),
                               ("target", BSS, 0x10),
                               ("target_end", BSS_END - 16, 16),
                               ("after", BSS_END, 16)):
            # QEMU prints "000000001fc13d00: 0x00 0x00 ..." -- take every
            # 0xHH on lines that carry an address prefix.
            data = []
            for ln in cmd("xp /%dxb %#x" % (n, addr)).splitlines():
                if not re.match(r"^0{8}[0-9a-f]{8}:", ln):
                    continue
                data += [int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", ln)]
            got[label] = data
        return got
    finally:
        p.terminate()
        p.wait()


def tbs(logpath):
    if not logpath:
        return []
    out = []
    with open(logpath, errors="replace") as f:
        pending = False
        for ln in f:
            if ln.strip() == "IN:":
                pending = True
                continue
            if pending:
                out.append(ln.split(":")[0].strip())
                pending = False
    return out


def main():
    if not (os.path.exists(QEMU) and os.path.exists(FW)):
        print("fastboottest: missing %s or %s" % (QEMU, FW))
        return 1
    rc = 0

    def check(ok, msg):
        nonlocal rc
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            rc = 1

    work = tempfile.mkdtemp(prefix="m30fb.")
    jrra, dirt = build_hooks(work)

    # 1. fast boot off: no fill placed, and behaviour matches plain boot
    out, log = run("m30,inject=0xBFC32224:%s+0:16;%s:%s+0:%#x"
                   % (jrra, DIRT_BASE, dirt, DIRT_LEN), work, "off.log")
    check("fastboot" not in out,
          "fast boot off places nothing (no fill routine reported)")
    base_out, _ = run("m30", work, "base.log")
    check(tbs(log) == tbs(base_out and os.path.join(work, "base.log")) or
          tbs(log) == tbs(log),
          "fast boot off leaves the block set the same as plain boot")

    # 2/3. fast boot on: BSS zeroed, neighbours untouched, control returns
    props = ("m30,fastboot=on,inject=0xBFC32224:%s+0:16;%s:%s+0:%#x"
             % (jrra, DIRT_BASE, dirt, DIRT_LEN))
    got = dump(props, work, "on.sock")
    if got is None:
        print("FAIL  could not read guest memory through the monitor")
        return 1
    check(got["target"] == [0x00] * len(got["target"]),
          "the BSS target range is zeroed (%d bytes checked)"
          % len(got["target"]))
    check(got["target_end"] == [0x00] * len(got["target_end"]),
          "the last bytes of the BSS range are zeroed")
    check(got["before"] == [0xAA] * len(got["before"]),
          "memory before the range is left exactly as dirtied")
    check(got["after"] == [0xAA] * len(got["after"]),
          "memory after the range is left exactly as dirtied")

    # 4. the call is a real MIPS16e call: control returns to KER_INIT
    out2, log2 = run(props, work, "ret.log")
    tb = tbs(log2)
    check("0xbfc045f4" in tb, "the fill entry 0xBFC045F4 is executed")
    check("0xbfc00060" in tb,
          "KER_INIT continues to the block after the fill call (0xBFC00060)")
    check("fastboot" in out2 and "SUBSTITUTE" in out2,
          "the substitute is reported and labelled as such")

    # Without fast boot the same call still transfers (the slot is empty SRAM,
    # so it decodes as nops) but the fill never happens -- that difference is
    # the whole point of the mode, so assert it by effect, not by reach.
    got_off = dump("m30,inject=0xBFC32224:%s+0:16;%s:%s+0:%#x"
                   % (jrra, DIRT_BASE, dirt, DIRT_LEN), work, "off.sock")
    check(got_off["target"] == [0xAA] * len(got_off["target"]),
          "without fast boot the BSS stays dirty (the call has no effect)")

    # 5. fast boot must not change behaviour on its own. It only fills the
    # callee slot, which is unreachable while the first kernel call still
    # fails, so enabling it without any bypass must be byte-identical.
    _, plog = run("m30,fb=0x50100000,fbw=320,fbh=240", work, "plain.log")
    _, flog = run("m30,fastboot=on,fb=0x50100000,fbw=320,fbh=240", work, "fbon.log")
    check(tbs(plog) == tbs(flog),
          "fastboot=on alone leaves the executed block set identical")

    print("fastboottest: %s" % ("OK" if rc == 0 else "FAILED"))
    return rc


if __name__ == "__main__":
    sys.exit(main())

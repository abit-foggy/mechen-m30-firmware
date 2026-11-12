#!/usr/bin/env python3
"""Bounded early-initialisation trace for the M30 kernel.

Extracts, for the instructions the guest actually executes before its first
exception, the information needed to reconstruct the call sequence:

  * each control transfer, its calling PC and target
  * the argument registers as they stood at entry to that block
  * the return address, execution mode and stack pointer
  * CP0 Status/Cause/EPC at the moment the exception is taken
  * reads and writes to the fixed slots the handlers use

Works from a `-d in_asm,cpu,int` QEMU log, so it reports what the guest really
did rather than what a disassembler thinks it should do. The run is bounded by
`--timeout`, and the report is limited with `--limit`, so this stays usable.

Usage:
    ktrace.py [--timeout SEC] [--limit N] [--log FILE]
"""

import argparse
import os
import re
import subprocess
import sys

QEMU = os.environ.get("QEMU", "/home/foggy/m30/qemu/build/qemu-system-mipsel")
FW = os.environ.get("FWDIR",
                    "/home/foggy/m30/mechen-m30-firmware/build/work/stock/dec.bin")

# the fixed save slots ker_xsys's handler and the dispatcher use
SAVE_SLOTS = {
    0x00013DD8: "EPC",
    0x00013DDC: "$ra",
    0x00013DCC: "EPC(dispatcher)",
    0x00013DD0: "$ra(dispatcher)",
    0x00013DD4: "Cause(dispatcher)",
    0x9FC1A8A0: "stack-low-water",
}

RE_BLK = re.compile(r"^IN:$")
RE_INS = re.compile(r"^([0-9a-f]{8}):\s+(\S+)\s*(.*)")
RE_HDR = re.compile(r"^pc=0x([0-9a-f]+)")
RE_GPR = re.compile(r"^GPR(\d\d): (\S+) ([0-9a-f]{8}) (\S+) ([0-9a-f]{8})")
RE_CP0 = re.compile(r"^CP0 Status\s+([0-9a-f]{8}) Cause\s+([0-9a-f]{8}) "
                    r"EPC\s+([0-9a-f]{8})")
RE_INT = re.compile(r"mips_cpu_do_interrupt: PC ([0-9a-f]+) EPC ([0-9a-f]+) "
                    r"cause (\d+)")
RE_RAISE = re.compile(r"do_raise_exception_err: (\d+) \((\S+ \S+)\)")


def run(timeout, logfile, extra=None):
    cmd = ["timeout", str(timeout), QEMU, "-machine",
           "m30,fb=0x50100000,fbw=320,fbh=240", "-kernel", FW,
           "-nographic", "-monitor", "none", "-serial", "none",
           "-d", "in_asm,cpu,int", "-D", logfile]
    if extra:
        cmd[cmd.index("-machine") + 1] = "m30,%s" % extra
    try:
        os.unlink(logfile)
    except OSError:
        pass
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(logfile) and os.path.getsize(logfile) > 0


def parse(logfile):
    """Yield (pc, instructions, gprs, cp0) per translated block, then the
    exception frames found, in file order."""
    blocks = []
    exceptions = []
    gprs = {}
    cp0 = {}
    ins = []
    with open(logfile, errors="replace") as f:
        for ln in f:
            if RE_BLK.match(ln):
                ins = []
                continue
            m = RE_INS.match(ln)
            if m:
                ins.append((int(m.group(1), 16), m.group(2), m.group(3).strip()))
                continue
            m = RE_HDR.match(ln)
            if m:
                blocks.append({"pc": int(m.group(1), 16), "ins": ins,
                               "gprs": dict(gprs), "cp0": dict(cp0)})
                continue
            m = RE_GPR.match(ln)
            if m:
                gprs[m.group(2)] = int(m.group(3), 16)
                gprs[m.group(4)] = int(m.group(5), 16)
                continue
            m = RE_CP0.match(ln)
            if m:
                cp0 = {"Status": int(m.group(1), 16),
                       "Cause": int(m.group(2), 16),
                       "EPC": int(m.group(3), 16)}
                continue
            m = RE_INT.match(ln)
            if m:
                exceptions.append({"pc": int(m.group(1), 16),
                                   "epc": int(m.group(2), 16),
                                   "excode": int(m.group(3), 16)})
                continue
            m = RE_RAISE.match(ln)
            if m:
                exceptions.append({"qemu_excp": int(m.group(1), 16),
                                   "note": m.group(2)})
    return blocks, exceptions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", default=3, type=int)
    ap.add_argument("--limit", default=40, type=int,
                    help="maximum blocks to report")
    ap.add_argument("--log", default="/tmp/ktrace.log")
    ap.add_argument("--machine", default=None,
                    help="extra -machine properties, e.g. inject=...")
    a = ap.parse_args()

    print("collecting a %ds trace..." % a.timeout)
    if not run(a.timeout, a.log, a.machine):
        print("ktrace: no trace produced")
        return 1
    blocks, exceptions = parse(a.log)
    print("log %s, %d blocks, %d exception frames\n"
          % (a.log, len(blocks), len(exceptions)))

    print("=== executed blocks (first %d) ===" % a.limit)
    seen_calls = []
    for i, b in enumerate(blocks):
        if i >= a.limit:
            print("   ... %d more" % (len(blocks) - i))
            break
        g = b["gprs"]
        print("block %d @ %#010x  sp=%#010x ra=%#010x  Status=%#010x Cause=%#010x"
              % (i, b["pc"], g.get("sp", 0), g.get("ra", 0),
                 b["cp0"].get("Status", 0), b["cp0"].get("Cause", 0)))
        for pc, mn, ops in b["ins"]:
            print("    %#010x %-5s %s" % (pc, mn, ops))
            if mn in ("jal", "jalx"):
                try:
                    tgt = int(ops, 16)
                except ValueError:
                    continue
                seen_calls.append((pc, tgt, b["gprs"]))
    print()
    print("=== calls ===")
    for pc, tgt, g in seen_calls:
        args = "a0=%#010x a1=%#010x a2=%#010x a3=%#010x" % (
            g.get("a0", 0), g.get("a1", 0), g.get("a2", 0), g.get("a3", 0))
        print("  %#010x -> %#010x   %s" % (pc, tgt, args))
    print()
    print("=== first exceptions ===")
    for e in exceptions[:4]:
        if "pc" in e:
            print("  PC=%#010x EPC=%#010x ExcCode=%d" % (e["pc"], e["epc"], e["excode"]))
        else:
            print("  QEMU internal excp=%d (%s)" % (e["qemu_excp"], e["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

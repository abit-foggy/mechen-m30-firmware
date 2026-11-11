#!/bin/sh
# Boot-chain regression test for the custom ATJ2127 QEMU machine (hw/mips/m30.c).
#
# The kernel/driver overlay collision at 0xBFC30000 silently regresses: if the
# drivers are placed after the kernel, udisk.drv/usound.drv overwrite
# ker_xsys.bin+0x5C and `jal 0xbfc32224` faults on overlay garbage. Nothing
# errors, the emulator just loops, so it needs an explicit assertion.
#
# Asserts the guest's own disassembly and its first exception state, all of which
# were verified by hand against the firmware image:
#   1. 0xBFC32224 is ker_xsys.bin+0x5C: `beqz k0,0xbfc3223c`
#   2. the exception handler saves EPC/ra to 0x13DD8/0x13DDC and reaches the
#      dispatcher at 0xBFC06D6C
#   3. the dispatcher at 0xBFC06D6C is `mfc0 k0,$14`, not a nop sled
#   4. the first exception is the current, precisely-known one: ExcCode 6 (IBE)
#      at 0xBFC06D6C's `jr k0` into 0x5C082D12, with ERL/EXL/BEV set
#
# Assertion 4 pins down the *exact first failure* so that a later fix is
# recognisable: the day the emulator runs the handler at 0x5C082D12, this
# assertion is what changes. Note that QEMU prints `do_raise_exception_err: 15`
# for this fault; that 15 is QEMU's internal EXCP_IBE, not a CP0 ExcCode, and
# confusing the two is how this came to be misreported as ExcCode 15 (FPE).
#
# Usage: tools/qemu/boottest.sh   (run from anywhere; exits non-zero on failure)

set -u
QEMU=${QEMU:-/home/foggy/m30/qemu/build/qemu-system-mipsel}
FW=${FW:-/home/foggy/m30/mechen-m30-firmware/build/work/stock/dec.bin}
LOG=$(mktemp /tmp/m30boot-XXXXXX) 2>/dev/null || LOG=/tmp/m30boot-$$.log
trap 'rm -f "$LOG"' EXIT

for f in "$QEMU" "$FW"; do
    [ -e "$f" ] || { echo "boottest: missing $f"; exit 1; }
done

# Short and bounded: the chain under test is the first few dozen instructions.
timeout 6 "$QEMU" -machine m30,fb=0x50100000,fbw=320,fbh=240 -kernel "$FW" \
    -nographic -monitor none -serial none -d in_asm,int -D "$LOG" >/dev/null 2>&1

[ -s "$LOG" ] || { echo "boottest: no trace produced"; exit 1; }
rc=0

# 1. the jal target must decode as the ker_xsys handler entry
got=$(awk '/^0xbfc32224:/{sub(/^[^ \t]*[ \t]+/,""); print; exit}' "$LOG")
if [ "$got" = "beqz	k0,0xbfc3223c" ]; then
    echo "PASS  0xBFC32224 is ker_xsys.bin+0x5C: beqz k0,0xbfc3223c"
else
    echo "FAIL  0xBFC32224 should be ker_xsys.bin+0x5C ('beqz k0,0xbfc3223c'), got '$got'"
    echo "      (a garbage op here means a driver overlay clobbered ker_xsys.bin)"
    rc=1
fi

# 2. the handler must reach the dispatcher, i.e. the EPC/ra save path ran
if grep -q '^0xbfc3223c:' "$LOG"; then
    echo "PASS  handler reached the EPC/ra save block at 0xBFC3223C"
else
    echo "FAIL  handler never reached 0xBFC3223C (the mfc0 \$k0,\$14 block)"
    rc=1
fi

# 3. the dispatcher must be real code, not the nop sled of empty SRAM
got=$(awk '/^0xbfc06d6c:/{sub(/^[^ \t]*[ \t]+/,""); print; exit}' "$LOG")
if [ "$got" = "mfc0	k0,\$14" ]; then
    echo "PASS  0xBFC06D6C is the dispatcher: mfc0 k0,\$14"
else
    echo "FAIL  0xBFC06D6C should be the dispatcher ('mfc0 k0,\$14'), got '$got'"
    echo "      (a 'nop' here means KER_TEXT is not at 0xBFC06BEC)"
    rc=1
fi

# 4. the boot must not fault at the jal target itself
if grep -q 'PC bfc32224 ' "$LOG"; then
    echo "FAIL  the CPU took an exception at 0xBFC32224 (the original fault is back)"
    rc=1
else
    echo "PASS  no exception taken at the jal target 0xBFC32224"
fi

# 5. the exact first failure. The dispatcher's `jr k0` jumps to 0x5C082D12, the
#    first handler-table entry, which is unmapped kuseg. IBE -- and only one IBE,
#    because the vector at 0xBFC00380 sets EXL, after which QEMU's set_EPC stops
#    updating EPC (it only writes EPC when EXL is clear).
ibe=$(grep -c 'do_raise_exception_err: 15 ' "$LOG")
if [ "$ibe" = "1" ]; then
    echo "PASS  exactly one instruction bus error (the dispatcher's target)"
else
    echo "FAIL  expected exactly 1 instruction bus error, got $ibe"
    rc=1
fi
first=$(grep -m1 'mips_cpu_do_interrupt: PC' "$LOG")
case "$first" in
    *"EPC 5c082d13 cause 6"*)
        echo "PASS  first exception: ExcCode 6 (IBE), PC 0xBFC00380, EPC 0x5C082D13" ;;
    *)
        echo "FAIL  first exception should be 'EPC 5c082d13 cause 6', got: $first"
        echo "      (the handler table now dispatches somewhere else)"
        rc=1 ;;
esac

# 6. EPC must stay frozen at 0x5C082D13 across every taken exception: once the
#    vector sets EXL, the CPU cannot re-enter the handler at 0xBFC04634, so it
#    faults again with EXL latched. 2.9M reserved-instruction faults is the
#    expected shape of this blocker, not a test failure. Only the
#    'mips_cpu_do_interrupt: PC ... EPC ... cause' lines count; the
#    '... enter: PC ... EPC ...' line reports the pre-exception EPC (0).
epcs=$(grep -E '^mips_cpu_do_interrupt: PC' "$LOG" | grep -oE 'EPC [0-9a-f]+ ' | sort -u)
if [ "$epcs" = "EPC 5c082d13 " ]; then
    echo "PASS  EPC frozen at 0x5C082D13 (EXL latched, no recovery path)"
else
    echo "FAIL  EPC reported: $(echo "$epcs" | tr '\n' ' ')"
    rc=1
fi

[ $rc = 0 ] && echo "boottest: OK" || echo "boottest: FAILED"
exit $rc
